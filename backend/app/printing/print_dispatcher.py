"""
KINDpos Print Dispatcher
Polls the print queue, resolves printer IPs, sends ESC/POS bytes over network.
Retry loop: immediate → 5s → 15s → 30s → FAILED
"""
import asyncio
import json
import logging
import socket
import aiosqlite
import os
from typing import Dict, Optional

from .print_queue import PrintJobQueue
from .escpos_formatter import ESCPOSFormatter
from .templates.guest_receipt import GuestReceiptTemplate
from .templates.kitchen_ticket import KitchenTicketTemplate
from .templates.clock_hours import ClockHoursTemplate
from .templates.sales_recap import SalesRecapTemplate

logger = logging.getLogger("kindpos.printing.dispatcher")

# ── Hardware config DB path ────────────────────────────────────────────────────
HARDWARE_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'hardware_config.db'
)

# ── Fallback IPs (used if hardware_config.db has no entry) ────────────────────
FALLBACK_IPS: Dict[str, str] = {
    "DEFAULT_RECEIPT": "10.0.0.186",
    "DEFAULT_KITCHEN": "10.0.0.19",
}

# Type-based fallback when a MAC-registered printer's IP can't be resolved
_TYPE_FALLBACK_IPS: Dict[str, str] = {
    "kitchen": "10.0.0.19",
    "receipt": "10.0.0.186",
}

PRINTER_PORT = 9100
RETRY_DELAYS = [0, 5, 15, 30]
MAX_ATTEMPTS = len(RETRY_DELAYS)


class PrintDispatcher:
    """
    Background service that drains the print queue.
    Call start() once at app startup, stop() at shutdown.
    """

    def __init__(self, queue: PrintJobQueue, poll_interval: float = 3.0):
        self._queue         = queue
        self._poll_interval = poll_interval
        self._running       = False
        self._task: Optional[asyncio.Task] = None
        self._failure_subscribers: list[asyncio.Queue] = []

        # Receipt printer: 48 chars per line
        # Kitchen printer: 33 chars per line
        self._formatter_receipt = ESCPOSFormatter(paper_width=80, chars_per_line=48)
        self._formatter_kitchen = ESCPOSFormatter(paper_width=80, chars_per_line=33)
        self._templates_receipt = {
            "guest_receipt":  GuestReceiptTemplate(paper_width=80, chars_per_line=48),
            "clock_hours":    ClockHoursTemplate(paper_width=80, chars_per_line=48),
            "sales_recap":    SalesRecapTemplate(paper_width=80, chars_per_line=48),
            "server_checkout": None,  # loaded lazily if needed
        }
        self._templates_kitchen = {
            "kitchen_ticket": KitchenTicketTemplate(paper_width=80, chars_per_line=33),
        }

    def subscribe_failures(self) -> asyncio.Queue:
        """Return a queue that receives print failure dicts."""
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._failure_subscribers.append(q)
        return q

    def unsubscribe_failures(self, q: asyncio.Queue) -> None:
        try:
            self._failure_subscribers.remove(q)
        except ValueError:
            pass

    def _broadcast_failure(self, job: dict, error: str) -> None:
        msg = {
            "type": "print_failure",
            "job_id": job.get("job_id"),
            "order_id": job.get("order_id"),
            "template_id": job.get("template_id"),
            "printer_mac": job.get("printer_mac"),
            "error": error,
        }
        for q in list(self._failure_subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # drop if subscriber is too slow

    async def start(self) -> None:
        self._running = True
        self._task    = asyncio.create_task(self._loop())
        logger.info("PrintDispatcher started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PrintDispatcher stopped")

    # ── Main poll loop ────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                jobs = await self._queue.get_pending_jobs()
                for job in jobs:
                    if not self._running:
                        break
                    await self._process_job(job)
            except Exception as e:
                logger.error(f"Dispatcher loop error: {e}")
            await asyncio.sleep(self._poll_interval)

    # ── Job processor ─────────────────────────────────────────────────────────

    async def _process_job(self, job: dict) -> None:
        job_id      = job["job_id"]
        attempt     = job.get("attempt_count", 0) + 1
        template_id = job["template_id"]
        printer_mac = job["printer_mac"]

        if attempt > MAX_ATTEMPTS:
            await self._queue.mark_failed(job_id)
            logger.error(f"Job {job_id} exceeded max attempts — marked FAILED")
            self._broadcast_failure(job, "Exceeded max retry attempts")
            return

        delay = RETRY_DELAYS[attempt - 1]
        if delay > 0:
            logger.info(f"Job {job_id} retry #{attempt} in {delay}s")
            await asyncio.sleep(delay)

        await self._queue.mark_sent(job_id, attempt)

        try:
            context = json.loads(job["context_json"])
            raw     = self._render(template_id, context, printer_mac)
            ip      = await self._resolve_ip(printer_mac)
            await self._send(ip, raw)
            await self._queue.mark_completed(job_id)
            logger.info(f"Job {job_id} ({template_id}) → {ip} ✓")

        except Exception as e:
            logger.warning(f"Job {job_id} attempt {attempt} failed: {e}")
            await self._queue.reset_for_retry(job_id)
            # Preserve attempt count after reset
            try:
                await self._queue._db.execute(
                    "UPDATE print_queue SET attempt_count = ? WHERE job_id = ?",
                    (attempt, job_id)
                )
                await self._queue._db.commit()
            except Exception:
                pass
            if attempt >= MAX_ATTEMPTS:
                await self._queue.mark_failed(job_id)
                logger.error(f"Job {job_id} FAILED after {attempt} attempts: {e}")
                self._broadcast_failure(job, str(e))

    # ── Render ────────────────────────────────────────────────────────────────

    def _render(self, template_id: str, context: dict, printer_mac: str = "") -> bytes:
        is_kitchen = (printer_mac == "DEFAULT_KITCHEN")
        templates = self._templates_kitchen if is_kitchen else self._templates_receipt
        formatter = self._formatter_kitchen if is_kitchen else self._formatter_receipt

        template = templates.get(template_id)
        if not template:
            # Fall back to the other set in case template is registered there
            other = self._templates_receipt if is_kitchen else self._templates_kitchen
            template = other.get(template_id)
        if not template:
            raise ValueError(f"Unknown template: {template_id}")
        commands = template.render(context)
        return formatter.format(commands)

    # ── IP resolution ─────────────────────────────────────────────────────────

    async def _resolve_ip(self, printer_mac: str) -> str:
        """
        Resolve a printer MAC address to its current IP via hardware_config.db.
        Falls back to FALLBACK_IPS for legacy DEFAULT_KITCHEN / DEFAULT_RECEIPT keys,
        then to type-based defaults if the DB lookup fails.
        """
        # Legacy fallback keys (used before MAC-as-identity was wired)
        if printer_mac in FALLBACK_IPS:
            return FALLBACK_IPS[printer_mac]

        try:
            async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
                async with db.execute(
                    "SELECT ip, type FROM devices WHERE mac = ? LIMIT 1",
                    (printer_mac,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row and row[0]:
                        return row[0]
                    # IP missing but device exists — try type-based fallback
                    if row and row[1] and row[1] in _TYPE_FALLBACK_IPS:
                        logger.warning(f"No IP for {printer_mac}, using {row[1]} type fallback")
                        return _TYPE_FALLBACK_IPS[row[1]]
        except Exception as e:
            logger.warning(f"hardware_config.db lookup failed for {printer_mac}: {e}")

        # Last resort: infer type from template association
        for ttype, ip in _TYPE_FALLBACK_IPS.items():
            if ttype in printer_mac.lower():
                logger.warning(f"Using type-name fallback for {printer_mac} → {ip}")
                return ip

        raise ValueError(f"No IP found for printer MAC: {printer_mac}")

    # ── Network send ──────────────────────────────────────────────────────────

    async def _send(self, ip: str, data: bytes) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_sync, ip, data)

    def _send_sync(self, ip: str, data: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((ip, PRINTER_PORT))
            s.sendall(data)