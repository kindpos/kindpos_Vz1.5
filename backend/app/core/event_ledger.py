"""
KINDpos Event Ledger

The Event Ledger is the source of truth for the entire system.
All state is derived from replaying events stored here.

Key properties:
- Append-only: Events are never modified or deleted
- Hash-chained: Each event includes previous event's hash (tamper detection)
- WAL mode: Concurrent reads/writes without blocking
- Crash-safe: SQLite WAL ensures durability
"""

import asyncio
import aiosqlite
import json
from decimal import Decimal


def _decimal_default(o):
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

import logging
from decimal import Decimal

from .events import Event, EventType, parse_event_type

logger = logging.getLogger("kindpos.ledger")

# Monetary payload keys that must be 2-decimal-place clean
_MONETARY_KEYS = frozenset({
    "price", "amount", "tip_amount", "total", "total_amount",
    "cash_total", "card_total", "modifier_price", "total_sales",
    "total_tips", "previous_tip", "half_price",
})
_TWO_DP = Decimal("0.01")


def _check_monetary_precision(payload: dict) -> list[str]:
    """Return list of keys whose values are not 2dp-clean."""
    failures = []
    for key in _MONETARY_KEYS:
        val = payload.get(key)
        if val is not None and isinstance(val, (int, float)):
            d = Decimal(str(val))
            if d != d.quantize(_TWO_DP):
                failures.append(f"{key}={val}")
    return failures


class EventLedger:
    """
    Async SQLite-based Event Ledger.

    Usage:
        async with EventLedger("./data/ledger.db") as ledger:
            event = await ledger.append(my_event)
            events = await ledger.get_events_for_order(order_id)
    """

    def __init__(self, db_path: str = "./data/event_ledger.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open database connection and initialize schema."""
        self._db = await aiosqlite.connect(str(self.db_path))

        # Enable WAL mode for concurrent access
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=10000")

        # Create events table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                timestamp TEXT NOT NULL,
                terminal_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                user_id TEXT,
                user_role TEXT,
                correlation_id TEXT,
                previous_checksum TEXT,
                checksum TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add idempotency_key column (migration-safe for existing DBs)
        try:
            await self._db.execute(
                "ALTER TABLE events ADD COLUMN idempotency_key TEXT"
            )
        except Exception:
            pass  # Column already exists

        # Indexes for common queries
        await self._db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idempotency
            ON events(idempotency_key) WHERE idempotency_key IS NOT NULL
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_correlation
            ON events(correlation_id)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type 
            ON events(event_type)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp 
            ON events(timestamp)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_synced
            ON events(synced) WHERE synced = 0
        """)

        # Separate sync tracking table — keeps events table immutable
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sync_ledger (
                event_id TEXT PRIMARY KEY,
                synced_at TEXT NOT NULL
            )
        """)

        await self._db.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "EventLedger":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    async def append(self, event: Event) -> Event:
        """
        Append an event to the ledger.

        - Assigns sequence number
        - Computes checksum with hash chain
        - Returns the complete event
        """
        # 2dp precision gate — reject non-2dp monetary values
        if event.payload:
            bad = _check_monetary_precision(event.payload)
            if bad:
                raise ValueError(
                    f"Precision gate: event {event.event_id} ({event.event_type.value}) "
                    f"has non-2dp monetary values: {', '.join(bad)}"
                )

        async with self._write_lock:
            # ── Idempotency gate: reject if key already exists in ledger ──
            if event.idempotency_key:
                cursor = await self._db.execute(
                    "SELECT event_id FROM events WHERE idempotency_key = ?",
                    (event.idempotency_key,)
                )
                existing = await cursor.fetchone()
                if existing:
                    logger.warning(
                        "BLOCKED duplicate event (idempotency_key=%s, existing=%s)",
                        event.idempotency_key, existing[0],
                    )
                    return None  # Caller must handle None as "duplicate blocked"

            # Get previous checksum for hash chain
            cursor = await self._db.execute(
                "SELECT checksum FROM events ORDER BY sequence_number DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            previous_checksum = row[0] if row else ""

            # Compute checksum
            checksum = event.compute_checksum(previous_checksum)

            # Insert event
            await self._db.execute(
                """
                INSERT INTO events (
                    event_id, timestamp, terminal_id, event_type, payload,
                    user_id, user_role, correlation_id, previous_checksum, checksum,
                    idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.timestamp.isoformat(),
                    event.terminal_id,
                    event.event_type.value,
                    json.dumps(event.payload, default=_decimal_default),
                    event.user_id,
                    event.user_role,
                    event.correlation_id,
                    previous_checksum,
                    checksum,
                    event.idempotency_key,
                )
            )

            # Get assigned sequence number
            cursor = await self._db.execute(
                "SELECT sequence_number FROM events WHERE event_id = ?",
                (event.event_id,)
            )
            row = await cursor.fetchone()
            sequence_number = row[0]

            await self._db.commit()

            # Return complete event with sequence number and checksum
            return Event(
                event_id=event.event_id,
                timestamp=event.timestamp,
                terminal_id=event.terminal_id,
                event_type=event.event_type,
                payload=event.payload,
                user_id=event.user_id,
                user_role=event.user_role,
                correlation_id=event.correlation_id,
                idempotency_key=event.idempotency_key,
                sequence_number=sequence_number,
                previous_checksum=previous_checksum,
                checksum=checksum,
            )

    async def append_batch(self, events: list[Event]) -> list[Event]:
        """Append multiple events atomically."""
        # 2dp precision gate — reject non-2dp monetary values
        for event in events:
            if event.payload:
                bad = _check_monetary_precision(event.payload)
                if bad:
                    raise ValueError(
                        f"Precision gate: event {event.event_id} ({event.event_type.value}) "
                        f"has non-2dp monetary values: {', '.join(bad)}"
                    )

        results = []
        async with self._write_lock:
            for event in events:
                # Get previous checksum
                if results:
                    previous_checksum = results[-1].checksum
                else:
                    cursor = await self._db.execute(
                        "SELECT checksum FROM events ORDER BY sequence_number DESC LIMIT 1"
                    )
                    row = await cursor.fetchone()
                    previous_checksum = row[0] if row else ""

                checksum = event.compute_checksum(previous_checksum)

                await self._db.execute(
                    """
                    INSERT INTO events (
                        event_id, timestamp, terminal_id, event_type, payload,
                        user_id, user_role, correlation_id, previous_checksum, checksum,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.timestamp.isoformat(),
                        event.terminal_id,
                        event.event_type.value,
                        json.dumps(event.payload, default=_decimal_default),
                        event.user_id,
                        event.user_role,
                        event.correlation_id,
                        previous_checksum,
                        checksum,
                        event.idempotency_key,
                    )
                )

                cursor = await self._db.execute(
                    "SELECT sequence_number FROM events WHERE event_id = ?",
                    (event.event_id,)
                )
                row = await cursor.fetchone()

                results.append(Event(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    terminal_id=event.terminal_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    user_id=event.user_id,
                    user_role=event.user_role,
                    correlation_id=event.correlation_id,
                    sequence_number=row[0],
                    previous_checksum=previous_checksum,
                    checksum=checksum,
                ))

            await self._db.commit()

        return results

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    def _row_to_event(self, row: tuple) -> Event:
        """Convert a database row to an Event object."""
        return Event(
            sequence_number=row[0],
            event_id=row[1],
            timestamp=datetime.fromisoformat(row[2]),
            terminal_id=row[3],
            event_type=parse_event_type(row[4]),
            payload=json.loads(row[5]),
            user_id=row[6],
            user_role=row[7],
            correlation_id=row[8],
            previous_checksum=row[9],
            checksum=row[10],
            idempotency_key=row[11] if len(row) > 11 else None,
        )

    async def get_event(self, event_id: str) -> Optional[Event]:
        """Get a single event by ID."""
        cursor = await self._db.execute(
            """
            SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                   payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
            FROM events WHERE event_id = ?
            """,
            (event_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_event(row) if row else None

    async def get_events_by_correlation(self, correlation_id: str) -> list[Event]:
        """Get all events with a given correlation ID (e.g., all events for an order)."""
        cursor = await self._db.execute(
            """
            SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                   payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
            FROM events 
            WHERE correlation_id = ?
            ORDER BY sequence_number ASC
            """,
            (correlation_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_events_by_type(
            self,
            event_type: EventType,
            since: Optional[datetime] = None,
            limit: int = 1000
    ) -> list[Event]:
        """Get events of a specific type."""
        if since:
            cursor = await self._db.execute(
                """
                SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                       payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
                FROM events 
                WHERE event_type = ? AND timestamp > ?
                ORDER BY sequence_number ASC
                LIMIT ?
                """,
                (event_type.value, since.isoformat(), limit)
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                       payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
                FROM events 
                WHERE event_type = ?
                ORDER BY sequence_number ASC
                LIMIT ?
                """,
                (event_type.value, limit)
            )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_events_since(
            self,
            sequence_number: int = 0,
            limit: int = 1000
    ) -> list[Event]:
        """Get events since a given sequence number (for sync)."""
        cursor = await self._db.execute(
            """
            SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                   payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
            FROM events 
            WHERE sequence_number > ?
            ORDER BY sequence_number ASC
            LIMIT ?
            """,
            (sequence_number, limit)
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_last_day_close_sequence(self) -> int:
        """Get the sequence number of the most recent DAY_CLOSED event.

        Returns 0 if no day has been closed yet, meaning all events
        are in the 'current day'.
        """
        cursor = await self._db.execute(
            """
            SELECT sequence_number FROM events
            WHERE event_type = 'day.closed'
            ORDER BY sequence_number DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_events_by_date_range(
            self,
            start_date: str,
            end_date: str,
            limit: int = 50000
    ) -> list[Event]:
        """Get events within a date range (YYYY-MM-DD format).

        Returns events whose timestamp falls on or after start_date
        and before end_date.
        """
        cursor = await self._db.execute(
            """
            SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                   payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
            FROM events
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY sequence_number ASC
            LIMIT ?
            """,
            (start_date, end_date, limit)
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_day_close_before_date(self, date_str: str) -> int:
        """Get the sequence number of the DAY_CLOSED event just before a date.

        Returns 0 if no day close exists before that date.
        """
        cursor = await self._db.execute(
            """
            SELECT sequence_number FROM events
            WHERE event_type = 'day.closed' AND timestamp < ?
            ORDER BY sequence_number DESC
            LIMIT 1
            """,
            (date_str,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_unsynced_events(self, limit: int = 100) -> list[Event]:
        """Get events that haven't been synced to cloud.

        Uses the separate sync_ledger table (LEFT JOIN) so that the
        immutable events table is never UPDATEd.
        """
        cursor = await self._db.execute(
            """
            SELECT e.sequence_number, e.event_id, e.timestamp, e.terminal_id, e.event_type,
                   e.payload, e.user_id, e.user_role, e.correlation_id,
                   e.previous_checksum, e.checksum, e.idempotency_key
            FROM events e
            LEFT JOIN sync_ledger s ON e.event_id = s.event_id
            WHERE s.event_id IS NULL
            ORDER BY e.sequence_number ASC
            LIMIT ?
            """,
            (limit,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def mark_synced(self, event_ids: list[str]) -> None:
        """Record sync status in separate sync_ledger table (append-only)."""
        if not event_ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.executemany(
            "INSERT OR IGNORE INTO sync_ledger (event_id, synced_at) VALUES (?, ?)",
            [(eid, now) for eid in event_ids],
        )
        await self._db.commit()

    async def get_latest_sequence(self) -> int:
        """Get the latest sequence number."""
        cursor = await self._db.execute(
            "SELECT MAX(sequence_number) FROM events"
        )
        row = await cursor.fetchone()
        return row[0] or 0

    async def count_events(self) -> int:
        """Get total event count."""
        cursor = await self._db.execute("SELECT COUNT(*) FROM events")
        row = await cursor.fetchone()
        return row[0]

    async def count_events_by_type(self, event_type: EventType) -> int:
        """Get count of events of a specific type."""
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = ?",
            (event_type.value,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def count_events_by_type_and_payload(
        self, event_type: EventType, payload_key: str, payload_value: str
    ) -> int:
        """Get count of events of a specific type where a payload field matches."""
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = ? AND json_extract(payload, ?) = ?",
            (event_type.value, f"$.{payload_key}", payload_value),
        )
        row = await cursor.fetchone()
        return row[0]

    # =========================================================================
    # INTEGRITY VERIFICATION
    # =========================================================================

    async def verify_chain(self, start: int = 0, end: Optional[int] = None) -> tuple[bool, Optional[int]]:
        """
        Verify the hash chain integrity.

        Returns:
            (is_valid, first_invalid_sequence) - If valid, second value is None
        """
        query = """
            SELECT sequence_number, event_id, timestamp, terminal_id, event_type,
                   payload, user_id, user_role, correlation_id, previous_checksum, checksum, idempotency_key
            FROM events 
            WHERE sequence_number > ?
        """
        params = [start]

        if end:
            query += " AND sequence_number <= ?"
            params.append(end)

        query += " ORDER BY sequence_number ASC"

        cursor = await self._db.execute(query, params)

        previous_checksum = ""
        if start > 0:
            # Get the checksum of the event before our range
            prev_cursor = await self._db.execute(
                "SELECT checksum FROM events WHERE sequence_number = ?",
                (start,)
            )
            prev_row = await prev_cursor.fetchone()
            if prev_row:
                previous_checksum = prev_row[0]

        async for row in cursor:
            event = self._row_to_event(row)
            expected_checksum = event.compute_checksum(previous_checksum)

            if event.checksum != expected_checksum:
                return False, event.sequence_number

            if event.previous_checksum != previous_checksum:
                return False, event.sequence_number

            previous_checksum = event.checksum

        return True, None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def get_order_events(ledger: EventLedger, order_id: str) -> list[Event]:
    """Get all events for a specific order."""
    return await ledger.get_events_by_correlation(order_id)


async def get_open_orders(ledger: EventLedger) -> list[str]:
    """Get IDs of orders that are still open (created but not closed/voided).

    Accounts for ORDER_REOPENED: an order that was closed then reopened
    is open again, unless a subsequent close/void exists.

    The correct algorithm tracks the *last* lifecycle event per order
    rather than using simple set subtraction, because reopened orders
    have both CREATED and CLOSED events and would otherwise be missed.
    """
    # Gather all lifecycle events in sequence order
    created_events = await ledger.get_events_by_type(EventType.ORDER_CREATED)
    closed_events = await ledger.get_events_by_type(EventType.ORDER_CLOSED)
    voided_events = await ledger.get_events_by_type(EventType.ORDER_VOIDED)
    reopened_events = await ledger.get_events_by_type(EventType.ORDER_REOPENED)

    # Build a map of order_id → latest lifecycle sequence number + state
    # so that the *last* event wins (handles reopen → close → reopen chains)
    last_state: dict[str, tuple[int, str]] = {}

    for e in created_events:
        oid = e.payload["order_id"]
        seq = e.sequence_number or 0
        prev = last_state.get(oid)
        if prev is None or seq > prev[0]:
            last_state[oid] = (seq, "open")

    for e in closed_events:
        oid = e.payload["order_id"]
        seq = e.sequence_number or 0
        prev = last_state.get(oid)
        if prev is None or seq > prev[0]:
            last_state[oid] = (seq, "closed")

    for e in voided_events:
        oid = e.payload["order_id"]
        seq = e.sequence_number or 0
        prev = last_state.get(oid)
        if prev is None or seq > prev[0]:
            last_state[oid] = (seq, "voided")

    for e in reopened_events:
        oid = e.payload["order_id"]
        seq = e.sequence_number or 0
        prev = last_state.get(oid)
        if prev is None or seq > prev[0]:
            last_state[oid] = (seq, "open")

    return [oid for oid, (_, state) in last_state.items() if state == "open"]
