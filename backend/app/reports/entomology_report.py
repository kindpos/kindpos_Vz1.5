"""
KINDpos Entomology Report Generator

Produces a self-contained HTML file with three diagnostic layers:
  Layer 1 — System Health Summary (triage in 10 seconds)
  Layer 2 — Pattern Analysis (recurring issues, timelines, escalation)
  Layer 3 — Event Timeline (the microscope)

All CSS is inline. No JavaScript. Native <details>/<summary> for expansion.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from app.models.diagnostic_event import (
    DiagnosticCategory,
    DiagnosticEvent,
    DiagnosticSeverity,
)
from app.services.diagnostic_collector import DiagnosticCollector


# =============================================================================
# CONSTANTS
# =============================================================================

SEVERITY_COLORS = {
    "INFO": "#28a745",
    "WARNING": "#ffc107",
    "ERROR": "#fd7e14",
    "CRITICAL": "#dc3545",
}

REPORT_WINDOW_DAYS = 7


# =============================================================================
# REPORT GENERATOR
# =============================================================================

class EntomologyReportGenerator:
    """Generates a self-contained HTML Entomology Report."""

    def __init__(self, collector: DiagnosticCollector, site_name: str = "KINDpos"):
        self.collector = collector
        self.site_name = site_name

    async def generate(
        self, terminal_ids: Optional[list[str]] = None
    ) -> tuple[str, str]:
        """
        Generate the Entomology Report.

        Returns (html_content, filename).
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=REPORT_WINDOW_DAYS)

        events = await self.collector.get_events(since=since, until=now)

        if terminal_ids:
            events = [e for e in events if e.terminal_id in terminal_ids]

        terminal_id_set = sorted(set(e.terminal_id for e in events)) if events else []

        header_html = self._render_header(now, since, terminal_id_set)
        layer1_html = self._render_layer1(events)
        layer2_html = self._render_layer2(events)
        layer3_html = self._render_layer3(events)

        html = self._assemble_html(header_html, layer1_html, layer2_html, layer3_html)
        date_str = now.strftime("%Y-%m-%d")
        filename = f"{self.site_name}_entomology_{date_str}.html"

        return html, filename

    # =========================================================================
    # HEADER
    # =========================================================================

    def _render_header(
        self, now: datetime, since: datetime, terminal_ids: list[str]
    ) -> str:
        return f"""
        <div class="header">
            <h1>{escape(self.site_name)} — Entomology Report</h1>
            <div class="header-meta">
                <span>Terminal(s): {escape(', '.join(terminal_ids)) if terminal_ids else 'None'}</span>
                <span>Generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}</span>
                <span>Window: {since.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')} (last 7 days)</span>
            </div>
        </div>
        """

    # =========================================================================
    # LAYER 1 — SYSTEM HEALTH SUMMARY
    # =========================================================================

    def _render_layer1(self, events: list[DiagnosticEvent]) -> str:
        scorecards = self._render_scorecards(events)
        top5 = self._render_top5(events)
        active_resolved = self._render_active_resolved(events)

        return f"""
        <section class="layer" id="layer1">
            <h2>Layer 1 — System Health Summary</h2>
            <div class="scorecards">{scorecards}</div>
            <div class="top5">{top5}</div>
            <div class="active-resolved">{active_resolved}</div>
        </section>
        """

    def _render_scorecards(self, events: list[DiagnosticEvent]) -> str:
        cards = []
        for cat in DiagnosticCategory:
            cat_events = [e for e in events if e.category == cat]
            severity_counts = Counter(e.severity.value for e in cat_events)
            total = len(cat_events)

            # Top offender
            code_counts = Counter(e.event_code for e in cat_events)
            top_offender = code_counts.most_common(1)[0] if code_counts else None

            # Health color
            health_color = self._health_color(cat_events)

            cards.append(f"""
            <div class="scorecard" style="border-top: 4px solid {health_color};">
                <h3>{escape(cat.value)}</h3>
                <div class="scorecard-total">{total} events</div>
                <div class="severity-breakdown">
                    <span class="sev-badge" style="background:{SEVERITY_COLORS['INFO']};">{severity_counts.get('INFO', 0)} INFO</span>
                    <span class="sev-badge" style="background:{SEVERITY_COLORS['WARNING']};">{severity_counts.get('WARNING', 0)} WARN</span>
                    <span class="sev-badge" style="background:{SEVERITY_COLORS['ERROR']};">{severity_counts.get('ERROR', 0)} ERR</span>
                    <span class="sev-badge" style="background:{SEVERITY_COLORS['CRITICAL']};">{severity_counts.get('CRITICAL', 0)} CRIT</span>
                </div>
                <div class="top-offender">
                    Top: {escape(top_offender[0]) + ' (' + str(top_offender[1]) + ')' if top_offender else 'None'}
                </div>
            </div>
            """)

        return "\n".join(cards)

    def _health_color(self, events: list[DiagnosticEvent]) -> str:
        severities = set(e.severity for e in events)
        if DiagnosticSeverity.CRITICAL in severities:
            return SEVERITY_COLORS["CRITICAL"]
        if DiagnosticSeverity.ERROR in severities:
            return SEVERITY_COLORS["ERROR"]
        if DiagnosticSeverity.WARNING in severities:
            return SEVERITY_COLORS["WARNING"]
        return SEVERITY_COLORS["INFO"]

    def _render_top5(self, events: list[DiagnosticEvent]) -> str:
        code_counts = Counter(e.event_code for e in events)
        top5 = code_counts.most_common(5)

        if not top5:
            return "<p>No issues in this window.</p>"

        rows = []
        for code, count in top5:
            matching = [e for e in events if e.event_code == code]
            most_recent = max(matching, key=lambda e: e.timestamp)
            rows.append(f"""
            <tr>
                <td><strong>{escape(code)}</strong></td>
                <td>{count}</td>
                <td>{escape(most_recent.category.value)}</td>
                <td>{most_recent.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>
                <td>{escape(most_recent.message)}</td>
            </tr>
            """)

        return f"""
        <h3>Top 5 Issues</h3>
        <table class="data-table">
            <thead>
                <tr><th>Code</th><th>Count</th><th>Category</th><th>Last Seen</th><th>Message</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """

    def _render_active_resolved(self, events: list[DiagnosticEvent]) -> str:
        # ERROR/CRITICAL events are "issues"
        issues = [
            e for e in events
            if e.severity in (DiagnosticSeverity.ERROR, DiagnosticSeverity.CRITICAL)
        ]
        recovery_events = [
            e for e in events if e.category == DiagnosticCategory.RECOVERY
        ]
        recovery_corr_ids = set(
            e.correlation_id for e in recovery_events if e.correlation_id
        )

        resolved = sum(
            1 for e in issues
            if e.correlation_id and e.correlation_id in recovery_corr_ids
        )
        active = len(issues) - resolved

        return f"""
        <div class="active-resolved-summary">
            <span class="active-count">{active} active issues</span> /
            <span class="resolved-count">{resolved} resolved this week</span>
        </div>
        """

    # =========================================================================
    # LAYER 2 — PATTERN ANALYSIS
    # =========================================================================

    def _render_layer2(self, events: list[DiagnosticEvent]) -> str:
        clusters = self._render_clusters(events)
        peripheral_timeline = self._render_peripheral_timeline(events)
        correlation_chains = self._render_correlation_chains(events)
        escalation = self._render_escalation(events)

        return f"""
        <section class="layer" id="layer2">
            <h2>Layer 2 — Pattern Analysis</h2>
            {clusters}
            {peripheral_timeline}
            {correlation_chains}
            {escalation}
        </section>
        """

    def _render_clusters(self, events: list[DiagnosticEvent]) -> str:
        code_counts = Counter(e.event_code for e in events)
        recurring = {code: count for code, count in code_counts.items() if count >= 2}

        if not recurring:
            return "<h3>Recurring Issue Clusters</h3><p>No recurring issues.</p>"

        sections = ["<h3>Recurring Issue Clusters</h3>"]

        for code, count in sorted(recurring.items(), key=lambda x: -x[1]):
            matching = [e for e in events if e.event_code == code]
            sources = sorted(set(e.source for e in matching))
            message = matching[-1].message

            # Hour-of-day histogram
            hour_counts = Counter(e.timestamp.hour for e in matching)
            max_count = max(hour_counts.values()) if hour_counts else 1
            histogram = self._render_hour_histogram(hour_counts, max_count)

            sections.append(f"""
            <div class="cluster">
                <div class="cluster-header">
                    <strong>{escape(code)}</strong> — {escape(message)}
                    <span class="cluster-count">{count} occurrences</span>
                </div>
                <div class="cluster-sources">Sources: {escape(', '.join(sources))}</div>
                <div class="histogram-container">
                    <div class="histogram-label">Hour of Day Distribution</div>
                    {histogram}
                </div>
            </div>
            """)

        return "\n".join(sections)

    def _render_hour_histogram(self, hour_counts: Counter, max_count: int) -> str:
        bars = []
        for hour in range(24):
            count = hour_counts.get(hour, 0)
            pct = (count / max_count * 100) if max_count > 0 else 0
            bars.append(f"""
            <div class="hist-bar-container">
                <div class="hist-bar" style="height:{pct}%;" title="{hour}:00 — {count}"></div>
                <div class="hist-label">{hour}</div>
            </div>
            """)
        return f'<div class="histogram">{"".join(bars)}</div>'

    def _render_peripheral_timeline(self, events: list[DiagnosticEvent]) -> str:
        # Extract peripheral status from heartbeat events
        heartbeats = [
            e for e in events if e.event_code == "SYS-HEARTBEAT"
        ]

        # Collect all known peripherals by MAC
        peripherals: dict[str, list[dict]] = defaultdict(list)
        for hb in heartbeats:
            periph_data = hb.context.get("peripherals", {})
            for mac, status in periph_data.items():
                peripherals[mac].append({
                    "timestamp": hb.timestamp,
                    "status": status.get("status", "UNKNOWN"),
                    "response_ms": status.get("response_ms", 0),
                })

        if not peripherals:
            return "<h3>Peripheral Health Timeline</h3><p>No peripheral data available.</p>"

        sections = ["<h3>Peripheral Health Timeline</h3>"]

        for mac in sorted(peripherals.keys()):
            snapshots = sorted(peripherals[mac], key=lambda s: s["timestamp"])
            total = len(snapshots)
            online_count = sum(
                1 for s in snapshots if s["status"] == "ONLINE"
            )
            uptime_pct = round((online_count / total) * 100, 1) if total else 0

            # Offline incidents
            offline_periods = []
            current_offline_start = None
            for snap in snapshots:
                if snap["status"] != "ONLINE":
                    if current_offline_start is None:
                        current_offline_start = snap["timestamp"]
                else:
                    if current_offline_start is not None:
                        offline_periods.append(
                            (current_offline_start, snap["timestamp"])
                        )
                        current_offline_start = None
            if current_offline_start is not None:
                offline_periods.append(
                    (current_offline_start, snapshots[-1]["timestamp"])
                )

            longest_offline = timedelta(0)
            for start, end in offline_periods:
                duration = end - start
                if duration > longest_offline:
                    longest_offline = duration

            sections.append(f"""
            <div class="peripheral-card">
                <div class="peripheral-header">
                    <strong>{escape(mac)}</strong>
                    <span class="uptime">Uptime: {uptime_pct}%</span>
                </div>
                <div class="peripheral-stats">
                    Offline incidents: {len(offline_periods)} |
                    Longest offline: {self._format_duration(longest_offline)}
                </div>
            </div>
            """)

        return "\n".join(sections)

    def _render_correlation_chains(self, events: list[DiagnosticEvent]) -> str:
        # Group events by correlation_id
        correlated: dict[str, list[DiagnosticEvent]] = defaultdict(list)
        for e in events:
            if e.correlation_id:
                correlated[e.correlation_id].append(e)

        if not correlated:
            return "<h3>Correlation Chains</h3><p>No correlated events found.</p>"

        resolved_chains = []
        unresolved_chains = []

        for corr_id, chain_events in correlated.items():
            chain_events.sort(key=lambda e: e.timestamp)
            has_recovery = any(
                e.category == DiagnosticCategory.RECOVERY for e in chain_events
            )
            chain_str = " → ".join(
                f"{e.event_code} ({e.severity.value})" for e in chain_events
            )

            entry = f"""
            <div class="chain-entry {'resolved' if has_recovery else 'unresolved'}">
                <span class="chain-id">{escape(corr_id[:8])}...</span>
                <span class="chain-flow">{escape(chain_str)}</span>
                <span class="chain-status">{'✅' if has_recovery else '❌'}</span>
            </div>
            """

            if has_recovery:
                resolved_chains.append(entry)
            else:
                unresolved_chains.append(entry)

        return f"""
        <h3>Correlation Chains</h3>
        <details>
            <summary>Resolved ({len(resolved_chains)})</summary>
            {''.join(resolved_chains) if resolved_chains else '<p>None</p>'}
        </details>
        <details open>
            <summary>Unresolved ({len(unresolved_chains)})</summary>
            {''.join(unresolved_chains) if unresolved_chains else '<p>None</p>'}
        </details>
        """

    def _render_escalation(self, events: list[DiagnosticEvent]) -> str:
        # Group events by event_code and day
        code_daily: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for e in events:
            day = e.timestamp.strftime("%Y-%m-%d")
            code_daily[e.event_code][day] += 1

        escalation_candidates = []

        for code, daily_counts in code_daily.items():
            if len(daily_counts) < 2:
                continue
            sorted_days = sorted(daily_counts.keys())
            counts = [daily_counts[d] for d in sorted_days]

            # Simple linear trend: is it generally increasing?
            increasing = sum(
                1 for i in range(1, len(counts)) if counts[i] > counts[i - 1]
            )
            decreasing = sum(
                1 for i in range(1, len(counts)) if counts[i] < counts[i - 1]
            )

            if increasing > decreasing:
                daily_str = " → ".join(
                    f"{d}: {daily_counts[d]}" for d in sorted_days
                )
                escalation_candidates.append(
                    f"""
                    <div class="escalation-entry">
                        <strong>{escape(code)}</strong>
                        <span class="trend-up">↑ INCREASING</span>
                        <div class="daily-counts">{escape(daily_str)}</div>
                    </div>
                    """
                )

        if not escalation_candidates:
            return "<h3>Escalation Candidates</h3><p>No escalating trends detected.</p>"

        return f"""
        <h3>Escalation Candidates</h3>
        {''.join(escalation_candidates)}
        """

    # =========================================================================
    # LAYER 3 — EVENT TIMELINE
    # =========================================================================

    def _render_layer3(self, events: list[DiagnosticEvent]) -> str:
        # Sort oldest first
        events_sorted = sorted(events, key=lambda e: e.timestamp)

        # Default: WARNING+ only
        warning_plus = [
            e for e in events_sorted
            if e.severity >= DiagnosticSeverity.WARNING
        ]

        filtered_timeline = self._render_timeline_rows(warning_plus, collapse_heartbeats=False)
        full_timeline = self._render_timeline_rows(events_sorted, collapse_heartbeats=True)

        return f"""
        <section class="layer" id="layer3">
            <h2>Layer 3 — Event Timeline</h2>
            <div class="timeline">
                {filtered_timeline}
            </div>
            <details class="full-timeline-toggle">
                <summary>Show all events (including INFO/heartbeats)</summary>
                <div class="timeline">
                    {full_timeline}
                </div>
            </details>
        </section>
        """

    def _render_timeline_rows(
        self, events: list[DiagnosticEvent], collapse_heartbeats: bool
    ) -> str:
        if not events:
            return "<p>No events in this view.</p>"

        rows = []
        i = 0
        while i < len(events):
            event = events[i]

            # Collapse consecutive off-hours heartbeats
            if (
                collapse_heartbeats
                and event.event_code == "SYS-HEARTBEAT"
                and event.severity == DiagnosticSeverity.INFO
            ):
                # Look ahead for consecutive healthy heartbeats
                j = i + 1
                while j < len(events):
                    next_ev = events[j]
                    if (
                        next_ev.event_code == "SYS-HEARTBEAT"
                        and next_ev.severity == DiagnosticSeverity.INFO
                        and self._is_off_hours_gap(event, next_ev)
                    ):
                        j += 1
                    else:
                        break

                consecutive_count = j - i
                if consecutive_count >= 2:
                    first_ts = events[i].timestamp.strftime("%H:%M")
                    last_ts = events[j - 1].timestamp.strftime("%H:%M")

                    # Build individual snapshots for expand
                    individual_rows = "\n".join(
                        self._render_single_row(events[k])
                        for k in range(i, j)
                    )

                    rows.append(f"""
                    <div class="timeline-row collapsed-heartbeats" style="border-left: 3px solid {SEVERITY_COLORS['INFO']};">
                        <details>
                            <summary>
                                {consecutive_count} heartbeats ({first_ts}–{last_ts}), all healthy
                            </summary>
                            {individual_rows}
                        </details>
                    </div>
                    """)
                    i = j
                    continue

            rows.append(self._render_single_row(event))
            i += 1

        return "\n".join(rows)

    def _render_single_row(self, event: DiagnosticEvent) -> str:
        color = SEVERITY_COLORS.get(event.severity.value, "#999")
        ts = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        context_json = json.dumps(event.context, indent=2)

        correlation_link = ""
        if event.correlation_id:
            correlation_link = (
                f' <a class="corr-link" href="#corr-{escape(event.correlation_id)}">'
                f'Correlated: {escape(event.correlation_id[:8])}...</a>'
            )

        return f"""
        <div class="timeline-row" style="border-left: 3px solid {color};">
            <div class="row-header">
                <span class="row-ts">{ts}</span>
                <span class="sev-badge" style="background:{color};">{escape(event.severity.value)}</span>
                <span class="cat-badge">{escape(event.category.value)}</span>
                <span class="row-code">{escape(event.event_code)}</span>
                <span class="row-source">{escape(event.source)}</span>
                <span class="row-message">{escape(event.message)}</span>
                {correlation_link}
            </div>
            <details>
                <summary>Context</summary>
                <pre class="context-json">{escape(context_json)}</pre>
            </details>
        </div>
        """

    def _is_off_hours_gap(
        self, event_a: DiagnosticEvent, event_b: DiagnosticEvent
    ) -> bool:
        """Check if two heartbeats represent an off-hours gap (>= 10 min apart)."""
        gap = (event_b.timestamp - event_a.timestamp).total_seconds()
        return gap >= 600  # 10 minutes — off-hours heartbeats are 15 min apart

    # =========================================================================
    # HTML ASSEMBLY
    # =========================================================================

    def _assemble_html(
        self, header: str, layer1: str, layer2: str, layer3: str
    ) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(self.site_name)} — Entomology Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; line-height: 1.5; }}
        .header {{ background: #16213e; padding: 24px; border-radius: 8px; margin-bottom: 24px; }}
        .header h1 {{ font-size: 1.5em; color: #fff; margin-bottom: 8px; }}
        .header-meta {{ display: flex; flex-wrap: wrap; gap: 16px; font-size: 0.85em; color: #a0a0a0; }}
        .layer {{ background: #16213e; padding: 24px; border-radius: 8px; margin-bottom: 24px; }}
        .layer h2 {{ font-size: 1.2em; color: #fff; margin-bottom: 16px; border-bottom: 1px solid #333; padding-bottom: 8px; }}
        .layer h3 {{ font-size: 1em; color: #ccc; margin: 16px 0 8px; }}

        /* Scorecards */
        .scorecards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }}
        .scorecard {{ background: #0f3460; padding: 16px; border-radius: 6px; }}
        .scorecard h3 {{ margin: 0 0 8px; font-size: 0.95em; }}
        .scorecard-total {{ font-size: 1.4em; font-weight: bold; margin-bottom: 8px; }}
        .severity-breakdown {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }}
        .sev-badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.75em; color: #000; font-weight: bold; }}
        .top-offender {{ font-size: 0.8em; color: #a0a0a0; }}

        /* Data Table */
        .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
        .data-table th {{ text-align: left; padding: 8px; background: #0f3460; border-bottom: 2px solid #333; }}
        .data-table td {{ padding: 8px; border-bottom: 1px solid #2a2a4a; }}

        /* Active/Resolved */
        .active-resolved-summary {{ font-size: 1.1em; padding: 12px; background: #0f3460; border-radius: 6px; }}
        .active-count {{ color: {SEVERITY_COLORS['ERROR']}; font-weight: bold; }}
        .resolved-count {{ color: {SEVERITY_COLORS['INFO']}; font-weight: bold; }}

        /* Clusters */
        .cluster {{ background: #0f3460; padding: 16px; border-radius: 6px; margin-bottom: 12px; }}
        .cluster-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
        .cluster-count {{ font-size: 0.85em; color: #a0a0a0; }}
        .cluster-sources {{ font-size: 0.8em; color: #888; margin-bottom: 8px; }}

        /* Histogram */
        .histogram-container {{ margin-top: 8px; }}
        .histogram-label {{ font-size: 0.8em; color: #888; margin-bottom: 4px; }}
        .histogram {{ display: flex; align-items: flex-end; gap: 2px; height: 60px; }}
        .hist-bar-container {{ display: flex; flex-direction: column; align-items: center; flex: 1; height: 100%; justify-content: flex-end; }}
        .hist-bar {{ width: 100%; background: #e94560; border-radius: 2px 2px 0 0; min-height: 1px; }}
        .hist-label {{ font-size: 0.6em; color: #666; margin-top: 2px; }}

        /* Peripheral */
        .peripheral-card {{ background: #0f3460; padding: 12px; border-radius: 6px; margin-bottom: 8px; }}
        .peripheral-header {{ display: flex; justify-content: space-between; }}
        .uptime {{ color: {SEVERITY_COLORS['INFO']}; }}
        .peripheral-stats {{ font-size: 0.8em; color: #888; margin-top: 4px; }}

        /* Correlation Chains */
        .chain-entry {{ padding: 8px; border-bottom: 1px solid #2a2a4a; display: flex; gap: 12px; align-items: center; font-size: 0.85em; }}
        .chain-entry.resolved {{ border-left: 3px solid {SEVERITY_COLORS['INFO']}; }}
        .chain-entry.unresolved {{ border-left: 3px solid {SEVERITY_COLORS['ERROR']}; }}
        .chain-id {{ color: #888; font-family: monospace; }}
        .chain-flow {{ flex: 1; }}
        .chain-status {{ font-size: 1.2em; }}

        /* Escalation */
        .escalation-entry {{ background: #0f3460; padding: 12px; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid {SEVERITY_COLORS['WARNING']}; }}
        .trend-up {{ color: {SEVERITY_COLORS['ERROR']}; font-weight: bold; margin-left: 8px; }}
        .daily-counts {{ font-size: 0.8em; color: #888; margin-top: 4px; }}

        /* Timeline */
        .timeline {{ margin-top: 8px; }}
        .timeline-row {{ padding: 8px 12px; margin-bottom: 4px; background: #0f3460; border-radius: 4px; }}
        .row-header {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 0.85em; }}
        .row-ts {{ color: #888; font-family: monospace; }}
        .cat-badge {{ background: #2a2a4a; padding: 1px 6px; border-radius: 3px; font-size: 0.8em; }}
        .row-code {{ font-weight: bold; }}
        .row-source {{ color: #888; }}
        .row-message {{ color: #ccc; }}
        .corr-link {{ color: #5dade2; text-decoration: none; font-size: 0.8em; }}
        .corr-link:hover {{ text-decoration: underline; }}
        .context-json {{ background: #0a0a1a; padding: 12px; border-radius: 4px; font-size: 0.8em; overflow-x: auto; white-space: pre-wrap; color: #a0d0a0; }}
        .collapsed-heartbeats {{ background: #0a1628; }}
        .full-timeline-toggle {{ margin-top: 16px; }}

        details > summary {{ cursor: pointer; color: #5dade2; }}
        details > summary:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    {header}
    {layer1}
    {layer2}
    {layer3}
</body>
</html>"""

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def _format_duration(td: timedelta) -> str:
        total_seconds = int(td.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        remaining_min = minutes % 60
        return f"{hours}h {remaining_min}m"
