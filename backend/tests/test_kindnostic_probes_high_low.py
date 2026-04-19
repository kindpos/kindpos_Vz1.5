"""
KINDnostic HIGH + LOW Probes Tests
====================================
Tests for all 9 HIGH/LOW probes: printers (2), hardware (3), system (4).
Printer probes use mock sockets. Hardware probes use graceful fallbacks.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from kindnostic.probes.printers import (
    probe_receipt_printer_reachable,
    probe_kitchen_printer_reachable,
)
from kindnostic.probes.hardware import (
    probe_ssd_health,
    probe_clock_sync,
    probe_display_resolution,
)
from kindnostic.probes.system import (
    probe_entomology_heartbeat,
    probe_network_interface,
    probe_last_boot_result,
    probe_uptime_since_last_close,
)
from kindnostic.types import Category, Status


# ═════════════════════════════════════════════════════════════
# FIXTURES
# ═════════════════════════════════════════════════════════════

def _create_hardware_db(db_path: str, devices: list[dict] | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            mac TEXT PRIMARY KEY, ip TEXT NOT NULL, type TEXT NOT NULL,
            name TEXT NOT NULL, port INTEGER NOT NULL DEFAULT 9100,
            register_id TEXT NOT NULL DEFAULT '', auth_key TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL
        )
    """)
    if devices:
        for d in devices:
            conn.execute(
                "INSERT INTO devices (mac, ip, type, name, port, saved_at) VALUES (?,?,?,?,?,?)",
                (d["mac"], d["ip"], d["type"], d["name"], d.get("port", 9100),
                 datetime.now(timezone.utc).isoformat()),
            )
    conn.commit()
    conn.close()


def _create_diag_db_with_summary(db_path: str, summaries: list[dict] | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boot_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, boot_id TEXT, timestamp TEXT,
            probe_name TEXT, category TEXT, status TEXT, duration_ms INTEGER,
            message TEXT, metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boot_summary (
            boot_id TEXT PRIMARY KEY, timestamp TEXT, total_probes INTEGER,
            passed INTEGER, warned INTEGER, failed INTEGER, duration_ms INTEGER,
            outcome TEXT NOT NULL, override_by TEXT
        )
    """)
    if summaries:
        for s in summaries:
            conn.execute(
                """INSERT INTO boot_summary
                   (boot_id, timestamp, total_probes, passed, warned, failed,
                    duration_ms, outcome)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (s["boot_id"], s["timestamp"], s.get("total_probes", 1),
                 s.get("passed", 1), s.get("warned", 0), s.get("failed", 0),
                 s.get("duration_ms", 100), s.get("outcome", "READY")),
            )
    conn.commit()
    conn.close()


def _create_ledger_with_close(db_path: str, close_timestamp: str | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL, timestamp TEXT NOT NULL,
            terminal_id TEXT NOT NULL, event_type TEXT NOT NULL,
            payload TEXT NOT NULL, user_id TEXT, user_role TEXT,
            correlation_id TEXT, previous_checksum TEXT,
            checksum TEXT NOT NULL, synced INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    if close_timestamp:
        conn.execute(
            """INSERT INTO events (event_id, timestamp, terminal_id, event_type,
                                   payload, checksum)
               VALUES (?, ?, 'terminal-01', 'DAY_CLOSED', '{}', 'abc')""",
            (f"close-{close_timestamp}", close_timestamp),
        )
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════
# PRINTER PROBES
# ═════════════════════════════════════════════════════════════

class TestReceiptPrinter:

    def test_pass_no_hardware_db(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_receipt_printer_reachable()
        assert result.status == Status.PASS
        assert result.metadata["configured"] is False

    def test_pass_no_printers_configured(self, tmp_path):
        db = str(tmp_path / "hw.db")
        _create_hardware_db(db)
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": db}):
            result = probe_receipt_printer_reachable()
        assert result.status == Status.PASS

    def test_warn_unreachable(self, tmp_path):
        db = str(tmp_path / "hw.db")
        _create_hardware_db(db, [
            {"mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.99.99", "type": "printer",
             "name": "Receipt Printer"},
        ])
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": db}):
            with patch("kindnostic.probes.printers._check_tcp_reachable", return_value=False):
                result = probe_receipt_printer_reachable()
        assert result.status == Status.WARN
        assert "unreachable" in result.message

    def test_pass_reachable(self, tmp_path):
        db = str(tmp_path / "hw.db")
        _create_hardware_db(db, [
            {"mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.100", "type": "printer",
             "name": "Receipt Printer"},
        ])
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": db}):
            with patch("kindnostic.probes.printers._check_tcp_reachable", return_value=True):
                result = probe_receipt_printer_reachable()
        assert result.status == Status.PASS
        assert result.metadata["reachable"] is True

    def test_category_is_high(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_receipt_printer_reachable()
        assert result.category == Category.HIGH


class TestKitchenPrinter:

    def test_pass_no_hardware_db(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_kitchen_printer_reachable()
        assert result.status == Status.PASS

    def test_warn_unreachable(self, tmp_path):
        db = str(tmp_path / "hw.db")
        _create_hardware_db(db, [
            {"mac": "AA:BB:CC:DD:EE:02", "ip": "192.168.99.99", "type": "printer",
             "name": "Kitchen Main"},
        ])
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": db}):
            with patch("kindnostic.probes.printers._check_tcp_reachable", return_value=False):
                result = probe_kitchen_printer_reachable()
        assert result.status == Status.WARN

    def test_pass_reachable(self, tmp_path):
        db = str(tmp_path / "hw.db")
        _create_hardware_db(db, [
            {"mac": "AA:BB:CC:DD:EE:02", "ip": "192.168.1.101", "type": "printer",
             "name": "Kitchen Main"},
        ])
        with patch.dict(os.environ, {"KINDPOS_HW_DB_PATH": db}):
            with patch("kindnostic.probes.printers._check_tcp_reachable", return_value=True):
                result = probe_kitchen_printer_reachable()
        assert result.status == Status.PASS


# ═════════════════════════════════════════════════════════════
# HARDWARE PROBES
# ═════════════════════════════════════════════════════════════

class TestSsdHealth:

    def test_pass_sufficient_space(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DATA_PATH": str(tmp_path)}):
            result = probe_ssd_health()
        assert result.status == Status.PASS
        assert result.metadata["free_mb"] > 0

    def test_warn_low_space(self, tmp_path):
        # Mock disk_usage to return low free space
        fake_usage = MagicMock()
        fake_usage.free = 100 * 1024 * 1024   # 100MB
        fake_usage.total = 32000 * 1024 * 1024  # 32GB
        with patch.dict(os.environ, {"KINDPOS_DATA_PATH": str(tmp_path)}):
            with patch("kindnostic.probes.hardware.shutil.disk_usage", return_value=fake_usage):
                result = probe_ssd_health()
        assert result.status == Status.WARN
        assert "Low disk space" in result.message

    def test_pass_missing_path(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DATA_PATH": str(tmp_path / "nope")}):
            result = probe_ssd_health()
        assert result.status == Status.PASS

    def test_category_is_high(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DATA_PATH": str(tmp_path)}):
            result = probe_ssd_health()
        assert result.category == Category.HIGH


class TestClockSync:

    def test_pass_current_time(self):
        result = probe_clock_sync()
        assert result.status == Status.PASS

    def test_warn_year_too_old(self):
        fake_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        with patch("kindnostic.probes.hardware.datetime") as mock_dt:
            mock_dt.now.return_value = fake_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = probe_clock_sync()
        assert result.status == Status.WARN
        assert "year < 2026" in result.message

    def test_warn_year_too_new(self):
        fake_time = datetime(2040, 6, 15, tzinfo=timezone.utc)
        with patch("kindnostic.probes.hardware.datetime") as mock_dt:
            mock_dt.now.return_value = fake_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = probe_clock_sync()
        assert result.status == Status.WARN
        assert "year > 2035" in result.message

    def test_category_is_high(self):
        result = probe_clock_sync()
        assert result.category == Category.HIGH


class TestDisplayResolution:

    def test_pass_no_framebuffer(self):
        """Non-Pi environment — no framebuffer device."""
        with patch("os.path.exists", return_value=False):
            result = probe_display_resolution()
        assert result.status == Status.PASS
        assert result.metadata["framebuffer"] is False

    def test_pass_correct_resolution(self, tmp_path):
        fb_dir = tmp_path / "fb0"
        fb_dir.mkdir()
        (fb_dir / "virtual_size").write_text("1024,600")
        with patch("kindnostic.probes.hardware.os.path.exists", return_value=True):
            with patch("kindnostic.probes.hardware.os.path.join",
                       return_value=str(fb_dir / "virtual_size")):
                result = probe_display_resolution()
        assert result.status == Status.PASS
        assert result.metadata["width"] == 1024
        assert result.metadata["height"] == 600

    def test_warn_wrong_resolution(self, tmp_path):
        fb_dir = tmp_path / "fb0"
        fb_dir.mkdir()
        (fb_dir / "virtual_size").write_text("1920,1080")
        with patch("kindnostic.probes.hardware.os.path.exists", return_value=True):
            with patch("kindnostic.probes.hardware.os.path.join",
                       return_value=str(fb_dir / "virtual_size")):
                result = probe_display_resolution()
        assert result.status == Status.WARN
        assert "1920x1080" in result.message

    def test_category_is_high(self):
        result = probe_display_resolution()
        assert result.category == Category.HIGH


# ═════════════════════════════════════════════════════════════
# SYSTEM PROBES
# ═════════════════════════════════════════════════════════════

class TestEntomologyHeartbeat:

    def test_pass_no_db(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_entomology_heartbeat()
        assert result.status == Status.PASS

    def test_pass_with_events(self, tmp_path):
        db = str(tmp_path / "diag.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE diagnostic_events (
                id INTEGER PRIMARY KEY, diagnostic_id TEXT UNIQUE,
                correlation_id TEXT, terminal_id TEXT, timestamp TEXT,
                category TEXT, severity TEXT, source TEXT, event_code TEXT,
                message TEXT, context TEXT, prev_hash TEXT, hash TEXT
            )
        """)
        conn.execute(
            """INSERT INTO diagnostic_events
               (diagnostic_id, terminal_id, timestamp, category, severity,
                source, event_code, message, context, prev_hash, hash)
               VALUES ('d1','t1','2026-04-04T10:00:00','SYSTEM','INFO',
                       'test','SYS-HEARTBEAT','ok','{}','','abc')"""
        )
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": db}):
            result = probe_entomology_heartbeat()
        assert result.status == Status.PASS
        assert result.metadata["event_count"] == 1

    def test_category_is_low(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_entomology_heartbeat()
        assert result.category == Category.LOW


class TestNetworkInterface:

    def test_pass_no_interfaces(self):
        """Non-Pi environment — no eth0/wlan0."""
        with patch("os.path.exists", return_value=False):
            result = probe_network_interface()
        assert result.status == Status.PASS
        assert result.metadata["has_ip"] is False

    def test_category_is_low(self):
        result = probe_network_interface()
        assert result.category == Category.LOW


class TestLastBootResult:

    def test_pass_no_db(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_last_boot_result()
        assert result.status == Status.PASS
        assert result.metadata["previous_boot"] is None

    def test_pass_previous_clean(self, tmp_path):
        db = str(tmp_path / "diag.db")
        _create_diag_db_with_summary(db, [{
            "boot_id": "boot-1",
            "timestamp": "2026-04-04T09:00:00+00:00",
            "passed": 5, "warned": 0, "failed": 0,
            "outcome": "READY",
        }])
        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": db}):
            result = probe_last_boot_result()
        assert result.status == Status.PASS

    def test_warn_previous_failures(self, tmp_path):
        db = str(tmp_path / "diag.db")
        _create_diag_db_with_summary(db, [{
            "boot_id": "boot-bad",
            "timestamp": "2026-04-04T09:00:00+00:00",
            "passed": 3, "warned": 1, "failed": 2,
            "outcome": "BLOCKED",
        }])
        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": db}):
            result = probe_last_boot_result()
        assert result.status == Status.WARN
        assert "2 failure(s)" in result.message

    def test_category_is_low(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DIAG_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_last_boot_result()
        assert result.category == Category.LOW


class TestUptimeSinceLastClose:

    def test_pass_no_ledger(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_uptime_since_last_close()
        assert result.status == Status.PASS

    def test_pass_recent_close(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        _create_ledger_with_close(db, recent)
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_uptime_since_last_close()
        assert result.status == Status.PASS
        assert result.metadata["hours_since_close"] < 48

    def test_warn_long_offline(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        _create_ledger_with_close(db, old)
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_uptime_since_last_close()
        assert result.status == Status.WARN
        assert "72" in result.message or "hours" in result.message

    def test_pass_no_close_events(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_close(db)  # no close timestamp
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = probe_uptime_since_last_close()
        assert result.status == Status.PASS

    def test_category_is_low(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": str(tmp_path / "nope.db")}):
            result = probe_uptime_since_last_close()
        assert result.category == Category.LOW
