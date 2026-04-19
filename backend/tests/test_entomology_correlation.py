"""
Entomology System — Reverse Correlation Tests (RC-01 .. RC-05)

Tests for retroactive correlation linking, time windows,
and update_correlation_id.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
)


# ─── RC-01: reverse_correlate links matching events ────

@pytest.mark.asyncio
async def test_rc01_reverse_correlate_links(collector):
    # Record an event with device IP in context but no correlation
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Terminal unreachable",
        context={"device_ip": "10.0.0.100"},
    )
    # Reverse correlate — should find the event by device identifier
    updated = await collector.reverse_correlate(
        device_identifier="10.0.0.100",
        correlation_id="order-abc",
    )
    assert updated == 1

    events = await collector.get_events(correlation_id="order-abc")
    assert len(events) == 1
    assert events[0].event_code == "DEV-001"


# ─── RC-02: reverse_correlate skips already-correlated ──

@pytest.mark.asyncio
async def test_rc02_skip_already_correlated(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Already linked",
        context={"device_ip": "10.0.0.100"},
        correlation_id="existing-corr",
    )
    updated = await collector.reverse_correlate(
        device_identifier="10.0.0.100",
        correlation_id="new-corr",
    )
    assert updated == 0


# ─── RC-03: reverse_correlate respects time window ─────

@pytest.mark.asyncio
async def test_rc03_time_window(collector):
    # Record an event and backdate it beyond the window
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Old event",
        context={"device_ip": "10.0.0.100"},
    )
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await collector._db.execute(
        "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
    )
    await collector._db.commit()

    # Default window is 5 minutes — should not find the old event
    updated = await collector.reverse_correlate(
        device_identifier="10.0.0.100",
        correlation_id="order-xyz",
        minutes_back=5,
    )
    assert updated == 0


# ─── RC-04: reverse_correlate with custom window ───────

@pytest.mark.asyncio
async def test_rc04_custom_window(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Recent event",
        context={"device_ip": "10.0.0.100"},
    )
    # Backdate 3 minutes
    ts = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    await collector._db.execute(
        "UPDATE diagnostic_events SET timestamp = ?", (ts,)
    )
    await collector._db.commit()

    # 2 minute window — should miss
    updated = await collector.reverse_correlate(
        device_identifier="10.0.0.100",
        correlation_id="order-xyz",
        minutes_back=2,
    )
    assert updated == 0

    # 5 minute window — should find
    updated = await collector.reverse_correlate(
        device_identifier="10.0.0.100",
        correlation_id="order-xyz",
        minutes_back=5,
    )
    assert updated == 1


# ─── RC-05: update_correlation_id on specific event ────

@pytest.mark.asyncio
async def test_rc05_update_correlation_id(collector):
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="To be linked",
        context={},
    )
    assert event.correlation_id is None

    success = await collector.update_correlation_id(
        event.diagnostic_id, "new-corr-id"
    )
    assert success is True

    events = await collector.get_events(correlation_id="new-corr-id")
    assert len(events) == 1
    assert events[0].diagnostic_id == event.diagnostic_id

    # Second update should fail (already has correlation)
    success2 = await collector.update_correlation_id(
        event.diagnostic_id, "another-corr"
    )
    assert success2 is False
