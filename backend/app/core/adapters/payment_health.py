import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from .base_payment import (
    BasePaymentDevice,
    PaymentDeviceStatus,
    PaymentDeviceConfig
)
from ..events import EventType, create_event
from ..event_ledger import EventLedger
from ..ephemeral_log import EphemeralLog

logger = logging.getLogger("kindpos.payment.health")

class PaymentHealthMonitor:
    """
    Continuous monitoring of payment devices.
    Tracks status, detects transitions, feeds Weather Report.
    """

    def __init__(self, ledger: EventLedger, terminal_id: str, devices: List[BasePaymentDevice], ephemeral_log: Optional[EphemeralLog] = None):
        self._ledger = ledger
        self._ephemeral = ephemeral_log or ledger
        self._terminal_id = terminal_id
        self._devices = devices
        self._stop_event = asyncio.Event()
        self._polling_task: Optional[asyncio.Task] = None

    async def start(self):
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("Payment Health Monitor started.")

    async def stop(self):
        self._stop_event.set()
        if self._polling_task:
            await self._polling_task
        logger.info("Payment Health Monitor stopped.")

    async def _poll_loop(self):
        while not self._stop_event.is_set():
            for device in self._devices:
                if self._stop_event.is_set():
                    break
                
                # Tiered Polling Strategy
                status = device.status
                interval = 10.0 # Default IDLE

                if device.in_sacred_state:
                    # AWAITING_CARD / PROCESSING -> back off entirely
                    continue
                
                if status == PaymentDeviceStatus.OFFLINE:
                    interval = 5.0
                elif status in [PaymentDeviceStatus.ONLINE, PaymentDeviceStatus.DEFERRED_MODE]:
                    interval = 15.0
                elif status == PaymentDeviceStatus.ERROR:
                    interval = 30.0

                old_status = status
                new_status = await device.check_status()

                if old_status != new_status:
                    await self._handle_status_change(device, old_status, new_status)

            await asyncio.sleep(2.0) # Small tick to avoid tight loop

    async def _handle_status_change(self, device: BasePaymentDevice, old_status: PaymentDeviceStatus, new_status: PaymentDeviceStatus):
        logger.info(f"Device {device.config.name if device.config else 'Unknown'} changed status: {old_status} -> {new_status}")
        
        # 1.7 device.status_changed event
        event = create_event(
            event_type=EventType.DEVICE_STATUS_CHANGED,
            terminal_id=self._terminal_id,
            payload={
                "device_id": device.config.device_id if device.config else "unknown",
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": datetime.now().isoformat()
            }
        )
        await self._ephemeral.append(event)

        # SIM Failover Signal detection (IDLE -> ONLINE means LAN ok, WAN suspect)
        if old_status == PaymentDeviceStatus.IDLE and new_status == PaymentDeviceStatus.ONLINE:
             logger.warning(f"Potential WAN outage detected on device {device.config.device_id}. SIM failover signal.")
             # In a real system, we might trigger a secondary check or notify via WebSocket
