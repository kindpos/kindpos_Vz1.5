"""
Tests for `app.core.ephemeral_log` — the non-chained SQLite log for
operational telemetry (printer status, drawer opens, retries).

ephemeral_log.py sat at 40%. These events never flow through the
immutable hash-chained ledger, so bugs here silently lose ops
visibility. Covered:

  - `append` writes a row; reconnect can see it
  - `append` without connect() raises cleanly
  - `purge_before` deletes rows older than a cutoff and returns count
  - async context manager opens + closes
  - EPHEMERAL_EVENT_TYPES is the authoritative routing set
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from app.core.ephemeral_log import EPHEMERAL_EVENT_TYPES, EphemeralLog
from app.core.events import EventType, create_event


TEST_DB = Path("./data/test_ephemeral_log.db")


@pytest_asyncio.fixture
async def log():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EphemeralLog(str(TEST_DB)) as _log:
        yield _log
    if TEST_DB.exists():
        TEST_DB.unlink()


def _event(event_type: EventType, payload: dict = None, *, timestamp: datetime = None):
    evt = create_event(
        event_type=event_type,
        terminal_id="T-1",
        payload=payload or {},
    )
    if timestamp is not None:
        evt = evt.model_copy(update={"timestamp": timestamp})
    return evt


class TestEphemeralAppend:

    @pytest.mark.asyncio
    async def test_append_persists_to_disk(self, log):
        evt = _event(EventType.PRINTER_STATUS_CHANGED, {"printer_id": "p1", "status": "offline"})
        await log.append(evt)

        # Read directly to confirm persistence survives this append
        async with aiosqlite.connect(str(TEST_DB)) as db:
            cur = await db.execute(
                "SELECT event_type, payload FROM ephemeral_events WHERE event_id = ?",
                (evt.event_id,),
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == EventType.PRINTER_STATUS_CHANGED.value

    @pytest.mark.asyncio
    async def test_append_without_connect_raises(self):
        """A disconnected log is a programmer error — raise, don't silently drop."""
        log = EphemeralLog(str(TEST_DB))
        with pytest.raises(RuntimeError) as exc:
            await log.append(_event(EventType.DRAWER_OPENED))
        assert "not connected" in str(exc.value)

    @pytest.mark.asyncio
    async def test_many_appends_ordered_by_timestamp(self, log):
        """Rapid-fire writes land in chronological order when queried."""
        base = datetime.now(timezone.utc)
        for i in range(10):
            await log.append(_event(
                EventType.PRINT_RETRYING,
                {"attempt": i},
                timestamp=base + timedelta(seconds=i),
            ))
        async with aiosqlite.connect(str(TEST_DB)) as db:
            cur = await db.execute(
                "SELECT payload FROM ephemeral_events ORDER BY timestamp ASC"
            )
            rows = await cur.fetchall()
        assert len(rows) == 10


class TestPurge:

    @pytest.mark.asyncio
    async def test_purge_deletes_rows_older_than_cutoff(self, log):
        old = datetime.now(timezone.utc) - timedelta(days=8)
        new = datetime.now(timezone.utc)

        await log.append(_event(EventType.DRAWER_OPENED, {"x": 1}, timestamp=old))
        await log.append(_event(EventType.DRAWER_OPENED, {"x": 2}, timestamp=old))
        await log.append(_event(EventType.DRAWER_OPENED, {"x": 3}, timestamp=new))

        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        deleted = await log.purge_before(cutoff)
        assert deleted == 2

        # Only the fresh row survived
        async with aiosqlite.connect(str(TEST_DB)) as db:
            cur = await db.execute("SELECT COUNT(*) FROM ephemeral_events")
            remaining = (await cur.fetchone())[0]
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_purge_with_nothing_to_delete_returns_zero(self, log):
        await log.append(_event(EventType.DRAWER_OPENED, {"x": 1}))
        cutoff = datetime.now(timezone.utc) - timedelta(days=365)
        assert (await log.purge_before(cutoff)) == 0

    @pytest.mark.asyncio
    async def test_purge_without_connect_raises(self):
        log = EphemeralLog(str(TEST_DB))
        with pytest.raises(RuntimeError):
            await log.purge_before(datetime.now(timezone.utc))


class TestContextManager:

    @pytest.mark.asyncio
    async def test_aenter_opens_and_aexit_closes(self):
        """`async with` connects and cleans up — the canonical usage path."""
        async with EphemeralLog(str(TEST_DB)) as log:
            assert log._db is not None
            await log.append(_event(EventType.DRAWER_OPENED))
        assert log._db is None

        # Subsequent operations fail because we're disconnected
        with pytest.raises(RuntimeError):
            await log.append(_event(EventType.DRAWER_OPENED))

        # Cleanup
        if TEST_DB.exists():
            TEST_DB.unlink()


class TestRoutingSet:
    """EPHEMERAL_EVENT_TYPES is the single source of truth for what
    goes into this log vs. the hash-chained ledger. Regressions here
    would quietly let ops events pollute the immutable chain."""

    def test_includes_printer_status(self):
        assert EventType.PRINTER_STATUS_CHANGED in EPHEMERAL_EVENT_TYPES
        assert EventType.PRINTER_ERROR in EPHEMERAL_EVENT_TYPES

    def test_includes_drawer_events(self):
        assert EventType.DRAWER_OPENED in EPHEMERAL_EVENT_TYPES
        assert EventType.DRAWER_OPEN_FAILED in EPHEMERAL_EVENT_TYPES

    def test_excludes_financial_events(self):
        """Money events must never be routed to the ephemeral (non-
        hashed) log. This test pins the invariant that makes audit
        possible."""
        assert EventType.PAYMENT_CONFIRMED not in EPHEMERAL_EVENT_TYPES
        assert EventType.PAYMENT_REFUNDED not in EPHEMERAL_EVENT_TYPES
        assert EventType.ORDER_CLOSED not in EPHEMERAL_EVENT_TYPES
        assert EventType.DAY_CLOSED not in EPHEMERAL_EVENT_TYPES
        assert EventType.BATCH_SUBMITTED not in EPHEMERAL_EVENT_TYPES
        assert EventType.TIP_ADJUSTED not in EPHEMERAL_EVENT_TYPES
