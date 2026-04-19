#!/usr/bin/env python3
"""
KINDpos Busy Day Bombard Simulation — Main Runner

Usage:
    cd backend
    python -m bombard.run_bombard
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure backend is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.event_ledger import EventLedger
from bombard.simulation_engine import SimulationEngine
from bombard.validators import (
    validate_ledger_integrity,
    validate_financial_reconciliation,
    compute_performance_metrics,
    validate_menu_projection,
    validate_server_snapshot,
    validate_close_day,
    validate_entomology,
    validate_edge_cases,
    compute_event_statistics,
    build_summary_table,
)

# ─── Paths ──────────────────────────────────────────────────
BOMBARD_DB = Path("./data/bombard_ledger.db")
DIAG_DB = Path("./data/bombard_diagnostic.db")
REPORT_PATH = Path("./data/bombard_report.txt")


def print_section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def print_checks(result: dict):
    """Print individual check results."""
    for check in result.get("checks", []):
        icon = "PASS" if check.get("passed", True) else "FAIL"
        print(f"    [{icon}] {check['name']}: {check.get('detail', '')}")


async def main():
    # Clean up previous run
    for db in [BOMBARD_DB, DIAG_DB]:
        if db.exists():
            os.remove(db)

    all_results = []
    report_lines = []

    def log(msg):
        print(msg)
        report_lines.append(msg)

    log("=" * 70)
    log("KINDpos BUSY DAY BOMBARD SIMULATION")
    log("=" * 70)
    log("")

    # ─── Run Simulation ─────────────────────────────────────
    async with EventLedger(str(BOMBARD_DB)) as ledger:
        engine = SimulationEngine(ledger)
        metrics = await engine.run()

        # ─── Section 1: Ledger Integrity ────────────────────
        print_section("1. Ledger Integrity")
        r1 = await validate_ledger_integrity(ledger)
        print_checks(r1)
        log(f"\n  Section 1 — Ledger Integrity: {r1['result']}")
        all_results.append(r1)

        # ─── Section 2: Financial Reconciliation ────────────
        print_section("2. Financial Reconciliation")
        r2 = await validate_financial_reconciliation(ledger, engine)
        print_checks(r2)
        if "financial_summary" in r2:
            fs = r2["financial_summary"]
            print(f"\n    Financial Summary:")
            print(f"      Gross Sales:     ${fs['gross_sales']}")
            print(f"      Discounts/Comps: ${fs['discounts_comps']}")
            print(f"      Voids:           ${fs['voids']}")
            print(f"      Net Sales:       ${fs['net_sales']}")
            print(f"      Tax:             ${fs['tax']}")
            print(f"      Tips:            ${fs['total_tips']}")
            print(f"      Card Payments:   ${fs['card_payments']}")
            print(f"      Cash Payments:   ${fs['cash_payments']}")
            print(f"      Closed Orders:   {fs['closed_orders']}")
            print(f"      Voided Orders:   {fs['voided_orders']}")
        log(f"\n  Section 2 — Financial Reconciliation: {r2['result']}")
        all_results.append(r2)

        # ─── Section 3: Performance Metrics ─────────────────
        print_section("3. Performance Metrics")
        r3 = compute_performance_metrics(metrics)
        pm = r3["metrics"]
        print(f"    Wall clock:        {pm['wall_clock_s']}s")
        print(f"    Total events:      {pm['total_events']}")
        print(f"    Events/sec:        {pm['events_per_sec']}")
        print(f"    Avg write:         {pm['avg_write_ms']}ms")
        print(f"    P95 write:         {pm['p95_write_ms']}ms")
        print(f"    Max write:         {pm['max_write_ms']}ms")
        print(f"    Avg events/check:  {pm['avg_events_per_check']}")
        if r3["warnings"]:
            for w in r3["warnings"]:
                print(f"    WARNING: {w}")
        log(f"\n  Section 3 — Performance: {pm['events_per_sec']} events/sec, {pm['wall_clock_s']}s total")
        all_results.append(r3)

        # ─── Section 4: Menu Projection ─────────────────────
        print_section("4. Menu Projection Stress Test")
        r4 = await validate_menu_projection(ledger, engine)
        print_checks(r4)
        log(f"\n  Section 4 — Menu Projection: {r4['result']}")
        all_results.append(r4)

        # ─── Section 5: Server Snapshot ─────────────────────
        print_section("5. Server Snapshot Validation")
        r5 = await validate_server_snapshot(ledger, engine)
        print_checks(r5)
        log(f"\n  Section 5 — Server Snapshot: {r5['result']}")
        all_results.append(r5)

        # ─── Section 6: Close Day ───────────────────────────
        print_section("6. Close Day Execution")
        r6 = await validate_close_day(ledger)
        print_checks(r6)
        log(f"\n  Section 6 — Close Day: {r6['result']}")
        all_results.append(r6)

    # ─── Section 7: Entomology (uses own DB) ────────────────
    print_section("7. Entomology System Validation")
    r7 = await validate_entomology(str(DIAG_DB))
    print_checks(r7)
    log(f"\n  Section 7 — Entomology: {r7['result']}")
    if r7.get("report_path"):
        log(f"    Entomology report saved: {r7['report_path']}")
    all_results.append(r7)

    # ─── Section 8: Edge Cases ──────────────────────────────
    print_section("8. Edge Case Verification")
    r8 = validate_edge_cases(engine)
    print_checks(r8)
    log(f"\n  Section 8 — Edge Cases: {r8['result']} ({r8.get('summary', '')})")
    all_results.append(r8)

    # ─── Section 9: Event Statistics ────────────────────────
    print_section("9. Event Ledger Statistics")
    async with EventLedger(str(BOMBARD_DB)) as ledger2:
        r9 = await compute_event_statistics(ledger2, engine)
    stats = r9["stats"]
    print(f"    Total events: {stats['total_events']}")
    print(f"    Avg events/check: {stats['avg_events_per_check']}")
    print(f"\n    Top 10 event types:")
    for etype, count in stats["top10_types"]:
        print(f"      {etype:<35} {count:>5}")
    print(f"\n    Events per hour:")
    for hour, count in sorted(stats["events_per_hour"].items()):
        bar = "#" * (count // 20)
        print(f"      {hour:02d}:00  {count:>5}  {bar}")
    print(f"\n    Distribution:")
    for k, v in stats["distribution"].items():
        print(f"      {k:<20} {v}")
    log(f"\n  Section 9 — Statistics: {stats['total_events']} total events")
    all_results.append(r9)

    # ─── Section 10: Summary Table ──────────────────────────
    summary = build_summary_table(all_results)
    print(summary)
    report_lines.append(summary)

    # ─── Save Report ────────────────────────────────────────
    full_report = "\n".join(report_lines)
    with open(REPORT_PATH, "w") as f:
        f.write(full_report)
    print(f"\nFull report saved to: {REPORT_PATH}")

    # ─── Save detailed JSON results ─────────────────────────
    json_path = Path("./data/bombard_results.json")
    # Make results JSON-serializable
    serializable = []
    for r in all_results:
        sr = {}
        for k, v in r.items():
            try:
                json.dumps(v)
                sr[k] = v
            except (TypeError, ValueError):
                sr[k] = str(v)
        serializable.append(sr)
    with open(json_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"Detailed JSON results saved to: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
