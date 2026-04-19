"""
Entomology System — Data Model Tests (M-01 .. M-14)

Tests for DiagnosticCategory, DiagnosticSeverity, DiagnosticEvent,
compute_diagnostic_hash, and validation logic.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
    DiagnosticEvent,
    compute_diagnostic_hash,
    GENESIS_HASH,
    DEFAULT_RETENTION_DAYS,
    EVENT_CODE_PATTERN,
)


# ─── M-01: DiagnosticCategory has all 5 values ─────────

def test_m01_category_enum_values():
    expected = {"DEVICE", "NETWORK", "SYSTEM", "PERIPHERAL", "RECOVERY"}
    assert set(c.value for c in DiagnosticCategory) == expected


# ─── M-02: DiagnosticSeverity has all 4 values ─────────

def test_m02_severity_enum_values():
    expected = {"INFO", "WARNING", "ERROR", "CRITICAL"}
    assert set(s.value for s in DiagnosticSeverity) == expected


# ─── M-03: Severity ordering INFO < WARNING < ERROR < CRITICAL ───

def test_m03_severity_ordering():
    assert DiagnosticSeverity.INFO < DiagnosticSeverity.WARNING
    assert DiagnosticSeverity.WARNING < DiagnosticSeverity.ERROR
    assert DiagnosticSeverity.ERROR < DiagnosticSeverity.CRITICAL


# ─── M-04: Severity comparison operators ────────────────

def test_m04_severity_le_ge():
    assert DiagnosticSeverity.INFO <= DiagnosticSeverity.INFO
    assert DiagnosticSeverity.INFO <= DiagnosticSeverity.WARNING
    assert DiagnosticSeverity.CRITICAL >= DiagnosticSeverity.ERROR
    assert DiagnosticSeverity.ERROR >= DiagnosticSeverity.ERROR


# ─── M-05: Severity gt/lt with non-severity returns NotImplemented ──

def test_m05_severity_comparison_with_non_severity():
    assert DiagnosticSeverity.INFO.__lt__("not a severity") is NotImplemented
    assert DiagnosticSeverity.INFO.__le__("not a severity") is NotImplemented
    assert DiagnosticSeverity.INFO.__gt__("not a severity") is NotImplemented
    assert DiagnosticSeverity.INFO.__ge__("not a severity") is NotImplemented


# ─── M-06: DiagnosticEvent creates valid instance ───────

def test_m06_diagnostic_event_valid():
    now = datetime.now(timezone.utc)
    event = DiagnosticEvent(
        diagnostic_id="test-id-001",
        terminal_id="terminal-01",
        timestamp=now,
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Test message",
        context={"device_ip": "10.0.0.1"},
        prev_hash=GENESIS_HASH,
        hash="abc123",
    )
    assert event.diagnostic_id == "test-id-001"
    assert event.category == DiagnosticCategory.DEVICE
    assert event.severity == DiagnosticSeverity.ERROR
    assert event.context == {"device_ip": "10.0.0.1"}


# ─── M-07: DiagnosticEvent default fields ──────────────

def test_m07_diagnostic_event_defaults():
    event = DiagnosticEvent(
        terminal_id="terminal-01",
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Heartbeat",
        context={},
        prev_hash=GENESIS_HASH,
        hash="abc",
    )
    # diagnostic_id should be auto-generated UUID
    assert len(event.diagnostic_id) == 36  # UUID format
    assert event.correlation_id is None
    assert event.timestamp is not None


# ─── M-08: Invalid category rejected ───────────────────

def test_m08_invalid_category():
    with pytest.raises(ValidationError):
        DiagnosticEvent(
            terminal_id="terminal-01",
            category="INVALID_CAT",
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="DEV-001",
            message="Test",
            context={},
            prev_hash=GENESIS_HASH,
            hash="abc",
        )


# ─── M-09: Invalid severity rejected ───────────────────

def test_m09_invalid_severity():
    with pytest.raises(ValidationError):
        DiagnosticEvent(
            terminal_id="terminal-01",
            category=DiagnosticCategory.DEVICE,
            severity="MEGA_BAD",
            source="Test",
            event_code="DEV-001",
            message="Test",
            context={},
            prev_hash=GENESIS_HASH,
            hash="abc",
        )


# ─── M-10: context must be a dict ──────────────────────

def test_m10_context_must_be_dict():
    with pytest.raises(ValidationError):
        DiagnosticEvent(
            terminal_id="terminal-01",
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="DEV-001",
            message="Test",
            context="not a dict",
            prev_hash=GENESIS_HASH,
            hash="abc",
        )


# ─── M-11: event_code format validation ────────────────

def test_m11_event_code_format_valid():
    assert EVENT_CODE_PATTERN.match("DEV-001")
    assert EVENT_CODE_PATTERN.match("SYS-HEARTBEAT")
    assert EVENT_CODE_PATTERN.match("NET-007")


def test_m11_event_code_format_invalid():
    with pytest.raises(ValidationError):
        DiagnosticEvent(
            terminal_id="terminal-01",
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="bad-format",
            message="Test",
            context={},
            prev_hash=GENESIS_HASH,
            hash="abc",
        )


# ─── M-12: compute_diagnostic_hash deterministic ───────

def test_m12_hash_deterministic():
    args = dict(
        prev_hash=GENESIS_HASH,
        diagnostic_id="id-001",
        timestamp="2025-01-01T00:00:00+00:00",
        category="DEVICE",
        severity="ERROR",
        source="TestAdapter",
        event_code="DEV-001",
        message="Terminal unreachable",
        context={"ip": "10.0.0.1"},
    )
    h1 = compute_diagnostic_hash(**args)
    h2 = compute_diagnostic_hash(**args)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


# ─── M-13: Different inputs produce different hashes ────

def test_m13_hash_different_inputs():
    base = dict(
        prev_hash=GENESIS_HASH,
        diagnostic_id="id-001",
        timestamp="2025-01-01T00:00:00+00:00",
        category="DEVICE",
        severity="ERROR",
        source="TestAdapter",
        event_code="DEV-001",
        message="Terminal unreachable",
        context={"ip": "10.0.0.1"},
    )
    h1 = compute_diagnostic_hash(**base)
    h2 = compute_diagnostic_hash(**{**base, "message": "Different message"})
    assert h1 != h2


# ─── M-14: GENESIS_HASH and DEFAULT_RETENTION_DAYS ─────

def test_m14_constants():
    assert GENESIS_HASH == "KIND_DIAGNOSTIC_GENESIS"
    assert DEFAULT_RETENTION_DAYS == 90
