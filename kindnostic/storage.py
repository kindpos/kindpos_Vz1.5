"""KINDnostic boot storage — SQLite persistence for diagnostic results."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_BOOT_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS boot_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    probe_name  TEXT NOT NULL,
    category    TEXT NOT NULL,
    status      TEXT NOT NULL,
    duration_ms INTEGER,
    message     TEXT,
    metadata    TEXT
)
"""

_BOOT_SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS boot_summary (
    boot_id         TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    total_probes    INTEGER,
    passed          INTEGER,
    warned          INTEGER,
    failed          INTEGER,
    duration_ms     INTEGER,
    outcome         TEXT NOT NULL,
    override_by     TEXT
)
"""


class BootStorage:
    """Synchronous SQLite storage for KINDnostic boot diagnostics."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_BOOT_RESULTS_SCHEMA)
        self._conn.execute(_BOOT_SUMMARY_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "BootStorage":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def record_result(
        self,
        boot_id: str,
        probe_name: str,
        category: str,
        status: str,
        duration_ms: int,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Insert a single probe result."""
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO boot_results
               (boot_id, timestamp, probe_name, category, status,
                duration_ms, message, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                boot_id,
                datetime.now(timezone.utc).isoformat(),
                probe_name,
                category,
                status,
                duration_ms,
                message,
                json.dumps(metadata) if metadata else None,
            ),
        )
        self._conn.commit()

    def record_summary(
        self,
        boot_id: str,
        total_probes: int,
        passed: int,
        warned: int,
        failed: int,
        duration_ms: int,
        outcome: str,
    ) -> None:
        """Insert a boot summary row."""
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO boot_summary
               (boot_id, timestamp, total_probes, passed, warned,
                failed, duration_ms, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                boot_id,
                datetime.now(timezone.utc).isoformat(),
                total_probes,
                passed,
                warned,
                failed,
                duration_ms,
                outcome,
            ),
        )
        self._conn.commit()

    def get_last_boot_summary(self) -> Optional[dict]:
        """Return the most recent boot summary as a dict, or None."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM boot_summary ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_boot_history(self, n: int = 10) -> list[dict]:
        """Return the last N boot summaries, most recent first."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM boot_summary ORDER BY timestamp DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_probe_trend(self, probe_name: str, n: int = 20) -> list[dict]:
        """Return pass/fail history for a specific probe across the last N boots."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT boot_id, timestamp, status, duration_ms, message
               FROM boot_results
               WHERE probe_name = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (probe_name, n),
        ).fetchall()
        return [dict(row) for row in rows]
