"""
Entomology System — Storage & Retention Tests (S-01 .. S-14)

Tests for SQLite schema, indexes, query operations,
and retention lifecycle (archive + delete).
"""

import json
import os
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
    GENESIS_HASH,
)
from app.services.diagnostic_collector import DiagnosticCollector


# ─── S-01: Table exists after connect ───────────────────

@pytest.mark.asyncio
async def test_s01_table_exists(collector):
    assert await collector.table_exists() is True


# ─── S-02: Expected indexes created ────────────────────

@pytest.mark.asyncio
async def test_s02_indexes_created(collector):
    indexes = await collector.get_indexes()
    expected = {
        "idx_diag_timestamp",
        "idx_diag_category",
        "idx_diag_severity",
        "idx_diag_event_code",
        "idx_diag_correlation",
    }
    assert expected.issubset(set(indexes))


# ─── S-03: WAL journal mode ────────────────────────────

@pytest.mark.asyncio
async def test_s03_wal_mode(collector):
    cursor = await collector._db.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    assert row[0] == "wal"


# ─── S-04: Record survives reconnect ───────────────────

@pytest.mark.asyncio
async def test_s04_data_survives_reconnect(tmp_path):
    db_path = str(tmp_path / "persist.db")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        await coll.record(
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.ERROR,
            source="Test",
            event_code="DEV-001",
            message="Persisted",
            context={"test": True},
        )

    # Reconnect and verify
    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        count = await coll.count_events()
        assert count == 1


# ─── S-05: Hash chain intact after reconnect ───────────

@pytest.mark.asyncio
async def test_s05_hash_chain_after_reconnect(tmp_path):
    db_path = str(tmp_path / "chain.db")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        e1 = await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="First",
            context={},
        )

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        e2 = await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Second",
            context={},
        )
        assert e2.prev_hash == e1.hash


# ─── S-06: Retention exports old events to JSON ────────

@pytest.mark.asyncio
async def test_s06_retention_exports(tmp_path):
    db_path = str(tmp_path / "retention.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        # Insert event with old timestamp by manipulating DB directly
        await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Old event",
            context={},
        )
        # Backdate the event to 100 days ago
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
        )
        await coll._db.commit()

        result = await coll.run_retention(
            retention_days=90,
            archive_dir=archive_dir,
        )
        assert result is not None
        assert os.path.exists(result)

        with open(result) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["message"] == "Old event"


# ─── S-07: Retention deletes archived events ───────────

@pytest.mark.asyncio
async def test_s07_retention_deletes(tmp_path):
    db_path = str(tmp_path / "retention_del.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Old",
            context={},
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
        )
        await coll._db.commit()

        await coll.run_retention(retention_days=90, archive_dir=archive_dir)
        count = await coll.count_events()
        assert count == 0


# ─── S-08: Retention keeps recent events ───────────────

@pytest.mark.asyncio
async def test_s08_retention_keeps_recent(tmp_path):
    db_path = str(tmp_path / "retention_keep.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        # One old, one recent
        await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Old",
            context={},
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ? WHERE message = 'Old'",
            (old_ts,),
        )
        await coll._db.commit()

        await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Recent",
            context={},
        )

        await coll.run_retention(retention_days=90, archive_dir=archive_dir)
        count = await coll.count_events()
        assert count == 1
        events = await coll.get_events()
        assert events[0].message == "Recent"


# ─── S-09: Retention returns None when nothing to archive ──

@pytest.mark.asyncio
async def test_s09_retention_nothing_to_archive(collector):
    result = await collector.run_retention(retention_days=90, archive_dir="./data")
    assert result is None


# ─── S-10: Archive JSON has correct structure ───────────

@pytest.mark.asyncio
async def test_s10_archive_json_structure(tmp_path):
    db_path = str(tmp_path / "archive_struct.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        await coll.record(
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.ERROR,
            source="TestAdapter",
            event_code="DEV-001",
            message="Archived event",
            context={"device_ip": "10.0.0.1"},
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
        )
        await coll._db.commit()

        result = await coll.run_retention(retention_days=90, archive_dir=archive_dir)
        with open(result) as f:
            data = json.load(f)

        record = data[0]
        expected_keys = {
            "diagnostic_id", "correlation_id", "terminal_id", "timestamp",
            "category", "severity", "source", "event_code", "message",
            "context", "prev_hash", "hash",
        }
        assert set(record.keys()) == expected_keys


# ─── S-11: Archive filename format ─────────────────────

@pytest.mark.asyncio
async def test_s11_archive_filename(tmp_path):
    db_path = str(tmp_path / "fname.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Test",
            context={},
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
        )
        await coll._db.commit()

        result = await coll.run_retention(
            retention_days=90,
            site_name="TestSite",
            archive_dir=archive_dir,
        )
        filename = os.path.basename(result)
        assert filename.startswith("TestSite_diag_archive_")
        assert filename.endswith(".json")


# ─── S-12: Multiple retention runs are idempotent ──────

@pytest.mark.asyncio
async def test_s12_retention_idempotent(tmp_path):
    db_path = str(tmp_path / "idempotent.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Old",
            context={},
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
        )
        await coll._db.commit()

        await coll.run_retention(retention_days=90, archive_dir=archive_dir)
        result2 = await coll.run_retention(retention_days=90, archive_dir=archive_dir)
        assert result2 is None  # Nothing left to archive


# ─── S-13: row_to_event round-trips correctly ──────────

@pytest.mark.asyncio
async def test_s13_row_to_event_roundtrip(collector):
    original = await collector.record(
        category=DiagnosticCategory.PERIPHERAL,
        severity=DiagnosticSeverity.WARNING,
        source="PrinterAdapter",
        event_code="PER-001",
        message="Printer connection failed",
        context={"printer_mac": "AA:BB:CC:DD:EE:FF"},
        correlation_id="order-999",
    )
    events = await collector.get_events()
    assert len(events) == 1
    restored = events[0]

    assert restored.diagnostic_id == original.diagnostic_id
    assert restored.correlation_id == original.correlation_id
    assert restored.terminal_id == original.terminal_id
    assert restored.category == original.category
    assert restored.severity == original.severity
    assert restored.source == original.source
    assert restored.event_code == original.event_code
    assert restored.message == original.message
    assert restored.context == original.context
    assert restored.prev_hash == original.prev_hash
    assert restored.hash == original.hash


# ─── S-14: Creates parent directory for DB ──────────────

@pytest.mark.asyncio
async def test_s14_creates_parent_dir(tmp_path):
    nested = tmp_path / "deep" / "nested" / "dir"
    db_path = str(nested / "test.db")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        assert await coll.table_exists() is True
    assert nested.exists()
