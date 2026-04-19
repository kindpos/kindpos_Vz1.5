"""KINDnostic Entomology integration — writes BOOT_DIAGNOSTIC events to diagnostic_events."""

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kindnostic.types import ProbeResult, Status

# Must match backend/app/models/diagnostic_event.py
GENESIS_HASH = "KIND_DIAGNOSTIC_GENESIS"
_DEFAULT_DIAG_DB_PATH = "./data/diagnostic_boot.db"


def _compute_diagnostic_hash(
    prev_hash: str,
    diagnostic_id: str,
    timestamp: str,
    category: str,
    severity: str,
    source: str,
    event_code: str,
    message: str,
    context: dict,
) -> str:
    """Replicate Entomology's hash computation for chain compatibility."""
    data = (
        prev_hash
        + diagnostic_id
        + timestamp
        + category
        + severity
        + source
        + event_code
        + message
        + json.dumps(context, sort_keys=True)
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _ensure_diagnostic_table(conn: sqlite3.Connection) -> None:
    """Create diagnostic_events table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS diagnostic_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            diagnostic_id   TEXT NOT NULL UNIQUE,
            correlation_id  TEXT,
            terminal_id     TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            category        TEXT NOT NULL,
            severity        TEXT NOT NULL,
            source          TEXT NOT NULL,
            event_code      TEXT NOT NULL,
            message         TEXT NOT NULL,
            context         TEXT NOT NULL,
            prev_hash       TEXT NOT NULL,
            hash            TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_diag_timestamp
        ON diagnostic_events(timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_diag_event_code
        ON diagnostic_events(event_code)
    """)
    conn.commit()


def write_boot_diagnostic(
    boot_id: str,
    outcome: str,
    results: list[tuple[ProbeResult, int]],
    total_duration_ms: int,
    terminal_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Write a BOOT_DIAGNOSTIC event to Entomology's diagnostic_events table.

    Returns the diagnostic_id of the written event.
    """
    if db_path is None:
        db_path = os.environ.get("KINDPOS_DIAG_DB_PATH", _DEFAULT_DIAG_DB_PATH)
    if terminal_id is None:
        terminal_id = os.environ.get("KINDPOS_TERMINAL_ID", "terminal_01")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        _ensure_diagnostic_table(conn)

        diagnostic_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Determine severity from outcome
        if outcome == "BLOCKED":
            severity = "CRITICAL"
        elif any(r.status == Status.WARN for r, _ in results):
            severity = "WARNING"
        else:
            severity = "INFO"

        failures = [
            {"probe": r.probe_name, "status": r.status.value, "message": r.message}
            for r, _ in results
            if r.status != Status.PASS
        ]

        context = {
            "boot_id": boot_id,
            "outcome": outcome,
            "total_probes": len(results),
            "passed": sum(1 for r, _ in results if r.status == Status.PASS),
            "warned": sum(1 for r, _ in results if r.status == Status.WARN),
            "failed": sum(1 for r, _ in results if r.status == Status.FAIL),
            "failures": failures,
            "duration_ms": total_duration_ms,
        }

        # Get previous hash for chain
        row = conn.execute(
            "SELECT hash FROM diagnostic_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = row[0] if row else GENESIS_HASH

        hash_value = _compute_diagnostic_hash(
            prev_hash=prev_hash,
            diagnostic_id=diagnostic_id,
            timestamp=timestamp,
            category="SYSTEM",
            severity=severity,
            source="KINDnostic",
            event_code="SYS-BOOT-DIAG",
            message=f"Boot diagnostic: {outcome}",
            context=context,
        )

        conn.execute(
            """INSERT INTO diagnostic_events
               (diagnostic_id, correlation_id, terminal_id, timestamp,
                category, severity, source, event_code, message,
                context, prev_hash, hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                diagnostic_id,
                boot_id,  # correlation_id = boot_id for traceability
                terminal_id,
                timestamp,
                "SYSTEM",
                severity,
                "KINDnostic",
                "SYS-BOOT-DIAG",
                f"Boot diagnostic: {outcome}",
                json.dumps(context),
                prev_hash,
                hash_value,
            ),
        )
        conn.commit()
        return diagnostic_id

    finally:
        conn.close()
