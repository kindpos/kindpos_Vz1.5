"""
KINDpos Ephemeral Log

A lightweight, non-chained SQLite log for operational telemetry that
does NOT belong in the immutable hash-chained event ledger.

Events here are:
- NOT hash-chained (no SHA-256 checksums)
- NOT synced to the cloud
- Rotatable / purgeable without breaking ledger integrity
- Useful for debugging, ops dashboards, and alerting

Examples: printer status changes, device polling, print retries,
cash drawer kicks, reboot telemetry.
"""

import aiosqlite
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import logging

from .events import Event, EventType

logger = logging.getLogger("kindpos.ephemeral")

# Event types that must be routed here instead of the immutable ledger.
EPHEMERAL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.TICKET_PRINT_FAILED,
    EventType.PRINT_RETRYING,
    EventType.PRINT_REROUTED,
    EventType.PRINTER_STATUS_CHANGED,
    EventType.PRINTER_ERROR,
    EventType.PRINTER_ROLE_CREATED,
    EventType.PRINTER_FALLBACK_ASSIGNED,
    EventType.PRINTER_HEALTH_WARNING,
    EventType.PRINTER_REBOOT_STARTED,
    EventType.PRINTER_REBOOT_COMPLETED,
    EventType.DRAWER_OPENED,
    EventType.DRAWER_OPEN_FAILED,
    EventType.DEVICE_STATUS_CHANGED,
})


class EphemeralLog:
    """
    Non-chained SQLite log for operational telemetry.

    Same append interface as EventLedger so callers can swap easily.
    No hash chain, no precision gate, no sync flag.
    """

    def __init__(self, db_path: str = "./data/ephemeral_log.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open database connection and initialize schema."""
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS ephemeral_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                terminal_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_eph_type
            ON ephemeral_events(event_type)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_eph_timestamp
            ON ephemeral_events(timestamp)
        """)

        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "EphemeralLog":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def append(self, event: Event) -> Event:
        """Write an event to the ephemeral log (no hash chain)."""
        if self._db is None:
            raise RuntimeError("EphemeralLog not connected")

        await self._db.execute(
            """
            INSERT INTO ephemeral_events
                (event_id, timestamp, terminal_id, event_type, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.timestamp.isoformat(),
                event.terminal_id,
                event.event_type.value if isinstance(event.event_type, EventType) else event.event_type,
                json.dumps(event.payload),
            ),
        )
        await self._db.commit()
        logger.debug("ephemeral: %s", event.event_type)
        return event

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete ephemeral events older than *cutoff*. Returns rows deleted."""
        if self._db is None:
            raise RuntimeError("EphemeralLog not connected")
        cursor = await self._db.execute(
            "DELETE FROM ephemeral_events WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )
        await self._db.commit()
        return cursor.rowcount
