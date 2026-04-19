"""
Tests for PaymentHealthMonitor.

Covers:
    - start / stop lifecycle
    - status change detection and ledger event emission
    - sacred state polling skip
"""

import asyncio
import pytest
from pathlib import Path
import os

from app.core.adapters.payment_health import PaymentHealthMonitor
from app.core.adapters.mock_payment import MockPaymentDevice
from app.core.adapters.base_payment import (
    PaymentDeviceConfig,
    PaymentDeviceType,
    PaymentDeviceStatus,
)
from app.core.event_ledger import EventLedger
from app.core.events import EventType


# ─── Helpers ────────────────────────────────────────────────────────────────


def make_config(device_id="dev-01"):
    return PaymentDeviceConfig(
        device_id=device_id,
        name="Test Reader",
        device_type=PaymentDeviceType.SMART_TERMINAL,
        ip_address="127.0.0.1",
        mac_address="00:11:22:33:44:55",
        port=8443,
        protocol="mock",
        processor_id="mock",
    )


# ─── Fixtures ───────────────────────────────────────────────────────────────

TEST_DB = Path("./data/test_payment_health.db")


@pytest.fixture
async def ledger():
    if TEST_DB.exists():
        os.remove(TEST_DB)
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        os.remove(TEST_DB)


@pytest.fixture
async def device():
    dev = MockPaymentDevice()
    await dev.connect(make_config())
    return dev


# ─── Tests ──────────────────────────────────────────────────────────────────


async def test_start_stop(ledger, device):
    """Start monitor, stop it — no errors, task cancelled cleanly."""
    monitor = PaymentHealthMonitor(
        ledger=ledger, terminal_id="T1", devices=[device]
    )
    await monitor.start()
    await asyncio.sleep(0.1)
    await monitor.stop()
    # After stop, the polling task should be done
    assert monitor._polling_task is not None
    assert monitor._polling_task.done()


async def test_detects_status_change(ledger, device):
    """Setting device to OFFLINE and calling _handle_status_change emits an event."""
    monitor = PaymentHealthMonitor(
        ledger=ledger, terminal_id="T1", devices=[device]
    )

    old_status = PaymentDeviceStatus.IDLE
    device.set_device_status(PaymentDeviceStatus.OFFLINE)

    await monitor._handle_status_change(device, old_status, PaymentDeviceStatus.OFFLINE)

    events = await ledger.get_events_by_type(EventType.DEVICE_STATUS_CHANGED)
    assert len(events) == 1
    assert events[0].payload["device_id"] == "dev-01"
    assert events[0].payload["old_status"] == PaymentDeviceStatus.IDLE
    assert events[0].payload["new_status"] == PaymentDeviceStatus.OFFLINE


async def test_sacred_state_skipped(ledger, device):
    """Device in sacred state is skipped by _poll_loop — no events emitted."""
    device.set_device_status(PaymentDeviceStatus.AWAITING_CARD)

    monitor = PaymentHealthMonitor(
        ledger=ledger, terminal_id="T1", devices=[device]
    )

    # Run monitor briefly
    await monitor.start()
    await asyncio.sleep(0.2)
    await monitor.stop()

    # Sacred state means it's skipped entirely — no status change events
    events = await ledger.get_events_by_type(EventType.DEVICE_STATUS_CHANGED)
    assert len(events) == 0
