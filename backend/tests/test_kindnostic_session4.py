"""
KINDnostic Session 4 Tests
===========================
Entomology integration, boot history, probe trends, and alert queue.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from kindnostic.alerts import AlertQueue
from kindnostic.entomology import (
    GENESIS_HASH,
    _compute_diagnostic_hash,
    write_boot_diagnostic,
)
from kindnostic.storage import BootStorage
from kindnostic.types import Category, ProbeResult, Status


# ═════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════

def _make_results(specs: list[tuple[str, Category, Status]]) -> list[tuple[ProbeResult, int]]:
    """Build a list of (ProbeResult, duration_ms) tuples."""
    return [
        (ProbeResult(probe_name=name, category=cat, status=st, message=f"{name} msg" if st != Status.PASS else None), 50)
        for name, cat, st in specs
    ]


# ═════════════════════════════════════════════════════════════
# BOOT HISTORY + PROBE TRENDS (storage.py)
# ═════════════════════════════════════════════════════════════

class TestBootHistory:

    def test_get_boot_history_empty(self, tmp_path):
        with BootStorage(str(tmp_path / "test.db")) as s:
            assert s.get_boot_history() == []

    def test_get_boot_history_returns_recent_first(self, tmp_path):
        with BootStorage(str(tmp_path / "test.db")) as s:
            for i in range(5):
                s.record_summary(f"boot-{i}", 1, 1, 0, 0, 100, "READY")
            history = s.get_boot_history(n=3)
        assert len(history) == 3
        # Most recent first
        assert history[0]["boot_id"] == "boot-4"
        assert history[2]["boot_id"] == "boot-2"

    def test_get_boot_history_respects_limit(self, tmp_path):
        with BootStorage(str(tmp_path / "test.db")) as s:
            for i in range(10):
                s.record_summary(f"boot-{i}", 1, 1, 0, 0, 100, "READY")
            history = s.get_boot_history(n=5)
        assert len(history) == 5


class TestProbeTrend:

    def test_get_probe_trend_empty(self, tmp_path):
        with BootStorage(str(tmp_path / "test.db")) as s:
            assert s.get_probe_trend("dummy") == []

    def test_get_probe_trend_returns_history(self, tmp_path):
        with BootStorage(str(tmp_path / "test.db")) as s:
            for i in range(5):
                s.record_result(
                    boot_id=f"boot-{i}",
                    probe_name="receipt_printer_reachable",
                    category="HIGH",
                    status="PASS" if i % 2 == 0 else "WARN",
                    duration_ms=42,
                    message=None if i % 2 == 0 else "unreachable",
                )
            trend = s.get_probe_trend("receipt_printer_reachable", n=10)
        assert len(trend) == 5
        # Most recent first
        assert trend[0]["boot_id"] == "boot-4"

    def test_get_probe_trend_filters_by_name(self, tmp_path):
        with BootStorage(str(tmp_path / "test.db")) as s:
            s.record_result("boot-1", "dummy", "LOW", "PASS", 10)
            s.record_result("boot-1", "hash_chain_integrity", "CRITICAL", "PASS", 50)
            dummy_trend = s.get_probe_trend("dummy")
            chain_trend = s.get_probe_trend("hash_chain_integrity")
        assert len(dummy_trend) == 1
        assert len(chain_trend) == 1
        assert dummy_trend[0]["boot_id"] == "boot-1"


# ═════════════════════════════════════════════════════════════
# ENTOMOLOGY INTEGRATION
# ═════════════════════════════════════════════════════════════

class TestEntomologyIntegration:

    def test_writes_boot_diagnostic_event(self, tmp_path):
        db = str(tmp_path / "diag.db")
        results = _make_results([
            ("dummy", Category.LOW, Status.PASS),
            ("hash_chain", Category.CRITICAL, Status.PASS),
        ])
        diag_id = write_boot_diagnostic(
            boot_id="boot-123",
            outcome="READY",
            results=results,
            total_duration_ms=500,
            terminal_id="terminal-01",
            db_path=db,
        )
        assert diag_id  # Non-empty UUID string

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT * FROM diagnostic_events WHERE diagnostic_id = ?", (diag_id,)
        ).fetchone()
        conn.close()

        assert row is not None

    def test_event_has_correct_fields(self, tmp_path):
        db = str(tmp_path / "diag.db")
        results = _make_results([
            ("hash_chain", Category.CRITICAL, Status.FAIL),
        ])
        diag_id = write_boot_diagnostic(
            boot_id="boot-fail",
            outcome="BLOCKED",
            results=results,
            total_duration_ms=200,
            terminal_id="term-01",
            db_path=db,
        )

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute(
            "SELECT * FROM diagnostic_events WHERE diagnostic_id = ?", (diag_id,)
        ).fetchone())
        conn.close()

        assert row["category"] == "SYSTEM"
        assert row["severity"] == "CRITICAL"
        assert row["source"] == "KINDnostic"
        assert row["event_code"] == "SYS-BOOT-DIAG"
        assert "BLOCKED" in row["message"]
        assert row["correlation_id"] == "boot-fail"

        ctx = json.loads(row["context"])
        assert ctx["outcome"] == "BLOCKED"
        assert ctx["failed"] == 1
        assert len(ctx["failures"]) == 1

    def test_severity_info_for_clean_boot(self, tmp_path):
        db = str(tmp_path / "diag.db")
        results = _make_results([("dummy", Category.LOW, Status.PASS)])
        write_boot_diagnostic("boot-ok", "READY", results, 100, db_path=db)

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT severity FROM diagnostic_events").fetchone()
        conn.close()
        assert row[0] == "INFO"

    def test_severity_warning_for_warns(self, tmp_path):
        db = str(tmp_path / "diag.db")
        results = _make_results([
            ("ssd_health", Category.HIGH, Status.WARN),
        ])
        write_boot_diagnostic("boot-warn", "READY", results, 100, db_path=db)

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT severity FROM diagnostic_events").fetchone()
        conn.close()
        assert row[0] == "WARNING"

    def test_hash_chain_is_valid(self, tmp_path):
        """Multiple BOOT_DIAGNOSTIC events should form a valid hash chain."""
        db = str(tmp_path / "diag.db")

        for i in range(3):
            results = _make_results([("dummy", Category.LOW, Status.PASS)])
            write_boot_diagnostic(f"boot-{i}", "READY", results, 100, db_path=db)

        # Verify chain
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT diagnostic_id, timestamp, category, severity, source, "
            "event_code, message, context, prev_hash, hash "
            "FROM diagnostic_events ORDER BY id ASC"
        ).fetchall()
        conn.close()

        prev_hash = GENESIS_HASH
        for row in rows:
            diag_id, ts, cat, sev, src, code, msg, ctx_str, stored_prev, stored_hash = row
            ctx = json.loads(ctx_str)

            assert stored_prev == prev_hash

            expected = _compute_diagnostic_hash(
                prev_hash, diag_id, ts, cat, sev, src, code, msg, ctx
            )
            assert stored_hash == expected

            prev_hash = stored_hash

    def test_independent_from_event_ledger(self, tmp_path):
        """KINDnostic's diagnostic chain uses GENESIS_HASH, not the event ledger."""
        db = str(tmp_path / "diag.db")
        results = _make_results([("dummy", Category.LOW, Status.PASS)])
        write_boot_diagnostic("boot-1", "READY", results, 100, db_path=db)

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT prev_hash FROM diagnostic_events ORDER BY id ASC LIMIT 1"
        ).fetchone()
        conn.close()

        assert row[0] == GENESIS_HASH


# ═════════════════════════════════════════════════════════════
# ALERT QUEUE
# ═════════════════════════════════════════════════════════════

class TestAlertQueue:

    def test_no_alert_when_all_pass(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([("dummy", Category.LOW, Status.PASS)])
        with AlertQueue(db) as q:
            alert_id = q.enqueue("boot-1", "term-01", results)
        assert alert_id is None

    def test_enqueues_on_critical_fail(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("hash_chain_integrity", Category.CRITICAL, Status.FAIL),
        ])
        with AlertQueue(db) as q:
            alert_id = q.enqueue("boot-1", "term-01", results)
            assert alert_id is not None
            unsent = q.get_unsent()
        assert len(unsent) == 1
        assert unsent[0]["severity"] == "CRITICAL"
        assert "KN-HC" in unsent[0]["summary"]

    def test_enqueues_on_high_warn(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("ssd_health", Category.HIGH, Status.WARN),
        ])
        with AlertQueue(db) as q:
            alert_id = q.enqueue("boot-1", "term-01", results)
            assert alert_id is not None
            unsent = q.get_unsent()
        assert unsent[0]["severity"] == "WARNING"

    def test_mark_sent(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("hash_chain_integrity", Category.CRITICAL, Status.FAIL),
        ])
        with AlertQueue(db) as q:
            alert_id = q.enqueue("boot-1", "term-01", results)
            q.mark_sent(alert_id)
            unsent = q.get_unsent()
        assert len(unsent) == 0

    def test_increment_attempts(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("hash_chain_integrity", Category.CRITICAL, Status.FAIL),
        ])
        with AlertQueue(db) as q:
            alert_id = q.enqueue("boot-1", "term-01", results)
            q.increment_attempts(alert_id)
            q.increment_attempts(alert_id)
            unsent = q.get_unsent()
        assert unsent[0]["attempts"] == 2

    def test_flush_no_webhook_returns_zero(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("hash_chain_integrity", Category.CRITICAL, Status.FAIL),
        ])
        with AlertQueue(db) as q:
            q.enqueue("boot-1", "term-01", results)
            sent = q.flush()
        assert sent == 0

    def test_flush_sends_and_marks(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("hash_chain_integrity", Category.CRITICAL, Status.FAIL),
        ])

        # Mock successful HTTP POST
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with AlertQueue(db) as q:
            q.enqueue("boot-1", "term-01", results)
            with patch("kindnostic.alerts.urllib.request.urlopen", return_value=mock_resp):
                sent = q.flush(webhook_url="https://example.com/webhook")
            unsent = q.get_unsent()

        assert sent == 1
        assert len(unsent) == 0

    def test_flush_handles_network_error(self, tmp_path):
        db = str(tmp_path / "alerts.db")
        results = _make_results([
            ("hash_chain_integrity", Category.CRITICAL, Status.FAIL),
        ])

        with AlertQueue(db) as q:
            q.enqueue("boot-1", "term-01", results)
            with patch("kindnostic.alerts.urllib.request.urlopen",
                       side_effect=OSError("no network")):
                sent = q.flush(webhook_url="https://example.com/webhook")
            unsent = q.get_unsent()

        assert sent == 0
        assert len(unsent) == 1
        assert unsent[0]["attempts"] == 1


# ═════════════════════════════════════════════════════════════
# RUNNER INTEGRATION
# ═════════════════════════════════════════════════════════════

class TestRunnerIntegration:

    def test_run_all_writes_entomology_event(self, tmp_path):
        """Full run_all should produce a BOOT_DIAGNOSTIC in diagnostic_events."""
        db = str(tmp_path / "diag.db")
        from kindnostic.runner import run_all
        run_all(db_path=db)

        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT * FROM diagnostic_events WHERE event_code = 'SYS-BOOT-DIAG'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_run_all_creates_alert_queue_table(self, tmp_path):
        db = str(tmp_path / "diag.db")
        from kindnostic.runner import run_all
        run_all(db_path=db)

        conn = sqlite3.connect(db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alert_queue'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1
