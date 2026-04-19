"""
Tests for EventLedger.append_batch() and concurrent append behavior.

Verifies batch atomicity, hash chain continuity, and write lock correctness.
"""

import asyncio
import pytest
from app.core.event_ledger import EventLedger
from app.core.events import create_event, EventType, order_created, item_added


def _make_event(i: int, correlation_id: str = "order-batch"):
    """Helper to create a simple numbered event."""
    return item_added(
        terminal_id="T1",
        order_id=correlation_id,
        item_id=f"item-{i}",
        menu_item_id=f"menu-{i}",
        name=f"Item {i}",
        price=10.00,
        quantity=1,
    )


class TestAppendBatch:

    async def test_append_batch_returns_all_events(self, tmp_path):
        db = str(tmp_path / "batch_all.db")
        async with EventLedger(db) as ledger:
            events = [_make_event(i) for i in range(5)]
            results = await ledger.append_batch(events)
            assert len(results) == 5
            for r in results:
                assert r.sequence_number is not None

    async def test_append_batch_hash_chain_continuity(self, tmp_path):
        db = str(tmp_path / "batch_chain.db")
        async with EventLedger(db) as ledger:
            events = [_make_event(i) for i in range(10)]
            await ledger.append_batch(events)
            valid, first_invalid = await ledger.verify_chain()
            assert valid is True
            assert first_invalid is None

    async def test_append_batch_after_single_appends(self, tmp_path):
        db = str(tmp_path / "batch_mixed.db")
        async with EventLedger(db) as ledger:
            # Append 3 single events
            for i in range(3):
                await ledger.append(_make_event(i, correlation_id="order-single"))

            # Append batch of 5
            batch_events = [_make_event(i + 3, correlation_id="order-batch") for i in range(5)]
            await ledger.append_batch(batch_events)

            # Verify chain integrity across both
            valid, first_invalid = await ledger.verify_chain()
            assert valid is True
            assert first_invalid is None

            count = await ledger.count_events()
            assert count == 8

    async def test_append_batch_empty_list(self, tmp_path):
        db = str(tmp_path / "batch_empty.db")
        async with EventLedger(db) as ledger:
            results = await ledger.append_batch([])
            assert results == []

    async def test_append_batch_sequence_numbers_contiguous(self, tmp_path):
        db = str(tmp_path / "batch_seq.db")
        async with EventLedger(db) as ledger:
            # Append one event first so batch doesn't start at 1
            await ledger.append(_make_event(0))

            events = [_make_event(i + 1) for i in range(5)]
            results = await ledger.append_batch(events)

            seq_numbers = [r.sequence_number for r in results]
            # Should be contiguous: N+1, N+2, N+3, N+4, N+5
            assert seq_numbers == [2, 3, 4, 5, 6]

    async def test_concurrent_appends_no_duplicate_sequence(self, tmp_path):
        db = str(tmp_path / "concurrent.db")
        async with EventLedger(db) as ledger:
            # Launch 10 concurrent append() calls
            tasks = [
                ledger.append(_make_event(i, correlation_id=f"order-{i}"))
                for i in range(10)
            ]
            results = await asyncio.gather(*tasks)

            seq_numbers = [r.sequence_number for r in results]
            # All sequence numbers must be unique
            assert len(set(seq_numbers)) == 10
            # All should be in range 1..10
            assert sorted(seq_numbers) == list(range(1, 11))

    async def test_count_events(self, tmp_path):
        db = str(tmp_path / "count.db")
        async with EventLedger(db) as ledger:
            for i in range(5):
                await ledger.append(_make_event(i))
            count = await ledger.count_events()
            assert count == 5

    async def test_get_latest_sequence(self, tmp_path):
        db = str(tmp_path / "latest_seq.db")
        async with EventLedger(db) as ledger:
            for i in range(3):
                await ledger.append(_make_event(i))
            latest = await ledger.get_latest_sequence()
            assert latest == 3
