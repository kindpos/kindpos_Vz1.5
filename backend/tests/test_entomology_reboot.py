"""
Entomology System — Scheduled Reboot Tests (B-01 .. B-05)

Tests for SYS-007 reboot marker events, context structure,
and gap detection between pre-shutdown and post-boot.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
)


# ─── B-01: SYS-007 event records correctly ─────────────

@pytest.mark.asyncio
async def test_b01_sys007_records(collector):
    event = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="CronScheduler",
        event_code="SYS-007",
        message="Scheduled reboot — pre-shutdown marker",
        context={
            "scheduled_time": "04:00",
            "uptime_hours": 23.5,
            "pending_jobs": 0,
        },
    )
    assert event.event_code == "SYS-007"
    assert event.category == DiagnosticCategory.SYSTEM


# ─── B-02: SYS-007 context has expected fields ─────────

@pytest.mark.asyncio
async def test_b02_sys007_context_fields(collector):
    event = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="CronScheduler",
        event_code="SYS-007",
        message="Scheduled reboot",
        context={
            "scheduled_time": "04:00",
            "uptime_hours": 23.5,
            "pending_jobs": 0,
        },
    )
    assert "scheduled_time" in event.context
    assert "uptime_hours" in event.context
    assert "pending_jobs" in event.context


# ─── B-03: Gap detection — SYS-007 followed by heartbeat ──

@pytest.mark.asyncio
async def test_b03_gap_detection(collector):
    # Pre-shutdown marker
    shutdown = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="CronScheduler",
        event_code="SYS-007",
        message="Scheduled reboot",
        context={"scheduled_time": "04:00"},
    )

    # Simulate post-boot heartbeat (would happen after reboot)
    heartbeat = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="DiagnosticCollector",
        event_code="SYS-HEARTBEAT",
        message="Ambient health snapshot",
        context={"system": {"uptime_hours": 0.1}},
    )

    events = await collector.get_events(event_code="SYS-007")
    assert len(events) == 1

    all_events = await collector.get_all_events_ordered()
    assert len(all_events) == 2
    assert all_events[0].event_code == "SYS-007"
    assert all_events[1].event_code == "SYS-HEARTBEAT"


# ─── B-04: Multiple reboots tracked ────────────────────

@pytest.mark.asyncio
async def test_b04_multiple_reboots(collector):
    for day in range(3):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="CronScheduler",
            event_code="SYS-007",
            message=f"Scheduled reboot day {day}",
            context={"scheduled_time": "04:00", "day": day},
        )
    events = await collector.get_events(event_code="SYS-007")
    assert len(events) == 3


# ─── B-05: SYS-007 with non-zero pending jobs ──────────

@pytest.mark.asyncio
async def test_b05_reboot_with_pending_jobs(collector):
    event = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.WARNING,
        source="CronScheduler",
        event_code="SYS-007",
        message="Scheduled reboot with pending work",
        context={
            "scheduled_time": "04:00",
            "uptime_hours": 23.5,
            "pending_jobs": 3,
        },
    )
    assert event.severity == DiagnosticSeverity.WARNING
    assert event.context["pending_jobs"] == 3
