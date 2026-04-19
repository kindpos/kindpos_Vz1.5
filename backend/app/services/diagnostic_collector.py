"""
KINDpos Diagnostic Collector

Centralized write path for all diagnostic events.
No component writes directly to the diagnostic table — all writes
go through this collector, which handles hash chaining, SQLite writes,
and timestamp management.

Follows the same singleton service pattern as EventLedger.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

from app.models.diagnostic_event import (
    DEFAULT_RETENTION_DAYS,
    GENESIS_HASH,
    DiagnosticCategory,
    DiagnosticEvent,
    DiagnosticSeverity,
    compute_diagnostic_hash,
)

logger = logging.getLogger("kindpos.diagnostic_collector")

# Heartbeat intervals
ACTIVE_HEARTBEAT_INTERVAL_S = 60
OFF_HOURS_HEARTBEAT_INTERVAL_S = 900  # 15 minutes
COOLDOWN_MINUTES = 30
REVERSE_CORRELATION_WINDOW_MINUTES = 5


class DiagnosticCollector:
    """
    Singleton service that collects, hash-chains, and stores diagnostic events.

    Usage:
        async with DiagnosticCollector(db_path, terminal_id) as collector:
            event = await collector.record(
                category=DiagnosticCategory.DEVICE,
                severity=DiagnosticSeverity.ERROR,
                source="DejavooSPInAdapter",
                event_code="DEV-001",
                message="Payment terminal unreachable",
                context={"device_ip": "10.0.0.100", ...}
            )
    """

    def __init__(self, db_path: str, terminal_id: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.terminal_id = terminal_id
        self._db: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

        # Adaptive heartbeat state
        self._service_active: bool = False
        self._cooldown_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Reference to EventLedger for open orders check (set after init)
        self._event_ledger = None

    async def connect(self) -> None:
        """Open database connection and initialize diagnostic_events table."""
        self._db = await aiosqlite.connect(str(self.db_path))

        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=10000")
        await self._db.execute("PRAGMA mmap_size=268435456")      # 256MB memory-mapped I/O
        await self._db.execute("PRAGMA journal_size_limit=67108864")  # 64MB WAL size cap
        await self._db.execute("PRAGMA temp_store=MEMORY")

        await self._db.execute("""
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

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_diag_timestamp
            ON diagnostic_events(timestamp)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_diag_category
            ON diagnostic_events(category)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_diag_severity
            ON diagnostic_events(severity)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_diag_event_code
            ON diagnostic_events(event_code)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_diag_correlation
            ON diagnostic_events(correlation_id)
        """)

        await self._db.commit()

    async def close(self) -> None:
        """Cancel background tasks and close database connection."""
        self._shutdown_event.set()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            try:
                await self._cooldown_task
            except asyncio.CancelledError:
                pass
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "DiagnosticCollector":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def set_event_ledger(self, ledger) -> None:
        """Set reference to EventLedger for open orders checking."""
        self._event_ledger = ledger

    # =========================================================================
    # CORE RECORDING
    # =========================================================================

    async def record(
        self,
        category: DiagnosticCategory,
        severity: DiagnosticSeverity,
        source: str,
        event_code: str,
        message: str,
        context: dict,
        correlation_id: Optional[str] = None,
    ) -> DiagnosticEvent:
        """
        Record a diagnostic event. This is the only public write interface.

        Components call this method; the collector handles UUID generation,
        timestamping, hash chaining, and SQLite persistence.
        """
        diagnostic_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        timestamp_str = timestamp.isoformat()

        async with self._write_lock:
            # Get previous hash
            cursor = await self._db.execute(
                "SELECT hash FROM diagnostic_events ORDER BY id DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            prev_hash = row[0] if row else GENESIS_HASH

            # Compute hash
            hash_value = compute_diagnostic_hash(
                prev_hash=prev_hash,
                diagnostic_id=diagnostic_id,
                timestamp=timestamp_str,
                category=category.value,
                severity=severity.value,
                source=source,
                event_code=event_code,
                message=message,
                context=context,
            )

            # Insert
            await self._db.execute(
                """
                INSERT INTO diagnostic_events (
                    diagnostic_id, correlation_id, terminal_id, timestamp,
                    category, severity, source, event_code, message,
                    context, prev_hash, hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnostic_id,
                    correlation_id,
                    self.terminal_id,
                    timestamp_str,
                    category.value,
                    severity.value,
                    source,
                    event_code,
                    message,
                    json.dumps(context),
                    prev_hash,
                    hash_value,
                ),
            )
            await self._db.commit()

        return DiagnosticEvent(
            diagnostic_id=diagnostic_id,
            correlation_id=correlation_id,
            terminal_id=self.terminal_id,
            timestamp=timestamp,
            category=category,
            severity=severity,
            source=source,
            event_code=event_code,
            message=message,
            context=context,
            prev_hash=prev_hash,
            hash=hash_value,
        )

    # =========================================================================
    # QUERY OPERATIONS
    # =========================================================================

    def _row_to_event(self, row: tuple) -> DiagnosticEvent:
        """Convert a database row to a DiagnosticEvent."""
        return DiagnosticEvent(
            diagnostic_id=row[0],
            correlation_id=row[1],
            terminal_id=row[2],
            timestamp=datetime.fromisoformat(row[3]),
            category=DiagnosticCategory(row[4]),
            severity=DiagnosticSeverity(row[5]),
            source=row[6],
            event_code=row[7],
            message=row[8],
            context=json.loads(row[9]),
            prev_hash=row[10],
            hash=row[11],
        )

    async def get_events(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        category: Optional[DiagnosticCategory] = None,
        severity: Optional[DiagnosticSeverity] = None,
        event_code: Optional[str] = None,
        correlation_id: Optional[str] = None,
        limit: int = 10000,
    ) -> list[DiagnosticEvent]:
        """Flexible query for diagnostic events."""
        conditions = []
        params = []

        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())
        if category:
            conditions.append("category = ?")
            params.append(category.value)
        if severity:
            conditions.append("severity = ?")
            params.append(severity.value)
        if event_code:
            conditions.append("event_code = ?")
            params.append(event_code)
        if correlation_id:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor = await self._db.execute(
            f"""
            SELECT diagnostic_id, correlation_id, terminal_id, timestamp,
                   category, severity, source, event_code, message,
                   context, prev_hash, hash
            FROM diagnostic_events
            WHERE {where}
            ORDER BY id ASC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_events_by_severity_min(
        self,
        min_severity: DiagnosticSeverity,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 10000,
    ) -> list[DiagnosticEvent]:
        """Get events at or above a minimum severity level."""
        severity_values = []
        for sev in DiagnosticSeverity:
            if sev >= min_severity:
                severity_values.append(sev.value)

        placeholders = ",".join("?" for _ in severity_values)
        conditions = [f"severity IN ({placeholders})"]
        params = list(severity_values)

        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())

        where = " AND ".join(conditions)
        params.append(limit)

        cursor = await self._db.execute(
            f"""
            SELECT diagnostic_id, correlation_id, terminal_id, timestamp,
                   category, severity, source, event_code, message,
                   context, prev_hash, hash
            FROM diagnostic_events
            WHERE {where}
            ORDER BY id ASC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_all_events_ordered(self) -> list[DiagnosticEvent]:
        """Get all events ordered by id for hash chain verification."""
        cursor = await self._db.execute(
            """
            SELECT diagnostic_id, correlation_id, terminal_id, timestamp,
                   category, severity, source, event_code, message,
                   context, prev_hash, hash
            FROM diagnostic_events
            ORDER BY id ASC
            """
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def count_events(self) -> int:
        """Get total diagnostic event count."""
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM diagnostic_events"
        )
        row = await cursor.fetchone()
        return row[0]

    # =========================================================================
    # REVERSE CORRELATION
    # =========================================================================

    async def reverse_correlate(
        self,
        device_identifier: str,
        correlation_id: str,
        minutes_back: int = REVERSE_CORRELATION_WINDOW_MINUTES,
    ) -> int:
        """
        Look back at recent diagnostic events for a device and link them
        to a correlation_id if they don't already have one.

        Returns the number of events updated.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=minutes_back)
        ).isoformat()

        async with self._write_lock:
            cursor = await self._db.execute(
                """
                SELECT id, context FROM diagnostic_events
                WHERE correlation_id IS NULL
                  AND timestamp >= ?
                ORDER BY id ASC
                """,
                (cutoff,),
            )
            rows = await cursor.fetchall()

            updated = 0
            for row_id, context_str in rows:
                ctx = json.loads(context_str)
                # Check if device identifier appears in context values
                ctx_str = json.dumps(ctx)
                if device_identifier in ctx_str:
                    await self._db.execute(
                        "UPDATE diagnostic_events SET correlation_id = ? WHERE id = ?",
                        (correlation_id, row_id),
                    )
                    updated += 1

            if updated:
                await self._db.commit()

        return updated

    async def update_correlation_id(
        self, diagnostic_id: str, correlation_id: str
    ) -> bool:
        """Update the correlation_id of a specific diagnostic event."""
        async with self._write_lock:
            cursor = await self._db.execute(
                """
                UPDATE diagnostic_events
                SET correlation_id = ?
                WHERE diagnostic_id = ? AND correlation_id IS NULL
                """,
                (correlation_id, diagnostic_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # ADAPTIVE HEARTBEAT
    # =========================================================================

    def start_heartbeat_loop(self) -> asyncio.Task:
        """Start the adaptive heartbeat background task. Returns the task."""
        self._shutdown_event.clear()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self._heartbeat_task

    async def _heartbeat_loop(self) -> None:
        """Main heartbeat loop with adaptive interval."""
        while not self._shutdown_event.is_set():
            interval = (
                ACTIVE_HEARTBEAT_INTERVAL_S
                if self._service_active
                else OFF_HOURS_HEARTBEAT_INTERVAL_S
            )
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=interval
                )
                # If we get here, shutdown was requested
                break
            except asyncio.TimeoutError:
                # Interval elapsed — collect heartbeat
                pass

            try:
                await self._collect_heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat collection failed: {e}")

    async def _collect_heartbeat(self) -> None:
        """Gather system metrics and record a SYS-HEARTBEAT event."""
        context = {
            "peripherals": {},
            "system": self._collect_system_metrics(),
            "network": {"gateway_reachable": True, "gateway_latency_ms": 0.0},
        }

        await self.record(
            category=DiagnosticCategory.SYSTEM,
            severity=DiagnosticSeverity.INFO,
            source="DiagnosticCollector",
            event_code="SYS-HEARTBEAT",
            message="Ambient health snapshot",
            context=context,
        )

    def _collect_system_metrics(self) -> dict:
        """Collect system-level metrics (memory, disk, CPU temp, uptime)."""
        metrics = {
            "memory_used_pct": 0.0,
            "disk_used_pct": 0.0,
            "cpu_temp_c": 0.0,
            "uptime_hours": 0.0,
        }

        if not _PSUTIL_AVAILABLE:
            logger.warning("psutil not available — system metrics will be zeros")
            return metrics

        try:
            mem = psutil.virtual_memory()
            metrics["memory_used_pct"] = round(mem.percent, 1)

            disk = psutil.disk_usage("/")
            metrics["disk_used_pct"] = round(
                (disk.used / disk.total) * 100, 1
            )

            # CPU temperature — psutil first, fallback to sysfs (Pi 5)
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        metrics["cpu_temp_c"] = round(entries[0].current, 1)
                        break
            else:
                thermal_path = "/sys/class/thermal/thermal_zone0/temp"
                if os.path.exists(thermal_path):
                    with open(thermal_path) as f:
                        metrics["cpu_temp_c"] = round(
                            int(f.read().strip()) / 1000.0, 1
                        )

            # Uptime
            boot_time = datetime.fromtimestamp(
                psutil.boot_time(), tz=timezone.utc
            )
            uptime = datetime.now(timezone.utc) - boot_time
            metrics["uptime_hours"] = round(
                uptime.total_seconds() / 3600, 1
            )
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")

        return metrics

    async def notify_order_created(self) -> None:
        """Called when an ORDER_CREATED event fires. Activates service mode."""
        self._service_active = True
        # Cancel any pending cooldown
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            try:
                await self._cooldown_task
            except asyncio.CancelledError:
                pass
        # Start fresh cooldown
        self._cooldown_task = asyncio.create_task(self._cooldown_timer())

    async def _cooldown_timer(self) -> None:
        """Wait 30 minutes, then check if we can switch to off-hours."""
        try:
            await asyncio.sleep(COOLDOWN_MINUTES * 60)
        except asyncio.CancelledError:
            return

        # Check for open orders
        if self._event_ledger:
            try:
                from app.core.event_ledger import get_open_orders

                open_orders = await get_open_orders(self._event_ledger)
                if open_orders:
                    # Still have open orders — restart cooldown
                    self._cooldown_task = asyncio.create_task(
                        self._cooldown_timer()
                    )
                    return
            except Exception as e:
                logger.error(f"Error checking open orders: {e}")

        self._service_active = False

    # =========================================================================
    # RETENTION
    # =========================================================================

    async def run_retention(
        self,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        site_name: str = "KINDpos",
        archive_dir: str = "./data",
    ) -> Optional[str]:
        """
        Export events older than retention window to JSON archive,
        then delete them from the active table.

        Returns the archive file path if events were exported, None otherwise.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()

        cursor = await self._db.execute(
            """
            SELECT diagnostic_id, correlation_id, terminal_id, timestamp,
                   category, severity, source, event_code, message,
                   context, prev_hash, hash
            FROM diagnostic_events
            WHERE timestamp < ?
            ORDER BY id ASC
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()

        if not rows:
            return None

        # Build archive
        archive_data = []
        for row in rows:
            event = self._row_to_event(row)
            archive_data.append({
                "diagnostic_id": event.diagnostic_id,
                "correlation_id": event.correlation_id,
                "terminal_id": event.terminal_id,
                "timestamp": event.timestamp.isoformat(),
                "category": event.category.value,
                "severity": event.severity.value,
                "source": event.source,
                "event_code": event.event_code,
                "message": event.message,
                "context": event.context,
                "prev_hash": event.prev_hash,
                "hash": event.hash,
            })

        # Write archive file
        archive_path = Path(archive_dir)
        archive_path.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{site_name}_diag_archive_{date_str}.json"
        filepath = archive_path / filename

        with open(filepath, "w") as f:
            json.dump(archive_data, f, indent=2)

        # Delete archived events
        async with self._write_lock:
            await self._db.execute(
                "DELETE FROM diagnostic_events WHERE timestamp < ?",
                (cutoff,),
            )
            await self._db.commit()

        logger.info(
            f"Retention: archived {len(archive_data)} events to {filepath}"
        )
        return str(filepath)

    # =========================================================================
    # SCHEMA INTROSPECTION (for testing)
    # =========================================================================

    async def table_exists(self) -> bool:
        """Check if the diagnostic_events table exists."""
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='diagnostic_events'"
        )
        return await cursor.fetchone() is not None

    async def get_indexes(self) -> list[str]:
        """Get all index names for the diagnostic_events table."""
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='diagnostic_events'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
