"""System probes — entomology heartbeat, network, last boot result, uptime."""

import os
import sqlite3
import subprocess
from datetime import datetime, timezone

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.LOW

_DEFAULT_DIAG_DB_PATH = "./data/diagnostic_boot.db"
_DEFAULT_LEDGER_PATH = "./data/event_ledger.db"


def probe_entomology_heartbeat() -> ProbeResult:
    """Check if the Entomology diagnostic collector has recent activity."""
    # Entomology writes to diagnostic_events table — check for recent entries
    diag_db = os.environ.get("KINDPOS_DIAG_DB_PATH", _DEFAULT_DIAG_DB_PATH)

    if not os.path.exists(diag_db):
        return ProbeResult(
            probe_name="entomology_heartbeat",
            category=Category.LOW,
            status=Status.PASS,
            message="Diagnostic DB not found — Entomology may not be initialized yet",
            metadata={"db_exists": False},
        )

    conn = sqlite3.connect(diag_db)
    try:
        # Check if diagnostic_events table exists (Entomology's table)
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='diagnostic_events'"
        ).fetchone()

        if not table_check:
            return ProbeResult(
                probe_name="entomology_heartbeat",
                category=Category.LOW,
                status=Status.PASS,
                message="No diagnostic_events table — Entomology not yet active",
                metadata={"table_exists": False},
            )

        # Count recent events
        row = conn.execute("SELECT COUNT(*) FROM diagnostic_events").fetchone()
        event_count = row[0] if row else 0

        return ProbeResult(
            probe_name="entomology_heartbeat",
            category=Category.LOW,
            status=Status.PASS,
            message=None,
            metadata={"event_count": event_count, "table_exists": True},
        )
    finally:
        conn.close()


def probe_network_interface() -> ProbeResult:
    """Check if eth0 or wlan0 is up with an IP address."""
    interfaces_found = []

    for iface in ("eth0", "wlan0"):
        iface_path = f"/sys/class/net/{iface}"
        if not os.path.exists(iface_path):
            continue

        try:
            with open(os.path.join(iface_path, "operstate"), "r") as f:
                state = f.read().strip()
        except (FileNotFoundError, PermissionError):
            state = "unknown"

        # Try to get IP address
        ip_addr = None
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", iface],
                capture_output=True, text=True, timeout=2,
            )
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("inet "):
                    ip_addr = line.split()[1].split("/")[0]
                    break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        interfaces_found.append({
            "name": iface,
            "state": state,
            "ip": ip_addr,
        })

    has_ip = any(iface["ip"] for iface in interfaces_found)

    return ProbeResult(
        probe_name="network_interface",
        category=Category.LOW,
        status=Status.PASS,
        message=None if has_ip else "No network interface with IP detected",
        metadata={"interfaces": interfaces_found, "has_ip": has_ip},
    )


def probe_last_boot_result() -> ProbeResult:
    """Query boot_summary for the previous boot outcome."""
    diag_db = os.environ.get("KINDPOS_DIAG_DB_PATH", _DEFAULT_DIAG_DB_PATH)

    if not os.path.exists(diag_db):
        return ProbeResult(
            probe_name="last_boot_result",
            category=Category.LOW,
            status=Status.PASS,
            message="No diagnostic DB — first boot",
            metadata={"previous_boot": None},
        )

    conn = sqlite3.connect(diag_db)
    conn.row_factory = sqlite3.Row
    try:
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='boot_summary'"
        ).fetchone()

        if not table_check:
            return ProbeResult(
                probe_name="last_boot_result",
                category=Category.LOW,
                status=Status.PASS,
                message="No boot_summary table — first boot",
                metadata={"previous_boot": None},
            )

        row = conn.execute(
            "SELECT * FROM boot_summary ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        if not row:
            return ProbeResult(
                probe_name="last_boot_result",
                category=Category.LOW,
                status=Status.PASS,
                message="No previous boot records",
                metadata={"previous_boot": None},
            )

        prev = dict(row)
        had_failures = prev.get("failed", 0) > 0

        return ProbeResult(
            probe_name="last_boot_result",
            category=Category.LOW,
            status=Status.WARN if had_failures else Status.PASS,
            message=f"Previous boot had {prev['failed']} failure(s)" if had_failures else None,
            metadata={"previous_boot": prev},
        )
    finally:
        conn.close()


def probe_uptime_since_last_close() -> ProbeResult:
    """Check time since last DAY_CLOSED event in the event ledger."""
    db_path = os.environ.get("KINDPOS_DB_PATH", _DEFAULT_LEDGER_PATH)

    if not os.path.exists(db_path):
        return ProbeResult(
            probe_name="uptime_since_last_close",
            category=Category.LOW,
            status=Status.PASS,
            message="Event ledger not found — fresh system",
            metadata={"last_close": None},
        )

    conn = sqlite3.connect(db_path)
    try:
        # Check for events table
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()

        if not table_check:
            return ProbeResult(
                probe_name="uptime_since_last_close",
                category=Category.LOW,
                status=Status.PASS,
                message="No events table",
                metadata={"last_close": None},
            )

        row = conn.execute(
            """SELECT timestamp FROM events
               WHERE event_type IN ('DAY_CLOSED', 'day.closed')
               ORDER BY sequence_number DESC LIMIT 1"""
        ).fetchone()

        if not row:
            return ProbeResult(
                probe_name="uptime_since_last_close",
                category=Category.LOW,
                status=Status.PASS,
                message="No DAY_CLOSED events found",
                metadata={"last_close": None},
            )

        last_close_str = row[0]
        try:
            last_close = datetime.fromisoformat(last_close_str)
            now = datetime.now(timezone.utc)
            if last_close.tzinfo is None:
                last_close = last_close.replace(tzinfo=timezone.utc)
            hours_since = (now - last_close).total_seconds() / 3600
        except (ValueError, TypeError):
            hours_since = None

        # Flag if POS was off for more than 48 hours
        is_long = hours_since is not None and hours_since > 48

        return ProbeResult(
            probe_name="uptime_since_last_close",
            category=Category.LOW,
            status=Status.WARN if is_long else Status.PASS,
            message=f"POS off for {hours_since:.1f} hours since last close" if is_long else None,
            metadata={
                "last_close": last_close_str,
                "hours_since_close": round(hours_since, 1) if hours_since else None,
            },
        )
    finally:
        conn.close()
