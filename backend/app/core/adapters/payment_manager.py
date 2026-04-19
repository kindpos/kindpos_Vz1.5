import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List, Any
from decimal import Decimal

from .base_payment import (
    BasePaymentDevice,
    PaymentDeviceConfig,
    PaymentDeviceStatus,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
    BatchResult,
    PaymentType,
    PaymentError,
    PaymentErrorCategory
)
from ..events import (
    EventType,
    Event,
    create_event
)
from ..event_ledger import EventLedger
from ..money import money_round

logger = logging.getLogger("kindpos.payment.manager")

class PaymentManager:
    """
    The Brain — handles idempotency, event emission, device routing, 
    timeout enforcement, and deferred queue.
    """

    def __init__(self, ledger: EventLedger, terminal_id: str):
        self._ledger = ledger
        self._terminal_id = terminal_id
        self._devices: Dict[str, BasePaymentDevice] = {} # device_id -> adapter
        self._terminal_device_map: Dict[str, str] = {} # terminal_id -> device_id

    def register_device(self, device: BasePaymentDevice):
        if device.config:
            self._devices[device.config.device_id] = device
            logger.info(f"Registered payment device: {device.config.name} ({device.config.device_id})")

    def map_terminal_to_device(self, terminal_id: str, device_id: str):
        self._terminal_device_map[terminal_id] = device_id

    def get_device_for_terminal(self, terminal_id: str):
        """Return the payment device mapped to a terminal, or None."""
        device_id = self._terminal_device_map.get(terminal_id)
        if device_id and device_id in self._devices:
            return self._devices[device_id]
        return None

    async def initiate_sale(self, request: TransactionRequest, tax: float = 0.0) -> TransactionResult:
        """Core sale entry point with idempotency and event emission."""

        # 5.1 Idempotency check
        existing_result = await self._check_idempotency(request.transaction_id)
        if existing_result:
            logger.info(f"Idempotency hit for {request.transaction_id}")
            return existing_result

        # Get device for this terminal
        device_id = self._terminal_device_map.get(request.terminal_id)
        if not device_id or device_id not in self._devices:
            return self._error_result(request.transaction_id, PaymentErrorCategory.SYSTEM, "NO_DEVICE", f"No payment device mapped to terminal {request.terminal_id}")

        device = self._devices[device_id]

        # 5.2 Event Emission - Initiated
        event = self._create_payment_event(EventType.PAYMENT_INITIATED, request.dict())
        await self._ledger.append(event)

        # 5.4 Timeout Enforcement (90s)
        try:
            result = await asyncio.wait_for(device.initiate_sale(request), timeout=90.0)
        except asyncio.TimeoutError:
            logger.warning(f"Payment {request.transaction_id} timed out. Attempting cancel.")
            await device.cancel_transaction()
            result = TransactionResult(
                transaction_id=request.transaction_id,
                status=TransactionStatus.TIMEOUT,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"Payment {request.transaction_id} failed with exception: {e}")
            result = TransactionResult(
                transaction_id=request.transaction_id,
                status=TransactionStatus.ERROR,
                error=PaymentError(
                    category=PaymentErrorCategory.SYSTEM,
                    error_code="INTERNAL_ERR",
                    message=str(e),
                    source="PaymentManager"
                )
            )

        # 5.2 Event Emission - Result (include tax captured at payment time)
        await self._emit_result_event(request, result, extra={"tax": money_round(tax)})

        return result

    async def _check_idempotency(self, transaction_id: str) -> Optional[TransactionResult]:
        """Check if transaction already exists in ledger."""
        # Query ledger for payment.confirmed (PAYMENT_CONFIRMED)
        events = await self._ledger.get_events_by_type(EventType.PAYMENT_CONFIRMED)
        for e in events:
             if e.payload.get("transaction_id") == transaction_id:
                 return TransactionResult(**e.payload)
        
        # Also check failures (PAYMENT_DECLINED mapped to payment.failed)
        events = await self._ledger.get_events_by_type(EventType.PAYMENT_DECLINED)
        for e in events:
             if e.payload.get("transaction_id") == transaction_id:
                 return TransactionResult(**e.payload)
                 
        return None

    async def _emit_result_event(self, request: TransactionRequest, result: TransactionResult, extra: dict = None):
        status_map = {
            TransactionStatus.APPROVED: EventType.PAYMENT_CONFIRMED,
            TransactionStatus.DECLINED: EventType.PAYMENT_DECLINED,
            TransactionStatus.CANCELLED: EventType.PAYMENT_CANCELLED,
            TransactionStatus.TIMEOUT: EventType.PAYMENT_TIMED_OUT,
            TransactionStatus.ERROR: EventType.PAYMENT_ERROR
        }

        event_type = status_map.get(result.status, EventType.PAYMENT_ERROR)

        payload = request.dict()
        payload.update(result.dict())
        if extra:
            payload.update(extra)
        
        event = self._create_payment_event(event_type, payload)
        await self._ledger.append(event)

    def _create_payment_event(self, event_type: EventType, payload: Dict[str, Any]) -> Event:
        # Convert any Decimals in payload to strings for JSON compatibility
        def serialize(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: serialize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [serialize(i) for i in obj]
            return obj

        serialized = serialize(payload)
        # payment_manager only ever handles card-terminal flows, so stamp
        # `method: "card"` on every event it emits. Without this, the
        # projection falls back to `payment_type` (the string "SALE") and
        # every downstream consumer that classifies with `== "card"` or
        # `== "cash"` — manager-landing's unadjusted-tip counter, the
        # receipt builder's cash/card split, server-checkout tallies —
        # silently misses the payment. The tip-adjustment UI then shows
        # these checks as "already adjusted" and the sales split shows
        # them as neither cash nor card.
        if isinstance(serialized, dict):
            serialized.setdefault("method", "card")
        return create_event(
            event_type=event_type,
            terminal_id=self._terminal_id,
            payload=serialized,
            correlation_id=serialized.get("order_id") if isinstance(serialized, dict) else None,
        )

    def _error_result(self, tx_id: str, cat: PaymentErrorCategory, code: str, msg: str) -> TransactionResult:
        return TransactionResult(
            transaction_id=tx_id,
            status=TransactionStatus.ERROR,
            error=PaymentError(category=cat, error_code=code, message=msg, source="PaymentManager")
        )
