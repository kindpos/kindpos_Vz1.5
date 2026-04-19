"""
KINDnostic Types Tests
======================
Validates Status enum, Category enum (with ordering), and ProbeResult dataclass.
"""

import dataclasses

from kindnostic.types import Category, ProbeResult, Status


# ─── Status enum ─────────────────────────────────────────────

def test_status_has_three_members():
    assert set(Status) == {Status.PASS, Status.WARN, Status.FAIL}


def test_status_values():
    assert Status.PASS.value == "PASS"
    assert Status.WARN.value == "WARN"
    assert Status.FAIL.value == "FAIL"


def test_status_is_str():
    assert isinstance(Status.PASS, str)
    assert Status.PASS == "PASS"


# ─── Category enum ───────────────────────────────────────────

def test_category_has_three_members():
    assert set(Category) == {Category.CRITICAL, Category.HIGH, Category.LOW}


def test_category_values():
    assert Category.CRITICAL.value == "CRITICAL"
    assert Category.HIGH.value == "HIGH"
    assert Category.LOW.value == "LOW"


def test_category_is_str():
    assert isinstance(Category.CRITICAL, str)
    assert Category.CRITICAL == "CRITICAL"


def test_category_ordering_lt():
    assert Category.CRITICAL < Category.HIGH
    assert Category.HIGH < Category.LOW
    assert Category.CRITICAL < Category.LOW


def test_category_ordering_gt():
    assert Category.LOW > Category.HIGH
    assert Category.HIGH > Category.CRITICAL


def test_category_ordering_le_ge():
    assert Category.CRITICAL <= Category.CRITICAL
    assert Category.CRITICAL <= Category.HIGH
    assert Category.LOW >= Category.LOW
    assert Category.LOW >= Category.HIGH


def test_category_sorted():
    """sorted() should put CRITICAL first, then HIGH, then LOW."""
    shuffled = [Category.LOW, Category.CRITICAL, Category.HIGH]
    assert sorted(shuffled) == [Category.CRITICAL, Category.HIGH, Category.LOW]


# ─── ProbeResult ─────────────────────────────────────────────

def test_probe_result_fields():
    r = ProbeResult(
        probe_name="test",
        category=Category.LOW,
        status=Status.PASS,
        message="all good",
        metadata={"key": "value"},
    )
    assert r.probe_name == "test"
    assert r.category == Category.LOW
    assert r.status == Status.PASS
    assert r.message == "all good"
    assert r.metadata == {"key": "value"}


def test_probe_result_defaults():
    r = ProbeResult(probe_name="test", category=Category.LOW, status=Status.PASS)
    assert r.message is None
    assert r.metadata is None


def test_probe_result_frozen():
    r = ProbeResult(probe_name="test", category=Category.LOW, status=Status.PASS)
    try:
        r.status = Status.FAIL  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except dataclasses.FrozenInstanceError:
        pass
