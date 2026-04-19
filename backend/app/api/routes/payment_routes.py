from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from decimal import Decimal
import uuid
import aiosqlite
import os

# Correcting relative imports for app.api.routes
from ..dependencies import get_ledger
from ...core.event_ledger import EventLedger
from ...core.adapters.payment_manager import PaymentManager
from ...core.adapters.payment_validator import PaymentValidator
from ...core.adapters.base_payment import TransactionRequest, TransactionResult, TransactionStatus, ValidationStatus, ValidationResult, PaymentDeviceConfig, PaymentDeviceType
from ...core.adapters.mock_payment import MockPaymentDevice
from ...core.adapters.dejavoo_spin import DejavooSPInAdapter
from ...core.events import (
    payment_initiated, payment_confirmed, order_closed, tip_adjusted,
    create_event, EventType,
)
from ...core.projections import project_order, project_orders
from ...core.money import money_round
from ...config import settings
from typing import Optional as Opt

router = APIRouter(prefix="/payments", tags=["payments"])

_manager: Optional[PaymentManager] = None
_validator: Optional[PaymentValidator] = None

_devices_initialized = False

HARDWARE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'hardware_config.db')


async def _ensure_devices(manager: PaymentManager):
    """Load saved card readers as SPIn adapters, fall back to mock."""
    global _devices_initialized
    if _devices_initialized:
        return
    _devices_initialized = True

    # Try to load a real card reader from hardware_config.db
    reader_found = False
    if os.path.exists(HARDWARE_DB_PATH):
        try:
            async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM devices WHERE type = 'card_reader' LIMIT 1") as cur:
                    row = await cur.fetchone()
                    if row:
                        device = dict(row)
                        adapter = DejavooSPInAdapter()
                        config = PaymentDeviceConfig(
                            device_id=device['mac'],
                            name=device.get('name', 'Dejavoo'),
                            device_type=PaymentDeviceType.SMART_TERMINAL,
                            ip_address=device['ip'],
                            mac_address=device['mac'],
                            port=device.get('port', 9000),
                            protocol="spin",
                            processor_id="dejavoo",
                            register_id=device.get('register_id', ''),
                            tpn=device.get('tpn', ''),
                            auth_key=device.get('auth_key', ''),
                        )
                        connected = await adapter.connect(config)
                        if connected:
                            manager.register_device(adapter)
                            manager.map_terminal_to_device(settings.terminal_id, device['mac'])
                            manager.map_terminal_to_device("T-001", device['mac'])
                            reader_found = True
                            print(f"  Card reader loaded: {device.get('name', device['mac'])} @ {device['ip']}:{device.get('port', 9000)}")
                        else:
                            print(f"  Card reader saved but unreachable: {device['ip']}:{device.get('port', 9000)}")
        except Exception as e:
            print(f"  Warning: could not load card reader: {e}")

    # Fall back to mock if no real device found
    if not reader_found:
        mock = MockPaymentDevice()
        config = PaymentDeviceConfig(
            device_id="mock_001",
            name="Mock Payment Device",
            device_type=PaymentDeviceType.SMART_TERMINAL,
            ip_address="127.0.0.1",
            mac_address="00:00:00:00:00:00",
            port=9000,
            protocol="mock",
            processor_id="mock_processor",
        )
        await mock.connect(config)
        manager.register_device(mock)
        manager.map_terminal_to_device(settings.terminal_id, "mock_001")
        manager.map_terminal_to_device("T-001", "mock_001")
        print("  Mock payment device registered (no card reader found)")


@router.post("/reload-devices")
async def reload_devices(ledger: EventLedger = Depends(get_ledger)):
    """Hot-reload card reader from hardware_config.db without server restart."""
    global _devices_initialized, _manager
    _devices_initialized = False
    _manager = PaymentManager(ledger, settings.terminal_id)
    await _ensure_devices(_manager)
    # Report what's active
    device_ids = list(_manager._devices.keys()) if hasattr(_manager, '_devices') else []
    return {
        "reloaded": True,
        "active_devices": device_ids,
        "using_mock": any("mock" in d for d in device_ids),
    }


@router.get("/test-device")
async def test_device(ledger: EventLedger = Depends(get_ledger)):
    """Send GetStatus to the card reader and return the raw response."""
    manager = get_payment_manager(ledger)
    await _ensure_devices(manager)

    device = manager.get_device_for_terminal(settings.terminal_id)
    if not device:
        return {"connected": False, "error": "No device registered", "using_mock": True}

    is_mock = device.config and device.config.protocol == "mock"
    if is_mock:
        return {"connected": True, "device": "mock", "using_mock": True, "status": "ready"}

    # Real device — check status
    try:
        status = await device.check_status()
        cfg = device.config
        return {
            "connected": status.value != "OFFLINE",
            "using_mock": False,
            "status": status.value,
            "device": {
                "name": cfg.name if cfg else "unknown",
                "ip": cfg.ip_address if cfg else "",
                "port": cfg.port if cfg else 0,
                "register_id": cfg.register_id if cfg else "",
                "serial": cfg.device_id if cfg else "",
            },
        }
    except Exception as e:
        return {"connected": False, "using_mock": False, "error": str(e)}

@router.get("/spin-diag")
async def spin_diagnostic(ledger: EventLedger = Depends(get_ledger)):
    """Send multiple SPIn XML variants to diagnose what the terminal accepts."""
    import httpx, urllib.parse, xml.etree.ElementTree as ET_diag

    manager = get_payment_manager(ledger)
    await _ensure_devices(manager)
    device = manager.get_device_for_terminal(settings.terminal_id)
    if not device or not device.config or device.config.protocol == "mock":
        return {"error": "No real card reader loaded"}

    cfg = device.config
    reg = cfg.register_id or ""
    base_url = f"http://{cfg.ip_address}:{cfg.port}/spin/cgi.html"

    tests = [
        ("GetStatus bare",        f'<request><function>GetStatus</function><RegisterId>{reg}</RegisterId></request>'),
        ("GetStatus +Amount",     f'<request><function>GetStatus</function><RegisterId>{reg}</RegisterId><Amount>0.00</Amount></request>'),
        ("Sale minimal",          f'<request><function>Sale</function><RegisterId>{reg}</RegisterId><Amount>0.01</Amount><InvNum>diag0001</InvNum></request>'),
        ("Sale +PaymentType",     f'<request><function>Sale</function><RegisterId>{reg}</RegisterId><Amount>0.01</Amount><InvNum>diag0002</InvNum><PaymentType>Credit</PaymentType></request>'),
        ("Sale +AuthKey",         f'<request><function>Sale</function><RegisterId>{reg}</RegisterId><AuthKey></AuthKey><Amount>0.01</Amount><InvNum>diag0003</InvNum><PaymentType>Credit</PaymentType></request>'),
        ("CreditSale function",   f'<request><function>CreditSale</function><RegisterId>{reg}</RegisterId><Amount>0.01</Amount><InvNum>diag0004</InvNum></request>'),
        ("Sale +SPInProto fields", f'<request><function>Sale</function><RegisterId>{reg}</RegisterId><Amount>0.01</Amount><InvNum>diag0005</InvNum><PaymentType>Credit</PaymentType><Tip>0.00</Tip><Frequency>OneTime</Frequency></request>'),
    ]

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, xml in tests:
            encoded = urllib.parse.quote(xml, safe='')
            url = f"{base_url}?TerminalTransaction={encoded}"
            try:
                resp = await client.get(url)
                body = resp.text.strip()
                if "<xmp>" in body:
                    body = body.split("<xmp>", 1)[-1]
                if "</xmp>" in body:
                    body = body.split("</xmp>", 1)[0]
                body = urllib.parse.unquote(body.strip())
                results.append({"test": name, "status": resp.status_code, "response": body, "xml_sent": xml})
            except Exception as e:
                results.append({"test": name, "error": str(e), "xml_sent": xml})

    return {"device": f"{cfg.ip_address}:{cfg.port}", "register_id": reg, "results": results}


def get_payment_manager(ledger: EventLedger = Depends(get_ledger)) -> PaymentManager:
    global _manager
    if _manager is None:
        _manager = PaymentManager(ledger, settings.terminal_id)
    return _manager

def get_payment_validator(ledger: EventLedger = Depends(get_ledger)) -> PaymentValidator:
    global _validator
    if _validator is None:
        _validator = PaymentValidator(ledger)
    return _validator

@router.post("/sale")
async def process_sale(
    request: TransactionRequest,
    manager: PaymentManager = Depends(get_payment_manager),
    validator: PaymentValidator = Depends(get_payment_validator),
    ledger: EventLedger = Depends(get_ledger),
):
    """Initiate sale. Returns ValidationResult or TransactionResult."""
    await _ensure_devices(manager)
    # 1. Resolve Device
    device_id = manager._terminal_device_map.get(request.terminal_id)
    device = manager._devices.get(device_id) if device_id else None

    # 2. Validate
    v_result = await validator.validate(request, device)
    if v_result.status == ValidationStatus.REJECTED:
        raise HTTPException(status_code=400, detail=v_result.reason)

    if v_result.status == ValidationStatus.NEEDS_APPROVAL:
        return v_result # Return to frontend for PIN entry

    # 3. Process — capture tax at payment time
    order_events = await ledger.get_events_by_correlation(request.order_id)
    order_proj = project_order(order_events)
    if order_proj and order_proj.is_fully_paid:
        raise HTTPException(status_code=400, detail="Order is already fully paid")
    order_tax = order_proj.tax if order_proj else 0.0

    # Defense in depth: clamp the sale amount at the order's current
    # balance_due. Any excess — typically caused by a frontend that
    # computed its own cardTotal from a stale TAX_RATE and now disagrees
    # with the backend's `order.total` — is rerouted into `tip_amount`
    # so the tender identity (Cash+Card = Net+Tax) keeps holding. A
    # TIP_ADJUSTED event for the excess is emitted after confirmation
    # so both the projection and the operator's tip report stay honest.
    _overage_as_tip = 0.0
    if order_proj is not None:
        balance = float(order_proj.balance_due)
        req_amount = float(request.amount)
        if req_amount > balance + 0.005:
            _overage_as_tip = money_round(req_amount - balance)
            import logging
            logging.getLogger("kindpos.payment").warning(
                "Payment amount $%.2f exceeded balance_due $%.2f on %s — "
                "clamping sale to balance_due and routing $%.2f to tip.",
                req_amount, balance, request.order_id, _overage_as_tip,
            )
            request = request.model_copy(update={"amount": Decimal(str(balance))})

    result = await manager.initiate_sale(request, tax=order_tax)

    # Emit the overage-as-tip TIP_ADJUSTED only on successful approval.
    if (
        _overage_as_tip > 0
        and hasattr(result, "status")
        and result.status == TransactionStatus.APPROVED
    ):
        tip_evt = tip_adjusted(
            terminal_id=settings.terminal_id,
            order_id=request.order_id,
            payment_id=request.transaction_id,
            tip_amount=_overage_as_tip,
        )
        await ledger.append(tip_evt)

    # Return HTTP error if the transaction was not approved
    if hasattr(result, 'status'):
        if result.status == TransactionStatus.DECLINED:
            raise HTTPException(status_code=402, detail=result.processor_message or "Declined")
        if result.status == TransactionStatus.CANCELLED:
            raise HTTPException(status_code=400, detail=result.processor_message or "Cancelled")
        if result.status == TransactionStatus.ERROR:
            msg = result.processor_message or (result.error.message if result.error else "Transaction error")
            raise HTTPException(status_code=502, detail=msg)

    # 4. Auto-close order if fully paid (same as cash route)
    if hasattr(result, 'status') and result.status == TransactionStatus.APPROVED:
        events = await ledger.get_events_by_correlation(request.order_id)
        order = project_order(events)
        if order and order.is_fully_paid and order.status != "closed":
            close_evt = order_closed(
                terminal_id=settings.terminal_id,
                order_id=request.order_id,
                total=order.total,
            )
            await ledger.append(close_evt)

    return result


# =============================================================================
# CASH PAYMENT
# =============================================================================

class CashPaymentRequest(BaseModel):
    order_id: str
    amount: float
    tip: float = 0.0
    payment_method: str = "cash"
    seat_numbers: Optional[list[int]] = None


@router.post("/cash")
async def process_cash_payment(
    request: CashPaymentRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Process a cash payment — immediately confirmed, closes order if fully paid."""
    if request.tip < 0:
        raise HTTPException(status_code=400, detail="Tip amount cannot be negative")
    # Get current order state
    events = await ledger.get_events_by_correlation(request.order_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")
    order = project_order(events)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")

    if order.status in ("closed", "voided"):
        raise HTTPException(status_code=400, detail=f"Cannot pay on {order.status} order")

    # Guard: reject if order is already fully paid (prevents double-charge on rapid taps)
    if order.is_fully_paid:
        raise HTTPException(status_code=400, detail="Order is already fully paid")

    # Apply cash dual-pricing discount only on the FIRST cash payment
    # (no prior confirmed payments). Applying on every partial payment
    # would incorrectly reduce order.total and break split-tender flows.
    # Skip entirely when the rate is out of (0, 1) — otherwise partial
    # seat payments get discounted to cover unpaid seats, auto-closing
    # the order before other seats can pay.
    existing_confirmed = [p for p in order.payments if p.status == "confirmed"]
    rate = settings.cash_discount_rate
    if not existing_confirmed and request.payment_method == "cash" and 0 < rate < 1:
        # Cap the discount so partial (seat-level) payments don't inflate
        # the discount to include unpaid seats' value.
        naive_discount = money_round(order.total - request.amount)
        max_discount = money_round(request.amount * rate / (1 - rate))
        cash_discount = max(0, min(naive_discount, max_discount))
        if cash_discount > 0:
            discount_evt = create_event(
                event_type=EventType.DISCOUNT_APPROVED,
                terminal_id=settings.terminal_id,
                payload={
                    "order_id": request.order_id,
                    "discount_type": "cash_dual_pricing",
                    "amount": cash_discount,
                    "reason": "Cash dual-pricing discount",
                },
                correlation_id=request.order_id,
            )
            await ledger.append(discount_evt)
            # Re-project so order.total reflects the discount
            events = await ledger.get_events_by_correlation(request.order_id)
            order = project_order(events)

    payment_id = f"pay_{uuid.uuid4().hex[:8]}"

    # Defense in depth: clamp sale_amount at balance_due and route any
    # excess into the payment's tip. Cash payments are already clamped
    # client-side by `Math.min(enteredAmount, remaining)`, but `remaining`
    # relies on the frontend's own tax math — the tender identity stays
    # safe even when those disagree.
    balance = float(order.balance_due)
    req_amount = float(request.amount)
    overage_as_tip = 0.0
    if req_amount > balance + 0.005:
        overage_as_tip = money_round(req_amount - balance)
        import logging
        logging.getLogger("kindpos.payment").warning(
            "Cash amount $%.2f exceeded balance_due $%.2f on %s — "
            "clamping sale to balance_due and routing $%.2f to tip.",
            req_amount, balance, request.order_id, overage_as_tip,
        )
        sale_amount = money_round(balance)
    else:
        sale_amount = money_round(req_amount)

    # Emit PAYMENT_INITIATED (sale amount only — tip tracked via TIP_ADJUSTED)
    init_evt = payment_initiated(
        terminal_id=settings.terminal_id,
        order_id=request.order_id,
        payment_id=payment_id,
        amount=sale_amount,
        method="cash",
        seat_numbers=request.seat_numbers,
    )
    await ledger.append(init_evt)

    # Cash is immediately confirmed
    confirm_evt = payment_confirmed(
        terminal_id=settings.terminal_id,
        order_id=request.order_id,
        payment_id=payment_id,
        transaction_id=f"cash_{uuid.uuid4().hex[:8]}",
        amount=sale_amount,
        tax=order.tax,
        seat_numbers=request.seat_numbers,
    )
    await ledger.append(confirm_evt)

    # Record tip: request.tip plus any overage we rerouted from the
    # sale leg. Emit a single TIP_ADJUSTED event so the projection's
    # last-write-wins semantics remain intact.
    total_tip = money_round(float(request.tip or 0) + overage_as_tip)
    if total_tip > 0:
        tip_evt = tip_adjusted(
            terminal_id=settings.terminal_id,
            order_id=request.order_id,
            payment_id=payment_id,
            tip_amount=total_tip,
        )
        await ledger.append(tip_evt)

    # Re-project to check if fully paid
    events = await ledger.get_events_by_correlation(request.order_id)
    order = project_order(events)

    # Auto-close if fully paid
    if order and order.is_fully_paid and order.status != "closed":
        close_evt = order_closed(
            terminal_id=settings.terminal_id,
            order_id=request.order_id,
            total=order.total,
        )
        await ledger.append(close_evt)

    return {
        "success": True,
        "payment_id": payment_id,
        "order_id": request.order_id,
        "amount": sale_amount,
        "tip": request.tip,
    }


# =============================================================================
# TIP ADJUSTMENT (post-payment)
# =============================================================================

class TipAdjustRequest(BaseModel):
    order_id: str
    payment_id: str
    tip_amount: float


@router.post("/tip-adjust")
async def adjust_tip(
    request: TipAdjustRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Adjust tip on an existing payment (e.g. from signed credit card receipt)."""
    if request.tip_amount < 0:
        raise HTTPException(status_code=400, detail="Tip amount cannot be negative")
    events = await ledger.get_events_by_correlation(request.order_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")
    order = project_order(events)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")

    # Find the payment
    target = None
    for p in order.payments:
        if p.payment_id == request.payment_id:
            target = p
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"Payment {request.payment_id} not found")
    if target.status != "confirmed":
        raise HTTPException(status_code=400, detail="Can only adjust tips on confirmed payments")

    # Get previous tip from existing TIP_ADJUSTED events
    previous_tip = 0.0
    for e in events:
        if (e.event_type == EventType.TIP_ADJUSTED
                and e.payload.get("payment_id") == request.payment_id):
            previous_tip = e.payload.get("tip_amount", 0.0)

    tip_amt = money_round(request.tip_amount)
    evt = tip_adjusted(
        terminal_id=settings.terminal_id,
        order_id=request.order_id,
        payment_id=request.payment_id,
        tip_amount=tip_amt,
        previous_tip=previous_tip,
    )
    await ledger.append(evt)

    # Send tip adjust to payment device so it's included in batch settlement
    device_adjusted = False
    device_error = None
    manager = get_payment_manager(ledger)
    await _ensure_devices(manager)
    device = manager.get_device_for_terminal(settings.terminal_id)
    if device and hasattr(device, 'adjust_tip') and device.config and device.config.protocol != "mock":
        try:
            from decimal import Decimal
            result = await device.adjust_tip(target.payment_id, Decimal(str(tip_amt)))
            device_adjusted = result.status.value == "APPROVED"
            if not device_adjusted:
                device_error = f"Device tip adjust returned {result.status.value}"
        except Exception as e:
            device_error = f"Device tip adjust exception: {e}"
    if device_error:
        import logging
        logging.getLogger("kindpos.payment").warning(
            f"Tip adjust for {request.payment_id} saved to ledger but device sync failed: {device_error}"
        )

    return {
        "success": True,
        "order_id": request.order_id,
        "payment_id": request.payment_id,
        "tip_amount": tip_amt,
        "previous_tip": previous_tip,
        "device_adjusted": device_adjusted,
        "device_warning": device_error,
    }


@router.post("/zero-unadjusted")
async def zero_unadjusted_tips(
    server_id: Opt[str] = None,
    ledger: EventLedger = Depends(get_ledger),
):
    """Bulk-zero all unadjusted card tips for the current business day.

    Emits a TIP_ADJUSTED event with tip_amount=0 for every confirmed card
    payment that has no existing TIP_ADJUSTED event.  Optionally scoped to
    a single server via ?server_id=.
    """
    boundary = await ledger.get_last_day_close_sequence()
    all_events = await ledger.get_events_since(boundary, limit=50000)
    orders = project_orders(all_events)

    # Build set of payment_ids that already have a TIP_ADJUSTED event
    adjusted_pids = set()
    for e in all_events:
        if e.event_type == EventType.TIP_ADJUSTED:
            pid = e.payload.get("payment_id")
            if pid:
                adjusted_pids.add(pid)

    zeroed = 0
    for order in orders.values():
        if order.status not in ("closed", "paid"):
            continue
        if server_id and order.server_id != server_id:
            continue
        for p in order.payments:
            if p.status != "confirmed":
                continue
            if p.method == "cash":
                continue
            if p.payment_id in adjusted_pids:
                continue
            evt = tip_adjusted(
                terminal_id=settings.terminal_id,
                order_id=order.order_id,
                payment_id=p.payment_id,
                tip_amount=0.0,
                previous_tip=0.0,
            )
            await ledger.append(evt)
            zeroed += 1

    return {"success": True, "zeroed_count": zeroed}


# =============================================================================
# REFUND
# =============================================================================

class RefundRequest(BaseModel):
    order_id: str
    payment_id: str
    amount: Optional[float] = None  # None = full refund of original payment
    reason: str = "Customer refund"
    approved_by: str  # Manager approval required


@router.post("/refund")
async def process_refund(
    request: RefundRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Process a refund on a confirmed payment. Requires manager approval."""
    if not request.approved_by or not request.approved_by.strip():
        raise HTTPException(status_code=403, detail="Manager approval required for refunds")

    events = await ledger.get_events_by_correlation(request.order_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")
    order = project_order(events)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")

    # Find the target payment
    target = None
    for p in order.payments:
        if p.payment_id == request.payment_id:
            target = p
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"Payment {request.payment_id} not found")
    if target.status != "confirmed":
        raise HTTPException(status_code=400, detail="Can only refund confirmed payments")

    # Check for existing refund on this payment
    existing_refunds = [
        e for e in events
        if e.event_type == EventType.PAYMENT_REFUNDED
        and e.payload.get("payment_id") == request.payment_id
    ]
    already_refunded = money_round(sum(e.payload.get("amount", 0) for e in existing_refunds))

    refund_amount = money_round(request.amount if request.amount is not None else target.amount)
    if refund_amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be positive")
    if refund_amount > money_round(target.amount - already_refunded):
        raise HTTPException(
            status_code=400,
            detail=f"Refund amount ${refund_amount:.2f} exceeds remaining refundable "
                   f"${money_round(target.amount - already_refunded):.2f}"
        )

    from ...core.events import cash_refund_due
    refund_evt = cash_refund_due(
        terminal_id=settings.terminal_id,
        order_id=request.order_id,
        payment_id=request.payment_id,
        amount=refund_amount,
        reason=request.reason,
    )
    await ledger.append(refund_evt)

    return {
        "success": True,
        "order_id": request.order_id,
        "payment_id": request.payment_id,
        "refund_amount": refund_amount,
        "reason": request.reason,
        "approved_by": request.approved_by,
    }


@router.get("/device-status")
async def get_device_status(manager: PaymentManager = Depends(get_payment_manager)):
    """All devices: id, name, status, last_checked."""
    return [
        {
            "id": d.config.device_id if d.config else "unknown",
            "name": d.config.name if d.config else "Unknown",
            "status": d.status,
            "ip": d.config.ip_address if d.config else None
        }
        for d in manager._devices.values()
    ]


@router.post("/batch-settle")
async def batch_settle(ledger: EventLedger = Depends(get_ledger)):
    """Send BatchClose to the payment terminal to settle with the processor."""
    manager = get_payment_manager(ledger)
    await _ensure_devices(manager)

    device = manager.get_device_for_terminal(settings.terminal_id)
    if not device:
        return {"success": False, "error": "No payment device registered"}

    is_mock = device.config and device.config.protocol == "mock"
    if is_mock:
        return {
            "success": True,
            "using_mock": True,
            "batch_id": "MOCK",
            "transaction_count": 0,
            "total_amount": "0.00",
            "status": "SUCCESS",
        }

    try:
        result = await device.close_batch()
        return {
            "success": result.status.value == "SUCCESS",
            "using_mock": False,
            "batch_id": result.batch_id,
            "transaction_count": result.transaction_count,
            "total_amount": str(result.total_amount),
            "status": result.status.value,
            "error": result.error.message if result.error else None,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Batch settle failed: {e}")
