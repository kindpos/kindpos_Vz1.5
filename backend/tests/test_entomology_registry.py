"""
Entomology System — Event Code Registry Tests (R-01 .. R-09)

Tests for EVENT_CODE_REGISTRY completeness, format, and consistency.
"""

import pytest

from app.models.diagnostic_event import (
    EVENT_CODE_REGISTRY,
    EVENT_CODE_PATTERN,
    DiagnosticCategory,
)


# ─── R-01: Registry has 36 codes ───────────────────────

def test_r01_registry_count():
    assert len(EVENT_CODE_REGISTRY) == 36


# ─── R-02: No duplicate codes ──────────────────────────

def test_r02_no_duplicates():
    codes = list(EVENT_CODE_REGISTRY.keys())
    assert len(codes) == len(set(codes))


# ─── R-03: All codes match PREFIX-CODE pattern ─────────

def test_r03_all_codes_match_pattern():
    for code in EVENT_CODE_REGISTRY:
        assert EVENT_CODE_PATTERN.match(code), f"Code '{code}' doesn't match pattern"


# ─── R-04: All descriptions are non-empty strings ──────

def test_r04_descriptions_non_empty():
    for code, desc in EVENT_CODE_REGISTRY.items():
        assert isinstance(desc, str), f"Description for {code} is not a string"
        assert len(desc) > 0, f"Description for {code} is empty"


# ─── R-05: DEV- codes present (6 codes) ────────────────

def test_r05_device_codes():
    dev_codes = [c for c in EVENT_CODE_REGISTRY if c.startswith("DEV-")]
    assert len(dev_codes) == 6


# ─── R-06: NET- codes present (8 codes) ────────────────

def test_r06_network_codes():
    net_codes = [c for c in EVENT_CODE_REGISTRY if c.startswith("NET-")]
    assert len(net_codes) == 8


# ─── R-07: SYS- codes present (8 codes) ────────────────

def test_r07_system_codes():
    sys_codes = [c for c in EVENT_CODE_REGISTRY if c.startswith("SYS-")]
    assert len(sys_codes) == 8


# ─── R-08: PER- codes present (7 codes) ────────────────

def test_r08_peripheral_codes():
    per_codes = [c for c in EVENT_CODE_REGISTRY if c.startswith("PER-")]
    assert len(per_codes) == 7


# ─── R-09: REC- codes present (7 codes) ────────────────

def test_r09_recovery_codes():
    rec_codes = [c for c in EVENT_CODE_REGISTRY if c.startswith("REC-")]
    assert len(rec_codes) == 7
