"""
KINDnostic Display + Boot UX Tests
====================================
Tests for HTML screen rendering, manager override PIN validation,
boot display server, and warning indicator.
"""

import json
import os
import sqlite3
import time
import urllib.request
from unittest.mock import patch

import pytest

from kindnostic.display import (
    BootDisplay,
    BootDisplayState,
    render_failure,
    render_progress,
    render_success,
    render_warning_indicator,
    validate_manager_pin,
)
from kindnostic.types import Category, ProbeResult, Status


# ═════════════════════════════════════════════════════════════
# HTML SCREEN RENDERING
# ═════════════════════════════════════════════════════════════

class TestRenderProgress:

    def test_contains_progress_bar(self):
        html = render_progress(3, 10, "hash_chain_integrity")
        assert "progress-fill" in html
        assert "30%" in html  # 3/10 = 30%
        assert "hash_chain_integrity" in html

    def test_shows_probe_count(self):
        html = render_progress(5, 15, "ssd_health")
        assert "[5/15]" in html

    def test_zero_total_no_crash(self):
        html = render_progress(0, 0, "init")
        assert "0%" in html

    def test_auto_refresh(self):
        html = render_progress(1, 5, "test")
        assert 'http-equiv="refresh"' in html


class TestRenderSuccess:

    def test_contains_checkmark(self):
        html = render_success()
        assert "&#10003;" in html or "✓" in html

    def test_contains_redirect(self):
        html = render_success()
        assert "http://localhost:8000" in html

    def test_no_warnings_no_badge(self):
        html = render_success()
        # The CSS class exists in the style block, but no actual badge element
        assert "warning(s)" not in html

    def test_warnings_shown(self):
        warnings = [
            {"probe": "ssd_health", "message": "Low disk space: 200MB"},
            {"probe": "clock_sync", "message": "Clock may be wrong"},
        ]
        html = render_success(warnings)
        assert "warning-badge" in html
        assert "2 warning(s)" in html
        assert "ssd_health" in html
        assert "Low disk space" in html


class TestRenderFailure:

    def test_contains_support_code(self):
        failed = [{"probe": "hash_chain_integrity", "message": "Chain broken"}]
        html = render_failure(failed, "KN-HC-0404")
        assert "KN-HC-0404" in html
        assert "hash_chain_integrity" in html
        assert "Chain broken" in html

    def test_contains_override_form(self):
        failed = [{"probe": "test", "message": "fail"}]
        html = render_failure(failed, "KN-XX-0101")
        assert 'action="/override"' in html
        assert 'name="pin"' in html
        assert "Manager Override" in html

    def test_contains_call_support(self):
        failed = [{"probe": "test", "message": "fail"}]
        html = render_failure(failed, "KN-XX-0101")
        assert "Call Support" in html

    def test_pin_error_shown(self):
        failed = [{"probe": "test", "message": "fail"}]
        html = render_failure(failed, "KN-XX-0101", pin_error="Invalid manager PIN")
        assert "Invalid manager PIN" in html
        assert "pin-error" in html

    def test_cannot_accept_orders_message(self):
        failed = [{"probe": "test", "message": "fail"}]
        html = render_failure(failed, "KN-XX-0101")
        assert "cannot accept orders" in html


class TestRenderWarningIndicator:

    def test_empty_warnings_returns_empty(self):
        assert render_warning_indicator([]) == ""

    def test_shows_warning_count(self):
        warnings = [{"probe": "p1", "message": "m1"}, {"probe": "p2", "message": "m2"}]
        html = render_warning_indicator(warnings)
        assert "2 boot warning(s)" in html
        assert "warning-badge" in html


# ═════════════════════════════════════════════════════════════
# MANAGER PIN VALIDATION
# ═════════════════════════════════════════════════════════════

def _create_ledger_with_employees(db_path: str, employees: list[dict]) -> None:
    """Create an event ledger DB with EMPLOYEE_CREATED events."""
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
    for i, emp in enumerate(employees):
        conn.execute(
            """INSERT INTO events (event_id, timestamp, terminal_id,
                                   event_type, payload, checksum)
               VALUES (?, '2026-01-01T00:00:00', 'terminal-01',
                       'EMPLOYEE_CREATED', ?, 'hash')""",
            (f"emp-evt-{i}", json.dumps(emp)),
        )
    conn.commit()
    conn.close()


class TestValidateManagerPin:

    def test_valid_manager_pin(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_employees(db, [
            {"employee_id": "alex", "first_name": "Alex", "last_name": "M",
             "display_name": "Alex M.", "role_id": "manager", "pin": "1234",
             "hourly_rate": 0.0, "active": True},
            {"employee_id": "jordan", "first_name": "Jordan", "last_name": "K",
             "display_name": "Jordan K.", "role_id": "server", "pin": "5678",
             "hourly_rate": 15.0, "active": True},
        ])
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = validate_manager_pin("1234")
        assert result == "alex"

    def test_server_pin_rejected(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_employees(db, [
            {"employee_id": "jordan", "role_id": "server", "pin": "5678", "active": True},
        ])
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = validate_manager_pin("5678")
        assert result is None

    def test_wrong_pin_rejected(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_employees(db, [
            {"employee_id": "alex", "role_id": "manager", "pin": "1234", "active": True},
        ])
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = validate_manager_pin("9999")
        assert result is None

    def test_inactive_manager_rejected(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_employees(db, [
            {"employee_id": "alex", "role_id": "manager", "pin": "1234", "active": False},
        ])
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = validate_manager_pin("1234")
        assert result is None

    def test_no_ledger_returns_none(self, tmp_path):
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": str(tmp_path / "nope.db")}):
            result = validate_manager_pin("1234")
        assert result is None


# ═════════════════════════════════════════════════════════════
# BOOT DISPLAY STATE
# ═════════════════════════════════════════════════════════════

class TestBootDisplayState:

    def test_initial_state(self):
        state = BootDisplayState()
        assert "initializing" in state.current_screen
        assert not state.override_completed

    def test_set_progress(self):
        state = BootDisplayState()
        state.set_progress(3, 10, "hash_chain")
        assert "30%" in state.current_screen
        assert "hash_chain" in state.current_screen

    def test_set_success(self):
        state = BootDisplayState()
        state.set_success()
        assert "&#10003;" in state.current_screen or "All systems" in state.current_screen

    def test_set_failure(self):
        state = BootDisplayState()
        state.set_failure(
            [{"probe": "hash_chain", "message": "broken"}],
            "KN-HC-0404",
        )
        assert "KN-HC-0404" in state.current_screen
        assert "override" in state.current_screen.lower()

    def test_handle_override_success(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_employees(db, [
            {"employee_id": "alex", "role_id": "manager", "pin": "1234", "active": True},
        ])
        state = BootDisplayState()
        state.set_failure([{"probe": "test", "message": "fail"}], "KN-XX-0101")
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = state.handle_override("1234")
        assert result is True
        assert state.override_completed is True
        assert state.override_employee == "alex"

    def test_handle_override_bad_pin(self, tmp_path):
        db = str(tmp_path / "ledger.db")
        _create_ledger_with_employees(db, [
            {"employee_id": "alex", "role_id": "manager", "pin": "1234", "active": True},
        ])
        state = BootDisplayState()
        state.set_failure([{"probe": "test", "message": "fail"}], "KN-XX-0101")
        with patch.dict(os.environ, {"KINDPOS_DB_PATH": db}):
            result = state.handle_override("9999")
        assert result is False
        assert state.override_completed is False
        assert "Invalid" in state.pin_error


# ═════════════════════════════════════════════════════════════
# BOOT DISPLAY HTTP SERVER
# ═════════════════════════════════════════════════════════════

class TestBootDisplayServer:

    def test_server_starts_and_serves(self):
        display = BootDisplay(port=0)  # port 0 = OS picks a free port
        display.start()
        try:
            port = display._server.server_address[1]
            resp = urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
            html = resp.read().decode()
            assert "KINDnostic" in html
        finally:
            display.stop()

    def test_status_endpoint(self):
        display = BootDisplay(port=0)
        display.start()
        display.state.outcome = "READY"
        try:
            port = display._server.server_address[1]
            resp = urllib.request.urlopen(f"http://localhost:{port}/status", timeout=2)
            data = json.loads(resp.read().decode())
            assert data["outcome"] == "READY"
            assert data["override"] is False
        finally:
            display.stop()

    def test_context_manager(self):
        with BootDisplay(port=0) as display:
            port = display._server.server_address[1]
            resp = urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
            assert resp.status == 200

    def test_warnings_endpoint(self):
        display = BootDisplay(port=0)
        display.start()
        display.state.warnings = [
            {"probe": "ssd_health", "message": "Low disk"},
        ]
        try:
            port = display._server.server_address[1]
            resp = urllib.request.urlopen(f"http://localhost:{port}/warnings", timeout=2)
            html = resp.read().decode()
            assert "ssd_health" in html
        finally:
            display.stop()
