"""
Concurrency stress tests for `app.core.event_ledger.EventLedger`.

The ledger is the load-bearing wall of the app — every financial fact
lives in its hash-chained sequence. If concurrent appends can produce
duplicate sequence numbers, break the hash chain, or bypass the
idempotency gate, silent corruption follows.

These tests blast the ledger with asyncio.gather() batches and assert:

  - Every append gets a unique sequence_number, no gaps, no collisions
  - The hash chain across all appended events remains valid post-stress
  - Same idempotency_key hammered concurrently → exactly one winner
  - append_batch is atomic: either all events land or none do
  - Mixed append + append_batch under load still preserve ordering
"""

import asyncio
import hashlib
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.event_ledger import EventLedger
from app.core.events import EventType, create_event


TEST_DB = Path("./data/test_ledger_concurrency.db")


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


def _event(i: int, idem: str = None):
    return create_event(
        event_type=EventType.ORDER_CREATED,
        terminal_id=f"T{i}",
        payload={"order_id": f"o_{i}", "order_type": "dine_in", "guest_count": 1},
        idempotency_key=idem,
    )


# ═══════════════════════════════════════════════════════════════════════════
# CONCURRENT APPENDS
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrentAppends:

    @pytest.mark.asyncio
    async def test_50_concurrent_appends_get_unique_sequence_numbers(self, ledger):
        """Fire 50 appends with asyncio.gather(). Every result must have a
        distinct sequence_number — the write_lock plus SQLite autoinc
        should serialize them."""
        events = [_event(i) for i in range(50)]
        results = await asyncio.gather(*(ledger.append(e) for e in events))

        seqs = [r.sequence_number for r in results]
        assert len(seqs) == 50
        assert len(set(seqs)) == 50          # no duplicates
        assert min(seqs) == 1
        assert max(seqs) == 50

    @pytest.mark.asyncio
    async def test_sequence_numbers_are_contiguous(self, ledger):
        """No gaps between sequence numbers — gaps would indicate a
        half-committed write."""
        events = [_event(i) for i in range(30)]
        results = await asyncio.gather(*(ledger.append(e) for e in events))

        seqs = sorted(r.sequence_number for r in results)
        for a, b in zip(seqs, seqs[1:]):
            assert b == a + 1, f"gap between {a} and {b}"

    @pytest.mark.asyncio
    async def test_hash_chain_holds_under_concurrent_load(self, ledger):
        """After blasting 40 concurrent appends, replay the stored chain
        and verify every event's previous_checksum matches the one
        before it, and the checksum recomputes to the stored value."""
        events = [_event(i) for i in range(40)]
        await asyncio.gather(*(ledger.append(e) for e in events))

        all_events = await ledger.get_events_since(0, limit=1000)
        prev = ""
        for stored in all_events:
            assert stored.previous_checksum == prev, (
                f"chain broken at seq={stored.sequence_number}: "
                f"expected prev={prev[:8]!r}, got {stored.previous_checksum[:8]!r}"
            )
            recomputed = stored.compute_checksum(prev)
            assert stored.checksum == recomputed, (
                f"checksum mismatch at seq={stored.sequence_number}"
            )
            prev = stored.checksum


# ═══════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY GATE UNDER CONCURRENT LOAD
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrentIdempotency:

    @pytest.mark.asyncio
    async def test_same_key_hammered_concurrently_stores_exactly_once(self, ledger):
        """Ten parallel appends sharing one idempotency_key → one write
        plus nine blocked returns of None. This is the key contract the
        sync.replay_config_events route relies on."""
        key = "shared-idem-key"
        events = [_event(i, idem=key) for i in range(10)]
        results = await asyncio.gather(*(ledger.append(e) for e in events))

        winners = [r for r in results if r is not None]
        losers = [r for r in results if r is None]
        assert len(winners) == 1
        assert len(losers) == 9

        # And the ledger holds exactly one row
        stored = await ledger.get_events_since(0, limit=100)
        assert len(stored) == 1
        assert stored[0].idempotency_key == key

    @pytest.mark.asyncio
    async def test_distinct_keys_all_succeed(self, ledger):
        """No collision → no blocking; every event lands."""
        events = [_event(i, idem=f"distinct-key-{i}") for i in range(15)]
        results = await asyncio.gather(*(ledger.append(e) for e in events))
        winners = [r for r in results if r is not None]
        assert len(winners) == 15


# ═══════════════════════════════════════════════════════════════════════════
# APPEND_BATCH ATOMICITY
# ═══════════════════════════════════════════════════════════════════════════

class TestAppendBatch:

    @pytest.mark.asyncio
    async def test_batch_appends_contiguous_sequence_numbers(self, ledger):
        """A 10-event batch receives seqs [1..10] in order."""
        batch = [_event(i) for i in range(10)]
        results = await ledger.append_batch(batch)

        seqs = [r.sequence_number for r in results]
        assert seqs == list(range(1, 11))

    @pytest.mark.asyncio
    async def test_batch_rejects_any_non_2dp_monetary_event_before_writing(self, ledger):
        """The precision gate runs over the whole batch *before* any
        INSERT, so a single bad row must not leave partial writes."""
        good = create_event(
            event_type=EventType.ORDER_CREATED,
            terminal_id="T1",
            payload={"order_id": "o_good", "order_type": "dine_in"},
        )
        # 3-dp price = precision violation
        bad = create_event(
            event_type=EventType.ITEM_ADDED,
            terminal_id="T1",
            payload={
                "order_id": "o_bad", "item_id": "i1", "menu_item_id": "m1",
                "name": "Bad", "price": 9.999, "quantity": 1,
            },
        )

        with pytest.raises(ValueError):
            await ledger.append_batch([good, bad])

        # Nothing should have landed — not even the "good" event
        stored = await ledger.get_events_since(0, limit=10)
        assert stored == []

    @pytest.mark.asyncio
    async def test_append_and_append_batch_interleaved(self, ledger):
        """Mix singletons + batch under concurrent load; all events land
        with unique, contiguous seqs and a valid chain."""
        async def do_single(i):
            await ledger.append(_event(i))

        async def do_batch(start):
            batch = [_event(i) for i in range(start, start + 5)]
            await ledger.append_batch(batch)

        # 10 singles + 2 batches of 5 = 20 events total, interleaved
        await asyncio.gather(
            *(do_single(i) for i in range(10)),
            do_batch(100), do_batch(200),
        )

        stored = await ledger.get_events_since(0, limit=100)
        seqs = sorted(s.sequence_number for s in stored)
        assert seqs == list(range(1, 21))
        # Chain intact
        prev = ""
        for e in stored:
            assert e.previous_checksum == prev
            assert e.checksum == e.compute_checksum(prev)
            prev = e.checksum


# ═══════════════════════════════════════════════════════════════════════════
# SYNC LEDGER TRACKING
# ═══════════════════════════════════════════════════════════════════════════

class TestSyncLedger:
    """The `sync_ledger` table tracks which events have been shipped
    to the Overseer. Testing the mark+query path gives us confidence
    that no event gets double-synced or quietly skipped."""

    @pytest.mark.asyncio
    async def test_unsynced_events_include_every_append(self, ledger):
        for i in range(5):
            await ledger.append(_event(i))
        unsynced = await ledger.get_unsynced_events(limit=100)
        assert len(unsynced) == 5

    @pytest.mark.asyncio
    async def test_mark_synced_removes_from_unsynced(self, ledger):
        for i in range(3):
            await ledger.append(_event(i))
        unsynced = await ledger.get_unsynced_events(limit=10)
        # Sync two of the three
        await ledger.mark_synced([e.event_id for e in unsynced[:2]])

        remaining = await ledger.get_unsynced_events(limit=10)
        assert len(remaining) == 1
        assert remaining[0].event_id == unsynced[2].event_id
