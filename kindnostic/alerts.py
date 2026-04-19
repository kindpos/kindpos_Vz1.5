"""KINDnostic alert queue — stores alerts locally, sends when network is available."""

import json
import os
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kindnostic.support_codes import generate_support_code
from kindnostic.types import ProbeResult, Status

_DEFAULT_ALERT_DB_PATH = "./data/diagnostic_boot.db"

_ALERT_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    boot_id     TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    severity    TEXT NOT NULL,
    summary     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0,
    sent_at     TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0
)
"""


class AlertQueue:
    """Queue alerts locally, flush when network is available."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.environ.get(
            "KINDPOS_DIAG_DB_PATH", _DEFAULT_ALERT_DB_PATH
        )
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_ALERT_QUEUE_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AlertQueue":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def enqueue(
        self,
        boot_id: str,
        terminal_id: str,
        results: list[tuple[ProbeResult, int]],
    ) -> Optional[int]:
        """Enqueue an alert if any CRITICAL or HIGH probes failed/warned.

        Returns the alert row id if enqueued, None if no alert needed.
        """
        assert self._conn is not None

        actionable = [
            (r, ms) for r, ms in results
            if r.status in (Status.FAIL, Status.WARN)
        ]
        if not actionable:
            return None

        # Determine severity
        has_critical = any(r.status == Status.FAIL and r.category.value == "CRITICAL"
                          for r, _ in actionable)
        severity = "CRITICAL" if has_critical else "WARNING"

        failure_details = []
        for r, ms in actionable:
            failure_details.append({
                "probe": r.probe_name,
                "category": r.category.value,
                "status": r.status.value,
                "message": r.message,
                "support_code": generate_support_code(r.probe_name),
                "duration_ms": ms,
            })

        summary_parts = [f"{d['support_code']}: {d['probe']}" for d in failure_details]
        summary = f"KINDnostic {severity} — {', '.join(summary_parts)}"

        payload = {
            "boot_id": boot_id,
            "terminal_id": terminal_id,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "failures": failure_details,
            "total_probes": len(results),
        }

        cursor = self._conn.execute(
            """INSERT INTO alert_queue
               (created_at, boot_id, terminal_id, severity, summary, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                boot_id,
                terminal_id,
                severity,
                summary,
                json.dumps(payload),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_unsent(self, limit: int = 50) -> list[dict]:
        """Return unsent alerts, oldest first."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM alert_queue WHERE sent = 0 ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_sent(self, alert_id: int) -> None:
        """Mark an alert as successfully sent."""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE alert_queue SET sent = 1, sent_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), alert_id),
        )
        self._conn.commit()

    def increment_attempts(self, alert_id: int) -> None:
        """Increment the attempt counter for a failed send."""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE alert_queue SET attempts = attempts + 1 WHERE id = ?",
            (alert_id,),
        )
        self._conn.commit()

    def flush(self, webhook_url: Optional[str] = None) -> int:
        """Attempt to send all unsent alerts via HTTP POST.

        Returns the number of alerts successfully sent.
        """
        if webhook_url is None:
            webhook_url = os.environ.get("KINDPOS_ALERT_WEBHOOK")
        if not webhook_url:
            return 0

        unsent = self.get_unsent()
        sent_count = 0

        for alert in unsent:
            try:
                data = json.dumps({
                    "id": alert["id"],
                    "terminal_id": alert["terminal_id"],
                    "severity": alert["severity"],
                    "summary": alert["summary"],
                    "payload": json.loads(alert["payload"]),
                }).encode("utf-8")

                req = urllib.request.Request(
                    webhook_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status < 300:
                        self.mark_sent(alert["id"])
                        sent_count += 1
                    else:
                        self.increment_attempts(alert["id"])
            except (urllib.error.URLError, OSError):
                self.increment_attempts(alert["id"])

        return sent_count
