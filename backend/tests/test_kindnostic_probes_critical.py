"""
KINDnostic CRITICAL Probes Tests
=================================
Tests for all 5 CRITICAL probes: hash_chain_integrity, precision_gate,
database_integrity, database_writable, schema_version.

Each probe is tested against both healthy and corrupted/broken fixtures.
"""

import hashlib
import json
import os
import sqlite3
from unittest.mock import patch

import pytest

from kindnostic.probes.hash_chain import probe_hash_chain_integrity, _compute_checksum
from kindnostic.probes.precision_gate import probe_precision_gate
from kindnostic.probes.database import (
    probe_database_integrity,
    probe_database_writable,
    probe_schema_version,
)
from kindnostic.types import Category, Status


# ═════════════════════════════════════════════════════════════
# FIXTURES — Build real SQLite event ledger DBs for testing
# ═════════════════════════════════════════════════════════════

def _create_ledger_db(db_path: str, events: list[dict] | None = None) -> None:
    """Create a valid event ledger DB with optional events."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            terminal_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            user_id TEXT,
            user_role TEXT,
            correlation_id TEXT,
            previous_checksum TEXT,
            checksum TEXT NOT NULL,
            synced INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    if events:
        previous_checksum = ""
        for ev in events:
            checksum = _compute_checksum(
                ev["event_id"], ev["timestamp"], ev["terminal_id"],
                ev["event_type"], ev["payload"], previous_checksum,
            )
            conn.execute(
                """INSERT INTO events
                   (event_id, timestamp, terminal_id, event_type, payload,
                    previous_checksum, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ev["event_id"], ev["timestamp"], ev["terminal_id"],
                    ev["event_type"], json.dumps(ev["payload"]),
                    previous_checksum, checksum,
                ),
            )
            previous_checksum = checksum

    conn.commit()
    conn.close()


def _make_test_events(count: int = 5) -> list[dict]:
    """Generate a sequence of valid test events."""
    events = []
    for i in range(count):
        events.append({
            "event_id": f"evt-{i:04d}",
            "timestamp": f"2026-04-04T10:{i:02d}:00+00:00",
            "terminal_id": "terminal-01",
            "event_type": "ORDER_CREATED",
            "payload": {"order_id": f"order-{i:04d}", "price": 9.99},
        })
    return events


def _create_hardware_db(db_path: str) -> None:
    """Create a valid hardware_config DB."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            mac TEXT PRIMARY KEY,
            ip TEXT NOT NULL,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 9100,
            register_id TEXT NOT NULL DEFAULT '',
            auth_key TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _create_diagnostic_db(db_path: str) -> None:
    """Create a valid diagnostic_boot DB."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boot_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boot_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            probe_name TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_ms INTEGER,
            message TEXT,
            metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boot_summary (
            boot_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            total_probes INTEGER,
            passed INTEGER,
            warned INTEGER,
            failed INTEGER,
            duration_ms INTEGER,
            outcome TEXT NOT NULL,
            override_by TEXT
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def healthy_env(tmp_path):
    """Create a complete healthy environment with all DBs."""
    ledger = str(tmp_path / "event_ledger.db")
    hw = str(tmp_path / "hardware_config.db")
    diag = str(tmp_path / "diagnostic_boot.db")

    _create_ledger_db(ledger, _make_test_events(5))
    _create_hardware_db(hw)
    _create_diagnostic_db(diag)

    env = {
        "KINDPOS_DB_PATH": ledger,
        "KINDPOS_HW_DB_PATH": hw,
        "KINDPOS_DIAG_DB_PATH": diag,
    }
    with patch.dict(os.environ, env):
        yield tmp_path


# ═════════════════════════════════════════════════════════════
# HASH CHAIN INTEGRITY
# ═════════════════════════════════════════════════════════════

class TestHashChainIntegrity:

    def test_pass_healthy_chain(self, healthy_env):
        result = probe_hash_chain_integrity()
        assert result.status == Status.PASS
        assert result.metadata["events_checked"] == 5
        assert result.metadata["chain_valid"] is True

    def test_pass_empty_ledger(self, tmp_path):
        """Empty ledger (no events) should PASS."""
        db = str(tmp_path / "empty.db")
        _create_ledger_db(db)
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_hash_chain_integrity()
        assert result.status == Status.PASS
        assert result.metadata["events_checked"] == 0

    def test_pass_no_db_file(self, tmp_path):
        """Missing DB file = fresh system, PASS."""
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_hash_chain_integrity()
        assert result.status == Status.PASS

    def test_fail_tampered_checksum(self, tmp_path):
        """Directly modify a checksum — chain should break."""
        db = str(tmp_path / "tampered.db")
        _create_ledger_db(db, _make_test_events(5))

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE events SET checksum = 'deadbeef' WHERE sequence_number = 3"
        )
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_hash_chain_integrity()
        assert result.status == Status.FAIL
        assert result.metadata["failed_sequence"] == 3

    def test_fail_tampered_payload(self, tmp_path):
        """Modify event payload — recomputed hash won't match stored."""
        db = str(tmp_path / "tampered_payload.db")
        _create_ledger_db(db, _make_test_events(5))

        conn = sqlite3.connect(db)
        conn.execute(
            """UPDATE events SET payload = '{"order_id": "HACKED", "price": 0.01}'
               WHERE sequence_number = 2"""
        )
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_hash_chain_integrity()
        assert result.status == Status.FAIL
        assert result.metadata["failed_sequence"] == 2

    def test_fail_broken_chain_link(self, tmp_path):
        """Modify previous_checksum — chain link breaks."""
        db = str(tmp_path / "broken_link.db")
        _create_ledger_db(db, _make_test_events(5))

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE events SET previous_checksum = 'wrong' WHERE sequence_number = 4"
        )
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_hash_chain_integrity()
        assert result.status == Status.FAIL
        assert result.metadata["failed_sequence"] == 4

    def test_category_is_critical(self, healthy_env):
        result = probe_hash_chain_integrity()
        assert result.category == Category.CRITICAL


# ═════════════════════════════════════════════════════════════
# PRECISION GATE
# ═════════════════════════════════════════════════════════════

class TestPrecisionGate:

    def test_pass_healthy_db(self, healthy_env):
        result = probe_precision_gate()
        assert result.status == Status.PASS
        assert result.metadata["values_tested"] == 8
        assert result.metadata["drift_detected"] is False

    def test_pass_no_db_file(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_precision_gate()
        assert result.status == Status.PASS

    def test_rollback_leaves_no_trace(self, healthy_env):
        """Probe should not leave any temp tables behind."""
        db_path = os.environ["KINDPOS_DB_PATH"]
        probe_precision_gate()

        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row[0] for row in tables}
        conn.close()

        assert "_precision_test" not in table_names

    def test_category_is_critical(self, healthy_env):
        result = probe_precision_gate()
        assert result.category == Category.CRITICAL


# ═════════════════════════════════════════════════════════════
# DATABASE INTEGRITY
# ═════════════════════════════════════════════════════════════

class TestDatabaseIntegrity:

    def test_pass_healthy_dbs(self, healthy_env):
        result = probe_database_integrity()
        assert result.status == Status.PASS

    def test_skips_missing_dbs(self, tmp_path):
        """Missing DBs are skipped, not failed."""
        env = {
            "KINDPOS_DB_PATH": str(tmp_path / "nope.db"),
            "KINDPOS_HW_DB_PATH": str(tmp_path / "nope2.db"),
            "KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope3.db"),
        }
        with patch.dict(os.environ, env):
            result = probe_database_integrity()
        assert result.status == Status.PASS
        for entry in result.metadata["checked"]:
            assert entry["status"] == "skipped"

    def test_fail_corrupted_db(self, healthy_env):
        """Write garbage to a DB file to corrupt it."""
        db_path = os.environ["KINDPOS_DB_PATH"]
        # Corrupt the DB by overwriting part of it
        with open(db_path, "r+b") as f:
            f.seek(100)
            f.write(b"\x00" * 200)

        result = probe_database_integrity()
        assert result.status == Status.FAIL

    def test_category_is_critical(self, healthy_env):
        result = probe_database_integrity()
        assert result.category == Category.CRITICAL


# ═════════════════════════════════════════════════════════════
# DATABASE WRITABLE
# ═════════════════════════════════════════════════════════════

class TestDatabaseWritable:

    def test_pass_healthy_dbs(self, healthy_env):
        result = probe_database_writable()
        assert result.status == Status.PASS
        for entry in result.metadata["checked"]:
            assert entry["status"] in ("writable", "skipped")

    def test_skips_missing_dbs(self, tmp_path):
        env = {
            "KINDPOS_DB_PATH": str(tmp_path / "nope.db"),
            "KINDPOS_HW_DB_PATH": str(tmp_path / "nope2.db"),
            "KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope3.db"),
        }
        with patch.dict(os.environ, env):
            result = probe_database_writable()
        assert result.status == Status.PASS

    def test_fail_unwritable_db(self, tmp_path):
        """Point at a directory instead of a file — SQLite can't write."""
        bad_dir = str(tmp_path / "not_a_file" / "")
        os.makedirs(bad_dir, exist_ok=True)
        hw = str(tmp_path / "hw.db")
        diag = str(tmp_path / "diag.db")
        _create_hardware_db(hw)
        _create_diagnostic_db(diag)
        env = {
            "KINDPOS_DB_PATH": bad_dir,
            "KINDPOS_HW_DB_PATH": hw,
            "KINDPOS_DIAG_DB_PATH": diag,
        }
        with patch.dict(os.environ, env):
            result = probe_database_writable()
        assert result.status == Status.FAIL
        assert any(f["db"] == "event_ledger" for f in result.metadata["failures"])

    def test_category_is_critical(self, healthy_env):
        result = probe_database_writable()
        assert result.category == Category.CRITICAL


# ═════════════════════════════════════════════════════════════
# SCHEMA VERSION
# ═════════════════════════════════════════════════════════════

class TestSchemaVersion:

    def test_pass_correct_schemas(self, healthy_env):
        result = probe_schema_version()
        assert result.status == Status.PASS

    def test_fail_missing_table(self, healthy_env):
        """Drop a required table and verify schema check fails."""
        db_path = os.environ["KINDPOS_DB_PATH"]
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE events")
        conn.commit()
        conn.close()

        result = probe_schema_version()
        assert result.status == Status.FAIL
        assert any(
            f["db"] == "event_ledger" for f in result.metadata["failures"]
        )

    def test_skips_missing_dbs(self, tmp_path):
        env = {
            "KINDPOS_DB_PATH": str(tmp_path / "nope.db"),
            "KINDPOS_HW_DB_PATH": str(tmp_path / "nope2.db"),
            "KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope3.db"),
        }
        with patch.dict(os.environ, env):
            result = probe_schema_version()
        assert result.status == Status.PASS

    def test_category_is_critical(self, healthy_env):
        result = probe_schema_version()
        assert result.category == Category.CRITICAL
