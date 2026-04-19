"""
Entomology System — Integration Tests (I-01 .. I-08)

End-to-end tests: record → query → report, high volume,
hash chain integrity, and full day simulation.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
    GENESIS_HASH,
    compute_diagnostic_hash,
)
from app.reports.entomology_report import EntomologyReportGenerator
from app.services.diagnostic_collector import DiagnosticCollector


# ─── I-01: End-to-end record → query → report ──────────

@pytest.mark.asyncio
async def test_i01_end_to_end(collector):
    # Record
    event = await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="DejavooSPInAdapter",
        event_code="DEV-001",
        message="Payment terminal unreachable",
        context={"device_ip": "10.0.0.100", "timeout_ms": 5000},
    )

    # Query
    events = await collector.get_events(event_code="DEV-001")
    assert len(events) == 1
    assert events[0].diagnostic_id == event.diagnostic_id

    # Report
    gen = EntomologyReportGenerator(collector)
    html, filename = await gen.generate()
    assert "DEV-001" in html
    assert "Payment terminal unreachable" in html
    assert filename.endswith(".html")


# ─── I-02: Mixed categories end-to-end ─────────────────

@pytest.mark.asyncio
async def test_i02_mixed_categories(collector):
    categories = [
        (DiagnosticCategory.DEVICE, DiagnosticSeverity.ERROR, "DEV-001", "Device error"),
        (DiagnosticCategory.NETWORK, DiagnosticSeverity.WARNING, "NET-007", "High latency"),
        (DiagnosticCategory.SYSTEM, DiagnosticSeverity.INFO, "SYS-HEARTBEAT", "Heartbeat"),
        (DiagnosticCategory.PERIPHERAL, DiagnosticSeverity.ERROR, "PER-001", "Printer down"),
        (DiagnosticCategory.RECOVERY, DiagnosticSeverity.INFO, "REC-001", "Retry OK"),
    ]
    for cat, sev, code, msg in categories:
        await collector.record(
            category=cat, severity=sev, source="Test",
            event_code=code, message=msg, context={},
        )

    assert await collector.count_events() == 5

    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    for cat, _, code, _ in categories:
        assert code in html


# ─── I-03: High volume — 500 events ────────────────────

@pytest.mark.asyncio
async def test_i03_high_volume(collector):
    for i in range(500):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="LoadTest",
            event_code="SYS-HEARTBEAT",
            message=f"Event {i}",
            context={"seq": i},
        )
    assert await collector.count_events() == 500

    events = await collector.get_all_events_ordered()
    assert len(events) == 500


# ─── I-04: Hash chain integrity over 100 events ────────

@pytest.mark.asyncio
async def test_i04_hash_chain_integrity(collector):
    for i in range(100):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="ChainTest",
            event_code="SYS-HEARTBEAT",
            message=f"Chain {i}",
            context={"i": i},
        )

    events = await collector.get_all_events_ordered()
    assert len(events) == 100

    # Verify genesis
    assert events[0].prev_hash == GENESIS_HASH

    # Verify full chain
    for i in range(1, len(events)):
        assert events[i].prev_hash == events[i - 1].hash

    # Verify each hash is correct
    for e in events:
        expected = compute_diagnostic_hash(
            prev_hash=e.prev_hash,
            diagnostic_id=e.diagnostic_id,
            timestamp=e.timestamp.isoformat(),
            category=e.category.value,
            severity=e.severity.value,
            source=e.source,
            event_code=e.event_code,
            message=e.message,
            context=e.context,
        )
        assert e.hash == expected


# ─── I-05: Correlation chain end-to-end ────────────────

@pytest.mark.asyncio
async def test_i05_correlation_chain(collector):
    corr_id = "order-e2e-001"

    # Error occurs
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="DejavooSPInAdapter",
        event_code="DEV-001",
        message="Terminal unreachable",
        context={"device_ip": "10.0.0.100"},
        correlation_id=corr_id,
    )

    # Retry attempted
    await collector.record(
        category=DiagnosticCategory.NETWORK,
        severity=DiagnosticSeverity.WARNING,
        source="DejavooSPInAdapter",
        event_code="NET-004",
        message="Reconnect attempt",
        context={"attempt": 1},
        correlation_id=corr_id,
    )

    # Recovery
    await collector.record(
        category=DiagnosticCategory.RECOVERY,
        severity=DiagnosticSeverity.INFO,
        source="DejavooSPInAdapter",
        event_code="REC-001",
        message="Retry succeeded",
        context={"attempts_total": 1},
        correlation_id=corr_id,
    )

    events = await collector.get_events(correlation_id=corr_id)
    assert len(events) == 3

    # Report should show resolved chain
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Resolved" in html


# ─── I-06: Full day simulation ─────────────────────────

@pytest.mark.asyncio
async def test_i06_full_day_simulation(collector):
    now = datetime.now(timezone.utc)

    # Morning — heartbeats every 15 min (off-hours, 6 AM)
    for i in range(4):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="DiagnosticCollector",
            event_code="SYS-HEARTBEAT",
            message="Off-hours heartbeat",
            context={"system": {"uptime_hours": 2.0 + i * 0.25}},
        )

    # Service starts — device events
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="DejavooSPInAdapter",
        event_code="DEV-001",
        message="Terminal unreachable at open",
        context={"device_ip": "10.0.0.100"},
    )
    await collector.record(
        category=DiagnosticCategory.RECOVERY,
        severity=DiagnosticSeverity.INFO,
        source="DejavooSPInAdapter",
        event_code="REC-004",
        message="Device reconnected",
        context={"device_ip": "10.0.0.100"},
    )

    # Active service — more frequent heartbeats
    for i in range(10):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="DiagnosticCollector",
            event_code="SYS-HEARTBEAT",
            message="Active heartbeat",
            context={"system": {"memory_used_pct": 45.0 + i}},
        )

    # Printer issue during service
    await collector.record(
        category=DiagnosticCategory.PERIPHERAL,
        severity=DiagnosticSeverity.ERROR,
        source="PrinterManager",
        event_code="PER-001",
        message="Kitchen printer offline",
        context={"printer_id": "printer-kitchen-01"},
    )
    await collector.record(
        category=DiagnosticCategory.PERIPHERAL,
        severity=DiagnosticSeverity.INFO,
        source="PrinterManager",
        event_code="PER-006",
        message="Failover to backup",
        context={"from": "printer-kitchen-01", "to": "printer-kitchen-02"},
    )

    total = await collector.count_events()
    assert total == 18

    # Generate report
    gen = EntomologyReportGenerator(collector)
    html, filename = await gen.generate()
    assert "<!DOCTYPE html>" in html
    assert "DEV-001" in html
    assert "PER-001" in html
    assert "REC-004" in html


# ─── I-07: Report with retention cycle ─────────────────

@pytest.mark.asyncio
async def test_i07_report_after_retention(tmp_path):
    db_path = str(tmp_path / "retention_report.db")
    archive_dir = str(tmp_path / "archive")

    async with DiagnosticCollector(db_path, "terminal-01") as coll:
        # Old events
        for i in range(5):
            await coll.record(
                category=DiagnosticCategory.SYSTEM,
                severity=DiagnosticSeverity.INFO,
                source="Test",
                event_code="SYS-HEARTBEAT",
                message=f"Old {i}",
                context={},
            )
        # Backdate all
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await coll._db.execute(
            "UPDATE diagnostic_events SET timestamp = ?", (old_ts,)
        )
        await coll._db.commit()

        # Recent events
        for i in range(3):
            await coll.record(
                category=DiagnosticCategory.DEVICE,
                severity=DiagnosticSeverity.ERROR,
                source="Test",
                event_code="DEV-001",
                message=f"Recent {i}",
                context={},
            )

        # Run retention
        archive = await coll.run_retention(retention_days=90, archive_dir=archive_dir)
        assert archive is not None

        # Report should only show recent events
        assert await coll.count_events() == 3
        gen = EntomologyReportGenerator(coll)
        html, _ = await gen.generate()
        assert "DEV-001" in html


# ─── I-08: Concurrent recording doesn't corrupt chain ──

@pytest.mark.asyncio
async def test_i08_concurrent_recording(collector):
    import asyncio

    async def record_batch(prefix, count):
        for i in range(count):
            await collector.record(
                category=DiagnosticCategory.SYSTEM,
                severity=DiagnosticSeverity.INFO,
                source=f"Concurrent-{prefix}",
                event_code="SYS-HEARTBEAT",
                message=f"{prefix}-{i}",
                context={"batch": prefix, "seq": i},
            )

    # Run 3 batches concurrently
    await asyncio.gather(
        record_batch("A", 20),
        record_batch("B", 20),
        record_batch("C", 20),
    )

    assert await collector.count_events() == 60

    # Verify hash chain integrity
    events = await collector.get_all_events_ordered()
    assert events[0].prev_hash == GENESIS_HASH
    for i in range(1, len(events)):
        assert events[i].prev_hash == events[i - 1].hash
