"""
Entomology System — Report Tests (L1-01..L1-14, L2-01..L2-12, L3-01..L3-10)

Tests for EntomologyReportGenerator: Layer 1 (scorecards),
Layer 2 (patterns), Layer 3 (timeline).
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticSeverity,
)
from app.reports.entomology_report import (
    EntomologyReportGenerator,
    SEVERITY_COLORS,
    REPORT_WINDOW_DAYS,
)


# ─── Helper: seed events for report testing ────────────

async def _seed_mixed_events(collector, count_per_category=3):
    """Seed a mix of events across categories and severities."""
    combos = [
        (DiagnosticCategory.DEVICE, DiagnosticSeverity.ERROR, "DEV-001", "Terminal unreachable"),
        (DiagnosticCategory.DEVICE, DiagnosticSeverity.WARNING, "DEV-002", "Terminal timeout"),
        (DiagnosticCategory.NETWORK, DiagnosticSeverity.ERROR, "NET-001", "TCP timeout"),
        (DiagnosticCategory.NETWORK, DiagnosticSeverity.INFO, "NET-004", "Reconnect attempt"),
        (DiagnosticCategory.SYSTEM, DiagnosticSeverity.INFO, "SYS-HEARTBEAT", "Heartbeat"),
        (DiagnosticCategory.SYSTEM, DiagnosticSeverity.CRITICAL, "SYS-002", "Integrity failure"),
        (DiagnosticCategory.PERIPHERAL, DiagnosticSeverity.ERROR, "PER-001", "Printer failed"),
        (DiagnosticCategory.PERIPHERAL, DiagnosticSeverity.WARNING, "PER-005", "Printer offline"),
        (DiagnosticCategory.RECOVERY, DiagnosticSeverity.INFO, "REC-001", "Retry succeeded"),
        (DiagnosticCategory.RECOVERY, DiagnosticSeverity.WARNING, "REC-002", "Retry exhausted"),
    ]
    events = []
    for cat, sev, code, msg in combos:
        for i in range(count_per_category):
            e = await collector.record(
                category=cat,
                severity=sev,
                source="TestSource",
                event_code=code,
                message=f"{msg} #{i}",
                context={"iteration": i},
            )
            events.append(e)
    return events


# ═════════════════════════════════════════════════════════
# LAYER 1 — SYSTEM HEALTH SUMMARY
# ═════════════════════════════════════════════════════════

# ─── L1-01: generate() returns HTML and filename ───────

@pytest.mark.asyncio
async def test_l1_01_generate_returns_tuple(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, filename = await gen.generate()
    assert isinstance(html, str)
    assert isinstance(filename, str)
    assert filename.endswith(".html")


# ─── L1-02: HTML is valid structure ────────────────────

@pytest.mark.asyncio
async def test_l1_02_html_structure(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "</html>" in html
    assert "<style>" in html


# ─── L1-03: All 5 category scorecards present ──────────

@pytest.mark.asyncio
async def test_l1_03_all_scorecards(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    for cat in DiagnosticCategory:
        assert cat.value in html


# ─── L1-04: Scorecard shows event counts ───────────────

@pytest.mark.asyncio
async def test_l1_04_scorecard_counts(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "events" in html


# ─── L1-05: Severity badges in scorecards ──────────────

@pytest.mark.asyncio
async def test_l1_05_severity_badges(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "INFO" in html
    assert "WARN" in html
    assert "ERR" in html
    assert "CRIT" in html


# ─── L1-06: Health color — CRITICAL is red ─────────────

@pytest.mark.asyncio
async def test_l1_06_health_color_critical(collector):
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.CRITICAL,
        source="Test",
        event_code="SYS-002",
        message="Critical event",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert SEVERITY_COLORS["CRITICAL"] in html


# ─── L1-07: Health color — INFO-only is green ──────────

@pytest.mark.asyncio
async def test_l1_07_health_color_info(collector):
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Heartbeat",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert SEVERITY_COLORS["INFO"] in html


# ─── L1-08: Top 5 issues table present ─────────────────

@pytest.mark.asyncio
async def test_l1_08_top5_table(collector):
    await _seed_mixed_events(collector, count_per_category=5)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Top 5 Issues" in html
    assert "<table" in html


# ─── L1-09: Active/resolved summary present ────────────

@pytest.mark.asyncio
async def test_l1_09_active_resolved(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "active issues" in html
    assert "resolved" in html


# ─── L1-10: Empty events produce valid report ──────────

@pytest.mark.asyncio
async def test_l1_10_empty_report(collector):
    gen = EntomologyReportGenerator(collector)
    html, filename = await gen.generate()
    assert "<!DOCTYPE html>" in html
    assert filename.endswith(".html")


# ─── L1-11: Site name appears in report ────────────────

@pytest.mark.asyncio
async def test_l1_11_site_name(collector):
    gen = EntomologyReportGenerator(collector, site_name="TestStore")
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Test",
        context={},
    )
    html, filename = await gen.generate()
    assert "TestStore" in html
    assert "TestStore" in filename


# ─── L1-12: Terminal ID filtering ──────────────────────

@pytest.mark.asyncio
async def test_l1_12_terminal_filter(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate(terminal_ids=["terminal-test-01"])
    assert "terminal-test-01" in html


# ─── L1-13: Report window is 7 days ────────────────────

def test_l1_13_report_window():
    assert REPORT_WINDOW_DAYS == 7


# ─── L1-14: Layer 1 section present ────────────────────

@pytest.mark.asyncio
async def test_l1_14_layer1_section(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Layer 1" in html
    assert "System Health Summary" in html


# ═════════════════════════════════════════════════════════
# LAYER 2 — PATTERN ANALYSIS
# ═════════════════════════════════════════════════════════

# ─── L2-01: Layer 2 section present ────────────────────

@pytest.mark.asyncio
async def test_l2_01_layer2_section(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Layer 2" in html
    assert "Pattern Analysis" in html


# ─── L2-02: Recurring clusters detected ────────────────

@pytest.mark.asyncio
async def test_l2_02_recurring_clusters(collector):
    for i in range(5):
        await collector.record(
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.ERROR,
            source="Test",
            event_code="DEV-001",
            message="Recurring issue",
            context={},
        )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Recurring Issue Clusters" in html
    assert "DEV-001" in html
    assert "5 occurrences" in html


# ─── L2-03: No recurring issues message ────────────────

@pytest.mark.asyncio
async def test_l2_03_no_recurring(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="DEV-006",
        message="Single event",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "No recurring issues" in html


# ─── L2-04: Hour histogram rendered ────────────────────

@pytest.mark.asyncio
async def test_l2_04_hour_histogram(collector):
    for i in range(3):
        await collector.record(
            category=DiagnosticCategory.DEVICE,
            severity=DiagnosticSeverity.ERROR,
            source="Test",
            event_code="DEV-001",
            message="Recurring",
            context={},
        )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Hour of Day Distribution" in html
    assert "hist-bar" in html


# ─── L2-05: Peripheral timeline section ────────────────

@pytest.mark.asyncio
async def test_l2_05_peripheral_timeline(collector):
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Peripheral Health Timeline" in html


# ─── L2-06: Peripheral timeline with heartbeat data ────

@pytest.mark.asyncio
async def test_l2_06_peripheral_with_data(collector):
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="DiagnosticCollector",
        event_code="SYS-HEARTBEAT",
        message="Heartbeat",
        context={
            "peripherals": {
                "AA:BB:CC:DD:EE:FF": {"status": "ONLINE", "response_ms": 5},
            },
            "system": {},
        },
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "AA:BB:CC:DD:EE:FF" in html
    assert "Uptime:" in html


# ─── L2-07: Correlation chains section ─────────────────

@pytest.mark.asyncio
async def test_l2_07_correlation_chains(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Correlation Chains" in html


# ─── L2-08: Correlation chain with resolved/unresolved ─

@pytest.mark.asyncio
async def test_l2_08_resolved_unresolved_chains(collector):
    corr_id = "order-123"
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Error",
        context={},
        correlation_id=corr_id,
    )
    await collector.record(
        category=DiagnosticCategory.RECOVERY,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="REC-001",
        message="Recovered",
        context={},
        correlation_id=corr_id,
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Resolved" in html


# ─── L2-09: Escalation candidates section ──────────────

@pytest.mark.asyncio
async def test_l2_09_escalation_section(collector):
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Escalation Candidates" in html


# ─── L2-10: Escalation detected for increasing trend ───

@pytest.mark.asyncio
async def test_l2_10_escalation_detected(collector):
    now = datetime.now(timezone.utc)
    for day_offset in range(3):
        count = day_offset + 1  # 1, 2, 3 — increasing
        for i in range(count):
            await collector.record(
                category=DiagnosticCategory.DEVICE,
                severity=DiagnosticSeverity.ERROR,
                source="Test",
                event_code="DEV-001",
                message="Escalating",
                context={},
            )
            # Backdate to different days
            ts = (now - timedelta(days=2 - day_offset)).isoformat()
            await collector._db.execute(
                "UPDATE diagnostic_events SET timestamp = ? WHERE id = (SELECT MAX(id) FROM diagnostic_events)",
                (ts,),
            )
            await collector._db.commit()

    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "INCREASING" in html


# ─── L2-11: No escalation when stable ──────────────────

@pytest.mark.asyncio
async def test_l2_11_no_escalation(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="DEV-006",
        message="Stable",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "No escalating trends" in html


# ─── L2-12: Cluster shows sources ──────────────────────

@pytest.mark.asyncio
async def test_l2_12_cluster_sources(collector):
    for src in ["AdapterA", "AdapterB"]:
        for i in range(2):
            await collector.record(
                category=DiagnosticCategory.DEVICE,
                severity=DiagnosticSeverity.ERROR,
                source=src,
                event_code="DEV-001",
                message="Multi-source",
                context={},
            )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "AdapterA" in html
    assert "AdapterB" in html
    assert "Sources:" in html


# ═════════════════════════════════════════════════════════
# LAYER 3 — EVENT TIMELINE
# ═════════════════════════════════════════════════════════

# ─── L3-01: Layer 3 section present ────────────────────

@pytest.mark.asyncio
async def test_l3_01_layer3_section(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Layer 3" in html
    assert "Event Timeline" in html


# ─── L3-02: Default filters to WARNING+ ────────────────

@pytest.mark.asyncio
async def test_l3_02_default_warning_filter(collector):
    await collector.record(
        category=DiagnosticCategory.SYSTEM,
        severity=DiagnosticSeverity.INFO,
        source="Test",
        event_code="SYS-HEARTBEAT",
        message="Info only",
        context={},
    )
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Error event",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    # The main timeline should have the error
    assert "Error event" in html


# ─── L3-03: Full timeline toggle exists ────────────────

@pytest.mark.asyncio
async def test_l3_03_full_timeline_toggle(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Show all events" in html


# ─── L3-04: Timeline rows have severity colors ─────────

@pytest.mark.asyncio
async def test_l3_04_severity_colors(collector):
    await _seed_mixed_events(collector)
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    for color in SEVERITY_COLORS.values():
        assert color in html


# ─── L3-05: Context JSON expandable ────────────────────

@pytest.mark.asyncio
async def test_l3_05_context_expandable(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="With context",
        context={"device_ip": "10.0.0.1", "port": 8080},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Context" in html
    assert "context-json" in html
    assert "10.0.0.1" in html


# ─── L3-06: Heartbeat collapsing in full timeline ──────

@pytest.mark.asyncio
async def test_l3_06_heartbeat_collapsing(collector):
    now = datetime.now(timezone.utc)
    # Create multiple off-hours heartbeats (15 min apart)
    for i in range(4):
        await collector.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="DiagnosticCollector",
            event_code="SYS-HEARTBEAT",
            message="Heartbeat",
            context={},
        )
        # Backdate with 15-min gaps
        ts = (now - timedelta(minutes=45 - i * 15)).isoformat()
        await collector._db.execute(
            "UPDATE diagnostic_events SET timestamp = ? WHERE id = (SELECT MAX(id) FROM diagnostic_events)",
            (ts,),
        )
        await collector._db.commit()

    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "heartbeats" in html
    assert "all healthy" in html


# ─── L3-07: Correlation links in timeline ──────────────

@pytest.mark.asyncio
async def test_l3_07_correlation_links(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="Test",
        event_code="DEV-001",
        message="Linked event",
        context={},
        correlation_id="order-456",
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "Correlated:" in html
    assert "order-45" in html  # Truncated display


# ─── L3-08: Empty timeline message ─────────────────────

@pytest.mark.asyncio
async def test_l3_08_empty_timeline(collector):
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "No events" in html


# ─── L3-09: Timeline rows show source ──────────────────

@pytest.mark.asyncio
async def test_l3_09_timeline_shows_source(collector):
    await collector.record(
        category=DiagnosticCategory.DEVICE,
        severity=DiagnosticSeverity.ERROR,
        source="DejavooSPInAdapter",
        event_code="DEV-001",
        message="Source test",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "DejavooSPInAdapter" in html


# ─── L3-10: Timeline rows show event code ──────────────

@pytest.mark.asyncio
async def test_l3_10_timeline_shows_code(collector):
    await collector.record(
        category=DiagnosticCategory.NETWORK,
        severity=DiagnosticSeverity.WARNING,
        source="Test",
        event_code="NET-007",
        message="Latency elevated",
        context={},
    )
    gen = EntomologyReportGenerator(collector)
    html, _ = await gen.generate()
    assert "NET-007" in html
