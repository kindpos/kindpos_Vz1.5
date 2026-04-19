import asyncio
import aiosqlite
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("kindpos.printing.queue")

class PrintJobQueue:
    """
    Local SQLite-based print job queue.
    Guarantees no order is lost regardless of printer status.
    """

    def __init__(self, db_path: str = "./data/print_queue.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Initialize the print queue database and schema."""
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS print_queue (
                job_id          TEXT PRIMARY KEY,
                order_id        TEXT NOT NULL,
                template_id     TEXT NOT NULL,
                printer_mac     TEXT NOT NULL,
                copy_type       TEXT,
                ticket_number   TEXT NOT NULL,
                context_json    TEXT NOT NULL,
                status          TEXT NOT NULL,   -- queued | sent | completed | failed
                attempt_count   INTEGER DEFAULT 0,
                last_attempt_at TEXT,
                created_at      TEXT NOT NULL,
                completed_at    TEXT
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def enqueue(self, order_id: str, template_id: str, printer_mac: str, 
                      ticket_number: str, context: Dict[str, Any], 
                      copy_type: Optional[str] = None) -> str:
        """Add a new job to the queue."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        await self._db.execute("""
            INSERT INTO print_queue (
                job_id, order_id, template_id, printer_mac, 
                copy_type, ticket_number, context_json, status, 
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id, order_id, template_id, printer_mac, 
            copy_type, ticket_number, json.dumps(context), 'queued', 
            now
        ))
        await self._db.commit()
        return job_id

    async def mark_sent(self, job_id: str, attempt_number: int):
        """Mark a job as currently being sent."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("""
            UPDATE print_queue 
            SET status = 'sent', 
                attempt_count = ?, 
                last_attempt_at = ? 
            WHERE job_id = ?
        """, (attempt_number, now, job_id))
        await self._db.commit()

    async def mark_completed(self, job_id: str):
        """Mark a job as successfully printed."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("""
            UPDATE print_queue 
            SET status = 'completed', 
                completed_at = ? 
            WHERE job_id = ?
        """, (now, job_id))
        await self._db.commit()

    async def mark_failed(self, job_id: str):
        """Mark a job as failed after retry threshold."""
        await self._db.execute("""
            UPDATE print_queue 
            SET status = 'failed' 
            WHERE job_id = ?
        """, (job_id,))
        await self._db.commit()

    async def get_pending_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs that are 'queued' or 'sent' (but not yet 'completed' or 'failed')."""
        async with self._db.execute(
            "SELECT * FROM print_queue WHERE status IN ('queued', 'sent') ORDER BY created_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(zip([col[0] for col in cursor.description], row)) for row in rows]

    async def get_failed_jobs(self) -> List[Dict[str, Any]]:
        """Get all 'failed' jobs for manual retry or display."""
        async with self._db.execute(
            "SELECT * FROM print_queue WHERE status = 'failed' ORDER BY created_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(zip([col[0] for col in cursor.description], row)) for row in rows]

    async def reset_for_retry(self, job_id: str):
        """Reset a failed job back to 'queued' for manual retry."""
        await self._db.execute("""
            UPDATE print_queue 
            SET status = 'queued', 
                attempt_count = 0 
            WHERE job_id = ?
        """, (job_id,))
        await self._db.commit()

    async def dismiss_job(self, job_id: str):
        """Remove or mark a job as dismissed (deleting for simplicity here)."""
        await self._db.execute("DELETE FROM print_queue WHERE job_id = ?", (job_id,))
        await self._db.commit()
