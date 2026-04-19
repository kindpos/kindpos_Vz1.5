"""
Entomology System — Collector Tests (C-01 .. C-31)

Tests for DiagnosticCollector: recording, hash chaining,
queries, adaptive heartbeat, and singleton behavior.
"""

import asyncio
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
    DiagnosticEvent,
    GENESIS_HASH,
    compute_diagnostic_hash,
)
from app.services.diagnostic_collector import (
    DiagnosticCollector,
    ACTIVE_HEARTBEAT_INTERVAL_S,
    OFF_HOURS_HEARTBEAT_INTERVAL_S,
    COOLDOWN_MINUTES,
)


# ─── C-01: record() returns a DiagnosticEvent ──────────

@pytest.mark.asyncio
async def test_c01_record_returns_event(collector):
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Terminal unreachable",
        context={"device_ip": "10.0.0.1"},
    )
    assert isinstance(event, DiagnosticEvent)
    assert event.category == DiagnosticCategory.DEVICE
    assert event.severity == DiagnosticSeverity.ERROR
    assert event.event_code == "DEV-001"


# ─── C-02: record() auto-generates diagnostic_id ───────

@pytest.mark.asyncio
async def test_c02_record_auto_id(collector):
    event = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Heartbeat",
        context={},
    )
    assert len(event.diagnostic_id) == 36


# ─── C-03: record() auto-generates timestamp ───────────

@pytest.mark.asyncio
async def test_c03_record_auto_timestamp(collector):
    before = datetime.now(timezone.utc)
    event = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Heartbeat",
        context={},
    )
    after = datetime.now(timezone.utc)
    assert before <= event.timestamp <= after


# ─── C-04: First event uses GENESIS_HASH as prev_hash ──

@pytest.mark.asyncio
async def test_c04_first_event_genesis_hash(collector):
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.WARNING,
        source="Test",
        event_code="DEV-006",
        message="Status change",
        context={},
    )
    assert event.prev_hash == GENESIS_HASH


# ─── C-05: Hash chain links events ─────────────────────

@pytest.mark.asyncio
async def test_c05_hash_chain(collector):
    e1 = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="First",
        context={},
    )
    e2 = await collector.record(
        category=DiagnosticCategory.NETWORK,
        severity=DiagnosticSeverity.WARNING,
        source="Test",
        event_code="NET-001",
        message="Second",
        context={},
    )
    assert e2.prev_hash == e1.hash


# ─── C-06: Hash chain is verifiable ────────────────────

@pytest.mark.asyncio
async def test_c06_hash_chain_verifiable(collector):
    events = []
    for i in range(5):
        e = await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message=f"Event {i}",
            context={"seq": i},
        )
        events.append(e)

    # Verify chain
    for i in range(1, len(events)):
        assert events[i].prev_hash == events[i - 1].hash

    # Verify first links to genesis
    assert events[0].prev_hash == GENESIS_HASH


# ─── C-07: Hash is computed correctly ──────────────────

@pytest.mark.asyncio
async def test_c07_hash_computation(collector):
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="TestAdapter",
        event_code="DEV-001",
        message="Test",
        context={"key": "value"},
    )
    expected = compute_diagnostic_hash(
        prev_hash=event.prev_hash,
        diagnostic_id=event.diagnostic_id,
        timestamp=event.timestamp.isoformat(),
        category=event.category.value,
        severity=event.severity.value,
        source=event.source,
        event_code=event.event_code,
        message=event.message,
        context=event.context,
    )
    assert event.hash == expected


# ─── C-08: record() persists to SQLite ─────────────────

@pytest.mark.asyncio
async def test_c08_record_persists(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Persisted",
        context={},
    )
    count = await collector.count_events()
    assert count == 1


# ─── C-09: record() with correlation_id ────────────────

@pytest.mark.asyncio
async def test_c09_record_with_correlation(collector):
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Correlated",
        context={},
        correlation_id="order-12345",
    )
    assert event.correlation_id == "order-12345"


# ─── C-10: record() without correlation_id is None ─────

@pytest.mark.asyncio
async def test_c10_record_no_correlation(collector):
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="DEV-006",
        message="No correlation",
        context={},
    )
    assert event.correlation_id is None


# ─── C-11: record() stores terminal_id ─────────────────

@pytest.mark.asyncio
async def test_c11_terminal_id(collector):
    event = await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Test",
        context={},
    )
    assert event.terminal_id == "terminal-test-01"


# ─── C-12: Multiple records increment count ────────────

@pytest.mark.asyncio
async def test_c12_multiple_records(collector):
    for i in range(10):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message=f"Event {i}",
            context={},
        )
    assert await collector.count_events() == 10


# ─── C-13: get_events returns all events ───────────────

@pytest.mark.asyncio
async def test_c13_get_events_all(collector):
    for i in range(3):
        await collector.record(
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.WARNING,
            source="Test",
            event_code="DEV-006",
            message=f"Event {i}",
            context={},
        )
    events = await collector.get_events()
    assert len(events) == 3


# ─── C-14: get_events filters by category ──────────────

@pytest.mark.asyncio
async def test_c14_get_events_by_category(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Device",
        context={},
    )
    await collector.record(
        category=DiagnosticCategory.NETWORK,
        severity=DiagnosticSeverity.WARNING,
        source="Test",
        event_code="NET-001",
        message="Network",
        context={},
    )
    events = await collector.get_events(category=DiagnosticCategory.DEVICE)
    assert len(events) == 1
    assert events[0].category == DiagnosticCategory.DEVICE


# ─── C-15: get_events filters by severity ──────────────

@pytest.mark.asyncio
async def test_c15_get_events_by_severity(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Error",
        context={},
    )
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="DEV-006",
        message="Info",
        context={},
    )
    events = await collector.get_events(severity=DiagnosticSeverity.ERROR)
    assert len(events) == 1
    assert events[0].severity == DiagnosticSeverity.ERROR


# ─── C-16: get_events filters by event_code ────────────

@pytest.mark.asyncio
async def test_c16_get_events_by_event_code(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="One",
        context={},
    )
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.WARNING,
        source="Test",
        event_code="DEV-002",
        message="Two",
        context={},
    )
    events = await collector.get_events(event_code="DEV-001")
    assert len(events) == 1
    assert events[0].event_code == "DEV-001"


# ─── C-17: get_events filters by time range ────────────

@pytest.mark.asyncio
async def test_c17_get_events_by_time_range(collector):
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Now",
        context={},
    )
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=1)
    past = now - timedelta(hours=1)

    events = await collector.get_events(since=past, until=future)
    assert len(events) == 1

    events = await collector.get_events(since=future)
    assert len(events) == 0


# ─── C-18: get_events filters by correlation_id ────────

@pytest.mark.asyncio
async def test_c18_get_events_by_correlation(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Correlated",
        context={},
        correlation_id="corr-001",
    )
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="DEV-006",
        message="Uncorrelated",
        context={},
    )
    events = await collector.get_events(correlation_id="corr-001")
    assert len(events) == 1
    assert events[0].correlation_id == "corr-001"


# ─── C-19: get_events respects limit ───────────────────

@pytest.mark.asyncio
async def test_c19_get_events_limit(collector):
    for i in range(10):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message=f"Event {i}",
            context={},
        )
    events = await collector.get_events(limit=3)
    assert len(events) == 3


# ─── C-20: get_events_by_severity_min ──────────────────

@pytest.mark.asyncio
async def test_c20_get_events_by_severity_min(collector):
    for sev in DiagnosticSeverity:
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=sev,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message=f"Sev: {sev.value}",
            context={},
        )
    events = await collector.get_events_by_severity_min(DiagnosticSeverity.ERROR)
    assert len(events) == 2  # ERROR + CRITICAL
    for e in events:
        assert e.severity >= DiagnosticSeverity.ERROR


# ─── C-21: get_events_by_severity_min with time filter ─

@pytest.mark.asyncio
async def test_c21_severity_min_with_time(collector):
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.CRITICAL,
        source="Test",
        event_code="SYS-006",
        message="Critical",
        context={},
    )
    now = datetime.now(timezone.utc)
    events = await collector.get_events_by_severity_min(
        DiagnosticSeverity.CRITICAL,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )
    assert len(events) == 1


# ─── C-22: get_all_events_ordered ──────────────────────

@pytest.mark.asyncio
async def test_c22_get_all_events_ordered(collector):
    for i in range(5):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message=f"Event {i}",
            context={"seq": i},
        )
    events = await collector.get_all_events_ordered()
    assert len(events) == 5
    # Verify order
    for i in range(1, len(events)):
        assert events[i].timestamp >= events[i - 1].timestamp


# ─── C-23: count_events ────────────────────────────────

@pytest.mark.asyncio
async def test_c23_count_events_empty(collector):
    assert await collector.count_events() == 0


# ─── C-24: Adaptive heartbeat — active interval ────────

def test_c24_active_heartbeat_interval():
    assert ACTIVE_HEARTBEAT_INTERVAL_S == 60


# ─── C-25: Adaptive heartbeat — off-hours interval ─────

def test_c25_off_hours_heartbeat_interval():
    assert OFF_HOURS_HEARTBEAT_INTERVAL_S == 900


# ─── C-26: Cooldown is 30 minutes ──────────────────────

def test_c26_cooldown_minutes():
    assert COOLDOWN_MINUTES == 30


# ─── C-27: notify_order_created activates service ──────

@pytest.mark.asyncio
async def test_c27_notify_order_activates(collector):
    assert collector._service_active is False
    await collector.notify_order_created()
    assert collector._service_active is True


# ─── C-28: notify_order_created cancels existing cooldown ──

@pytest.mark.asyncio
async def test_c28_notify_cancels_cooldown(collector):
    await collector.notify_order_created()
    first_task = collector._cooldown_task

    await collector.notify_order_created()
    second_task = collector._cooldown_task

    assert first_task.cancelled() or first_task.done()
    assert second_task is not first_task


# ─── C-29: start_heartbeat_loop returns task ───────────

@pytest.mark.asyncio
async def test_c29_heartbeat_loop_returns_task(collector):
    task = collector.start_heartbeat_loop()
    assert isinstance(task, asyncio.Task)
    assert not task.done()
    # Clean up
    collector._shutdown_event.set()
    await asyncio.sleep(0.1)


# ─── C-30: close() cancels heartbeat task ──────────────

@pytest.mark.asyncio
async def test_c30_close_cancels_heartbeat(collector):
    task = collector.start_heartbeat_loop()
    await collector.close()
    assert task.done()


# ─── C-31: Collector context manager ───────────────────

@pytest.mark.asyncio
async def test_c31_context_manager(tmp_path):
    db_path = str(tmp_path / "test_cm.db")
    async with DiagnosticCollector(db_path, "terminal-cm") as coll:
        event = await coll.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="Test",
            event_code="SYS-HEARTBEAT",
            message="Context manager test",
            context={},
        )
        assert event is not None
    # After exit, db should be closed
    assert coll._db is None
