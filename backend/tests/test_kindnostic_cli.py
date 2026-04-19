"""
KINDnostic CLI + Output Formatting Tests
==========================================
Tests for --verbose, --json, --probe flags and output formatting functions.
"""

import json
from io import StringIO
from unittest.mock import patch

import pytest

from kindnostic.runner import (
    _format_json,
    _format_result_line,
    _format_summary,
    _format_verbose,
    run_all,
    run_single_probe,
)
from kindnostic.types import Category, ProbeResult, Status


# ═════════════════════════════════════════════════════════════
# OUTPUT FORMATTING (no color)
# ═════════════════════════════════════════════════════════════

def _make_result(name="dummy", cat=Category.LOW, status=Status.PASS, msg=None, meta=None):
    return ProbeResult(probe_name=name, category=cat, status=status, message=msg, metadata=meta)


class TestFormatResultLine:

    def test_pass_line_contains_status_and_name(self):
        r = _make_result()
        line = _format_result_line(r, 42, color=False)
        assert "PASS" in line
        assert "dummy" in line
        assert "42ms" in line

    def test_fail_line_contains_message(self):
        r = _make_result(status=Status.FAIL, msg="bad thing happened")
        line = _format_result_line(r, 100, color=False)
        assert "FAIL" in line
        assert "bad thing happened" in line

    def test_category_shown(self):
        r = _make_result(cat=Category.CRITICAL)
        line = _format_result_line(r, 10, color=False)
        assert "CRITICAL" in line


class TestFormatVerbose:

    def test_includes_metadata(self):
        r = _make_result(meta={"events_checked": 500, "chain_valid": True})
        output = _format_verbose(r, 50, color=False)
        assert "events_checked" in output
        assert "500" in output

    def test_no_metadata_still_works(self):
        r = _make_result()
        output = _format_verbose(r, 50, color=False)
        assert "dummy" in output


class TestFormatSummary:

    def test_ready_summary(self):
        results = [(_make_result(), 10), (_make_result(), 20)]
        summary = _format_summary(results, 30, "READY", color=False)
        assert "2 passed" in summary
        assert "READY" in summary
        assert "30ms" in summary

    def test_blocked_summary(self):
        results = [
            (_make_result(status=Status.FAIL), 50),
            (_make_result(status=Status.WARN), 30),
        ]
        summary = _format_summary(results, 80, "BLOCKED", color=False)
        assert "1 failed" in summary
        assert "1 warned" in summary
        assert "BLOCKED" in summary


class TestFormatJson:

    def test_valid_json(self):
        results = [(_make_result(), 42)]
        output = _format_json(results, "boot-123", 42, "READY")
        data = json.loads(output)
        assert data["boot_id"] == "boot-123"
        assert data["outcome"] == "READY"
        assert len(data["probes"]) == 1
        assert data["probes"][0]["probe_name"] == "dummy"
        assert data["summary"]["total"] == 1
        assert data["summary"]["passed"] == 1

    def test_includes_failures(self):
        results = [
            (_make_result(status=Status.FAIL, msg="broken"), 100),
        ]
        output = _format_json(results, "boot-fail", 100, "BLOCKED")
        data = json.loads(output)
        assert data["summary"]["failed"] == 1
        assert data["probes"][0]["message"] == "broken"


# ═════════════════════════════════════════════════════════════
# COLOR OUTPUT
# ═════════════════════════════════════════════════════════════

class TestColorOutput:

    def test_pass_gets_green(self):
        r = _make_result()
        line = _format_result_line(r, 10, color=True)
        assert "\033[32m" in line  # green

    def test_warn_gets_yellow(self):
        r = _make_result(status=Status.WARN)
        line = _format_result_line(r, 10, color=True)
        assert "\033[33m" in line  # yellow

    def test_fail_gets_red(self):
        r = _make_result(status=Status.FAIL)
        line = _format_result_line(r, 10, color=True)
        assert "\033[31m" in line  # red


# ═════════════════════════════════════════════════════════════
# --json FLAG (end-to-end)
# ═════════════════════════════════════════════════════════════

class TestJsonFlag:

    def test_run_all_json_output(self, tmp_path, capsys):
        db = str(tmp_path / "diag.db")
        exit_code = run_all(db_path=db, json_output=True)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["outcome"] == "READY"
        assert exit_code == 0


# ═════════════════════════════════════════════════════════════
# --probe FLAG
# ═════════════════════════════════════════════════════════════

class TestProbeFlag:

    def test_run_single_dummy(self, tmp_path, capsys):
        exit_code = run_single_probe("dummy", json_output=True)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["probes"]) == 1
        assert data["probes"][0]["probe_name"] == "dummy"
        assert exit_code == 0

    def test_run_single_unknown_returns_2(self, capsys):
        exit_code = run_single_probe("nonexistent_probe")
        captured = capsys.readouterr()
        assert "Unknown probe" in captured.err
        assert exit_code == 2

    def test_run_single_shows_available(self, capsys):
        run_single_probe("nope")
        captured = capsys.readouterr()
        assert "dummy" in captured.err

    def test_run_single_with_verbose(self, capsys):
        exit_code = run_single_probe("dummy", verbose=True)
        captured = capsys.readouterr()
        assert "dummy" in captured.out
        assert exit_code == 0
