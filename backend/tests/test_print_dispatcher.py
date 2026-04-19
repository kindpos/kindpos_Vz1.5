"""
Tests for `app/printing/print_dispatcher.py` — the background service
that drains the print queue, renders templates, resolves printer IPs,
and ships ESC/POS bytes over TCP.

print_dispatcher.py sat at 23% coverage. If it silently swallows a
job or retries past the intended ceiling, operators don't notice
until a kitchen ticket never comes out. Tests cover:

  - _render: dispatches to receipt vs kitchen formatter by printer_mac
             and raises cleanly on unknown template_id
  - _resolve_ip: fallback keys, hardware_config.db lookup, type-based
                 fallback, and final "no IP found" raise
  - _process_job: success path → mark_completed; failure → retry +
                  reset_for_retry with attempt_count preserved;
                  exceeding MAX_ATTEMPTS → mark_failed + broadcast
  - subscribe/unsubscribe failure queues
  - lifecycle: start + stop
"""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest
import pytest_asyncio

from app.printing import print_dispatcher as pd_mod
from app.printing.print_dispatcher import (
    FALLBACK_IPS,
    MAX_ATTEMPTS,
    PrintDispatcher,
    RETRY_DELAYS,
)
from app.printing.print_queue import PrintJobQueue


# ═══════════════════════════════════════════════════════════════════════════
# Fakes
# ═══════════════════════════════════════════════════════════════════════════

class FakeQueue:
    """A drop-in for PrintJobQueue that records which hook was called.

    We only need the methods the dispatcher touches: mark_sent,
    mark_completed, mark_failed, reset_for_retry, and the raw `_db`
    escape hatch the retry path reaches into for attempt_count.
    """

    def __init__(self):
        self.calls: List[tuple] = []
        # Minimal `_db`: expose execute + commit so the retry-count
        # preservation call path runs without error.
        self._db = self._DummyDb(self)

    class _DummyDb:
        def __init__(self, parent):
            self.parent = parent

        async def execute(self, *args, **kwargs):
            self.parent.calls.append(("db.execute", args, kwargs))

        async def commit(self):
            self.parent.calls.append(("db.commit",))

    async def mark_sent(self, job_id: str, attempt: int):
        self.calls.append(("mark_sent", job_id, attempt))

    async def mark_completed(self, job_id: str):
        self.calls.append(("mark_completed", job_id))

    async def mark_failed(self, job_id: str):
        self.calls.append(("mark_failed", job_id))

    async def reset_for_retry(self, job_id: str):
        self.calls.append(("reset_for_retry", job_id))

    async def get_pending_jobs(self):
        return []

    def names(self) -> List[str]:
        return [c[0] for c in self.calls]


def _make_job(
    *, job_id: str = "J1", order_id: str = "O1",
    template_id: str = "guest_receipt", printer_mac: str = "DEFAULT_RECEIPT",
    attempt_count: int = 0, context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Build a job dict in the shape `_process_job` expects."""
    return {
        "job_id": job_id,
        "order_id": order_id,
        "template_id": template_id,
        "printer_mac": printer_mac,
        "attempt_count": attempt_count,
        "context_json": json.dumps(context or {}),
    }


@pytest.fixture(autouse=True)
def _neuter_retry_delays(monkeypatch):
    """Zero out the retry sleeps so tests run in under a second.

    `RETRY_DELAYS = [0, 5, 15, 30]` — without this fixture, a single
    failure/retry test would take 5 seconds of real time.
    """
    monkeypatch.setattr(pd_mod, "RETRY_DELAYS", [0, 0, 0, 0])


@pytest.fixture
def dispatcher():
    """A dispatcher wired to a fake queue. No real task loop is started."""
    return PrintDispatcher(queue=FakeQueue(), poll_interval=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# _render
# ═══════════════════════════════════════════════════════════════════════════

class TestRender:

    def test_receipt_template_rendered_with_receipt_formatter(self, dispatcher):
        """guest_receipt + DEFAULT_RECEIPT → bytes produced, non-empty."""
        ctx = {
            "order_id": "O1",
            "items": [{"qty": 1, "name": "Item", "price": 10.0, "subtotal": 10.0}],
            "subtotal": 10.0,
            "tax": 0.0,
            "total": 10.0,
            "tax_lines": [],
        }
        out = dispatcher._render("guest_receipt", ctx, printer_mac="DEFAULT_RECEIPT")
        assert isinstance(out, bytes)
        assert len(out) > 0

    def test_kitchen_template_rendered_with_kitchen_formatter(self, dispatcher):
        """kitchen_ticket + DEFAULT_KITCHEN → bytes produced."""
        ctx = {
            "order_id": "O1",
            "items": [{"qty": 1, "name": "Burger"}],
            "fired_at": "2026-04-17T18:00:00+00:00",
        }
        out = dispatcher._render("kitchen_ticket", ctx, printer_mac="DEFAULT_KITCHEN")
        assert isinstance(out, bytes)
        assert len(out) > 0

    def test_unknown_template_raises_value_error(self, dispatcher):
        with pytest.raises(ValueError) as exc:
            dispatcher._render("not_a_template", {}, printer_mac="DEFAULT_RECEIPT")
        assert "Unknown template" in str(exc.value)

    def test_cross_bucket_fallback(self, dispatcher):
        """If a template is registered only on the other side (receipt vs
        kitchen), `_render` still finds it — the fallback lookup path."""
        # kitchen_ticket lives in _templates_kitchen; request it via a
        # non-kitchen MAC to exercise the "other" bucket lookup.
        ctx = {
            "order_id": "O1",
            "items": [{"qty": 1, "name": "X"}],
        }
        out = dispatcher._render("kitchen_ticket", ctx, printer_mac="DEFAULT_RECEIPT")
        assert isinstance(out, bytes)


# ═══════════════════════════════════════════════════════════════════════════
# _resolve_ip
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveIp:

    @pytest.mark.asyncio
    async def test_legacy_default_keys(self, dispatcher):
        """The two hardcoded legacy keys must always resolve — they're the
        fallback contract for early installs that haven't registered a MAC."""
        assert await dispatcher._resolve_ip("DEFAULT_RECEIPT") == FALLBACK_IPS["DEFAULT_RECEIPT"]
        assert await dispatcher._resolve_ip("DEFAULT_KITCHEN") == FALLBACK_IPS["DEFAULT_KITCHEN"]

    @pytest.mark.asyncio
    async def test_db_lookup_returns_ip(self, dispatcher, tmp_path, monkeypatch):
        """Registered MAC in hardware_config.db resolves to that row's ip."""
        db_path = tmp_path / "hardware.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE devices (mac TEXT, ip TEXT, type TEXT)")
        conn.execute(
            "INSERT INTO devices (mac, ip, type) VALUES (?, ?, ?)",
            ("AA:BB:CC:DD:EE:FF", "10.0.0.42", "kitchen"),
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(pd_mod, "HARDWARE_DB_PATH", str(db_path))

        assert await dispatcher._resolve_ip("AA:BB:CC:DD:EE:FF") == "10.0.0.42"

    @pytest.mark.asyncio
    async def test_db_row_missing_ip_uses_type_fallback(self, dispatcher, tmp_path, monkeypatch):
        """Device row with NULL IP falls back to the type-based default."""
        db_path = tmp_path / "hardware.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE devices (mac TEXT, ip TEXT, type TEXT)")
        conn.execute(
            "INSERT INTO devices (mac, ip, type) VALUES (?, ?, ?)",
            ("11:22:33:44:55:66", None, "kitchen"),
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(pd_mod, "HARDWARE_DB_PATH", str(db_path))

        ip = await dispatcher._resolve_ip("11:22:33:44:55:66")
        assert ip == pd_mod._TYPE_FALLBACK_IPS["kitchen"]

    @pytest.mark.asyncio
    async def test_unknown_mac_raises(self, dispatcher, tmp_path, monkeypatch):
        """Unregistered MAC that doesn't match any type-name heuristic → raise."""
        db_path = tmp_path / "hardware.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE devices (mac TEXT, ip TEXT, type TEXT)")
        conn.commit()
        conn.close()
        monkeypatch.setattr(pd_mod, "HARDWARE_DB_PATH", str(db_path))

        with pytest.raises(ValueError) as exc:
            await dispatcher._resolve_ip("DE:AD:BE:EF:00:01")
        assert "No IP found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_name_based_type_fallback(self, dispatcher, monkeypatch):
        """If the MAC string *contains* 'kitchen' or 'receipt', dispatch
        still resolves — a name-shaped escape hatch for unregistered
        printers in dev."""
        # Point the DB path somewhere that doesn't exist so the DB
        # lookup branch falls through and hits the name-contains check.
        monkeypatch.setattr(pd_mod, "HARDWARE_DB_PATH", "/tmp/nonexistent_hw.db")

        ip = await dispatcher._resolve_ip("some-kitchen-printer")
        assert ip == pd_mod._TYPE_FALLBACK_IPS["kitchen"]


# ═══════════════════════════════════════════════════════════════════════════
# _process_job — success, retry, exceed attempts
# ═══════════════════════════════════════════════════════════════════════════

class TestProcessJob:

    @pytest.mark.asyncio
    async def test_success_path_marks_completed(self, dispatcher, monkeypatch):
        """Happy path: mark_sent → render → resolve → send → mark_completed."""
        sent_payloads: List[tuple] = []

        async def fake_send(ip: str, data: bytes):
            sent_payloads.append((ip, data))

        monkeypatch.setattr(dispatcher, "_send", fake_send)

        job = _make_job(context={
            "order_id": "O1",
            "items": [{"qty": 1, "name": "X", "price": 1.0, "subtotal": 1.0}],
            "subtotal": 1.0, "tax": 0.0, "total": 1.0, "tax_lines": [],
        })
        await dispatcher._process_job(job)

        names = dispatcher._queue.names()
        assert "mark_sent" in names
        assert "mark_completed" in names
        assert "mark_failed" not in names
        # Bytes were actually delivered to the resolved IP
        assert len(sent_payloads) == 1
        assert sent_payloads[0][0] == FALLBACK_IPS["DEFAULT_RECEIPT"]
        assert len(sent_payloads[0][1]) > 0

    @pytest.mark.asyncio
    async def test_transient_failure_resets_for_retry(self, dispatcher, monkeypatch):
        """Send raises → reset_for_retry, no mark_failed, no broadcast
        (attempt still under the MAX_ATTEMPTS ceiling)."""
        async def fake_send(ip: str, data: bytes):
            raise ConnectionRefusedError("printer unreachable")

        monkeypatch.setattr(dispatcher, "_send", fake_send)

        # Subscribe so we can verify no failure is broadcast mid-retry.
        failures = dispatcher.subscribe_failures()

        await dispatcher._process_job(_make_job(attempt_count=0))

        names = dispatcher._queue.names()
        assert "mark_sent" in names
        assert "reset_for_retry" in names
        assert "mark_failed" not in names
        # The retry path preserves attempt_count via a raw UPDATE + commit
        assert ("db.commit",) in dispatcher._queue.calls
        # No premature failure broadcast
        assert failures.empty()

    @pytest.mark.asyncio
    async def test_exceeds_max_attempts_marks_failed_and_broadcasts(self, dispatcher, monkeypatch):
        """When attempt_count reaches MAX_ATTEMPTS and the send still
        fails, the job is marked FAILED and every subscriber gets a
        broadcast so the UI can surface it."""
        async def fake_send(ip: str, data: bytes):
            raise ConnectionResetError("kaboom")

        monkeypatch.setattr(dispatcher, "_send", fake_send)

        q = dispatcher.subscribe_failures()
        # attempt_count=MAX_ATTEMPTS-1 so `attempt = attempt_count+1 = MAX_ATTEMPTS`
        job = _make_job(attempt_count=MAX_ATTEMPTS - 1)
        await dispatcher._process_job(job)

        names = dispatcher._queue.names()
        assert names.count("mark_failed") >= 1
        # Broadcast received
        msg = q.get_nowait()
        assert msg["type"] == "print_failure"
        assert msg["job_id"] == job["job_id"]
        assert "kaboom" in msg["error"]

    @pytest.mark.asyncio
    async def test_already_past_max_attempts_short_circuits(self, dispatcher, monkeypatch):
        """A job that arrives with attempt_count > MAX_ATTEMPTS is marked
        failed without attempting another send. Defensive against a
        persister-glitch or a DB field read from a bad value."""
        send_attempts: List[tuple] = []

        async def fake_send(ip: str, data: bytes):
            send_attempts.append((ip, data))

        monkeypatch.setattr(dispatcher, "_send", fake_send)
        q = dispatcher.subscribe_failures()

        job = _make_job(attempt_count=MAX_ATTEMPTS + 5)
        await dispatcher._process_job(job)

        assert send_attempts == []   # never even tried the socket
        assert dispatcher._queue.names().count("mark_failed") == 1
        assert not q.empty()

    @pytest.mark.asyncio
    async def test_render_failure_treated_as_transient(self, dispatcher, monkeypatch):
        """If the template doesn't exist the render raises — same retry
        bookkeeping as a socket failure, not an immediate FAILED."""
        job = _make_job(template_id="bogus_template", attempt_count=0)
        await dispatcher._process_job(job)
        names = dispatcher._queue.names()
        assert "reset_for_retry" in names
        assert "mark_failed" not in names


# ═══════════════════════════════════════════════════════════════════════════
# Failure broadcast subscriptions
# ═══════════════════════════════════════════════════════════════════════════

class TestFailureBroadcast:

    def test_subscribe_returns_new_queue(self, dispatcher):
        q1 = dispatcher.subscribe_failures()
        q2 = dispatcher.subscribe_failures()
        assert q1 is not q2
        assert q1 in dispatcher._failure_subscribers
        assert q2 in dispatcher._failure_subscribers

    def test_unsubscribe_removes_queue(self, dispatcher):
        q = dispatcher.subscribe_failures()
        dispatcher.unsubscribe_failures(q)
        assert q not in dispatcher._failure_subscribers

    def test_unsubscribe_unknown_queue_is_a_noop(self, dispatcher):
        """Double-unsubscribe must not explode — network disconnects can
        cause this race. `remove` would raise, `.unsubscribe_failures`
        swallows the ValueError."""
        q = asyncio.Queue()
        dispatcher.unsubscribe_failures(q)   # wasn't subscribed
        # No exception → pass

    def test_broadcast_fans_out_to_all_subscribers(self, dispatcher):
        q1 = dispatcher.subscribe_failures()
        q2 = dispatcher.subscribe_failures()
        dispatcher._broadcast_failure(
            {"job_id": "J1", "order_id": "O1", "template_id": "T", "printer_mac": "M"},
            "disk full",
        )
        m1 = q1.get_nowait()
        m2 = q2.get_nowait()
        assert m1 == m2
        assert m1["job_id"] == "J1"
        assert m1["error"] == "disk full"

    def test_broadcast_drops_when_subscriber_queue_is_full(self, dispatcher):
        """A slow/disconnected subscriber must not block the dispatcher."""
        slow = asyncio.Queue(maxsize=1)
        dispatcher._failure_subscribers.append(slow)
        # Fill it
        slow.put_nowait("existing")
        # Broadcast — should NOT raise QueueFull
        dispatcher._broadcast_failure({"job_id": "J9"}, "err")
        # The slow subscriber still only has the original item
        assert slow.qsize() == 1


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestLifecycle:

    @pytest.mark.asyncio
    async def test_start_then_stop_is_clean(self, dispatcher):
        """start() schedules the loop task; stop() cancels and awaits it."""
        await dispatcher.start()
        assert dispatcher._task is not None
        assert dispatcher._running is True
        await dispatcher.stop()
        assert dispatcher._running is False
        # Task was awaited to completion
        assert dispatcher._task.done()

    @pytest.mark.asyncio
    async def test_stop_before_start_does_not_crash(self, dispatcher):
        await dispatcher.stop()   # _task is None, stop() handles it
        assert dispatcher._running is False
