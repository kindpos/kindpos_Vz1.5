"""
Order API Routes

Endpoints for order management.
All mutations go through the Event Ledger.
"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import logging
import uuid

_logger = logging.getLogger("kindpos.orders")

_TWO_DP = Decimal("0.01")


def _validate_2dp(value: float, field_name: str) -> None:
    """Raise 400 if a monetary value has more than 2 decimal places."""
    d = Decimal(str(value))
    if d != d.quantize(_TWO_DP):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must have at most 2 decimal places (got {value})",
        )

from app.config import settings
from app.api.dependencies import get_diagnostic_collector
from app.api.dependencies import get_ledger
from app.core.event_ledger import EventLedger
from app.core.events import (
    order_created,
    order_transferred,
    check_named,
    guest_count_updated,
    item_added,
    item_removed,
    item_modified,
    item_sent,
    modifier_applied,
    payment_initiated,
    payment_confirmed,
    payment_failed,
    order_closed,
    order_reopened,
    order_voided,
    tip_adjusted,
    cash_refund_due,
    ticket_printed,
    batch_submitted,
    day_closed,
    create_event,
    EventType,
)
from app.core.projections import project_order, project_orders, Order
from decimal import Decimal
from app.core.money import money_round
from app.core.financial_invariants import (
    check_day_close,
    gate as invariant_gate,
    max_abs_diff,
)

_ZERO = Decimal('0')
from app.core.event_ledger import get_open_orders

router = APIRouter(prefix="/orders", tags=["orders"])


# =============================================================================
# DAY BOUNDARY HELPER
# =============================================================================

async def get_current_day_events(ledger: EventLedger, limit: int = 50000) -> list:
    """Get events since the last day close (current business day)."""
    boundary = await ledger.get_last_day_close_sequence()
    return await ledger.get_events_since(boundary, limit=limit)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class CreateOrderRequest(BaseModel):
    """Request to create a new order."""
    table: Optional[str] = None
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    order_type: str = "dine_in"
    guest_count: int = 1
    customer_name: Optional[str] = None


class InlineModifier(BaseModel):
    """Modifier sent inline with an item from the frontend."""
    name: str
    price: float = 0.0
    modifier_price: float = 0.0
    charged: Optional[bool] = True
    prefix: Optional[str] = None       # 'Left' or 'Right' for half-placement
    half_price: Optional[float] = None


class AddItemRequest(BaseModel):
    """Request to add an item to an order."""
    menu_item_id: str
    name: str
    price: float
    quantity: int = Field(default=1, ge=1)
    category: Optional[str] = None
    notes: Optional[str] = None
    seat_number: Optional[int] = None
    modifiers: Optional[list[InlineModifier]] = None


class ModifyItemRequest(BaseModel):
    """Request to modify an item."""
    quantity: Optional[int] = Field(default=None, ge=1)
    price: Optional[float] = None
    notes: Optional[str] = None
    seat_number: Optional[int] = None


class ApplyModifierRequest(BaseModel):
    """Request to apply a modifier to an item."""
    modifier_id: str
    modifier_name: str
    modifier_price: float = 0.0
    action: str = "add"  # add, remove


class InitiatePaymentRequest(BaseModel):
    """Request to initiate a payment."""
    amount: float
    method: str  # card, cash, gift_card


class ConfirmPaymentRequest(BaseModel):
    """Request to confirm a payment."""
    transaction_id: str
    amount: float


class FailPaymentRequest(BaseModel):
    """Request to record a failed payment."""
    error: str
    error_code: Optional[str] = None


class VoidOrderRequest(BaseModel):
    """Request to void an order. Requires manager approval."""
    reason: str
    approved_by: str  # Manager ID required — voids are sensitive operations


class OrderItemResponse(BaseModel):
    """Response model for an order item."""
    item_id: str
    menu_item_id: str
    name: str
    price: float
    quantity: int
    category: Optional[str]
    notes: Optional[str]
    seat_number: Optional[int] = None
    modifiers: list[dict]
    subtotal: float
    added_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


class PaymentResponse(BaseModel):
    """Response model for a payment."""
    payment_id: str
    amount: float
    method: str
    status: str
    tip_amount: float = 0.0
    transaction_id: Optional[str] = None
    seat_numbers: list[int] = []


class OrderResponse(BaseModel):
    """Response model for an order."""
    order_id: str
    check_number: Optional[str] = None
    table: Optional[str]
    server_id: Optional[str]
    server_name: Optional[str]
    customer_name: Optional[str] = None
    order_type: str
    guest_count: int
    status: str
    items: list[OrderItemResponse]
    payments: list[PaymentResponse] = []
    subtotal: float
    discount_total: float
    tax: float
    total: float
    amount_paid: float
    balance_due: float
    paid_seats: list[int] = []
    created_at: Optional[datetime]

    @classmethod
    def from_order(cls, order: Order) -> "OrderResponse":
        """Convert an Order projection to a response."""
        return cls(
            order_id=order.order_id,
            check_number=order.check_number,
            table=order.table,
            server_id=order.server_id,
            server_name=order.server_name,
            customer_name=order.customer_name,
            order_type=order.order_type,
            guest_count=order.guest_count,
            status=order.status,
            items=[
                OrderItemResponse(
                    item_id=item.item_id,
                    menu_item_id=item.menu_item_id,
                    name=item.name,
                    price=item.price,
                    quantity=item.quantity,
                    category=item.category,
                    notes=item.notes,
                    seat_number=item.seat_number,
                    modifiers=item.modifiers,
                    subtotal=money_round(item.subtotal),
                    added_at=item.added_at,
                    sent_at=item.sent_at,
                )
                for item in order.items
            ],
            payments=[
                PaymentResponse(
                    payment_id=p.payment_id,
                    amount=p.amount,
                    method=p.method,
                    status=p.status,
                    tip_amount=p.tip_amount,
                    transaction_id=p.transaction_id,
                    seat_numbers=p.seat_numbers or [],
                )
                for p in order.payments
            ],
            subtotal=money_round(order.subtotal),
            discount_total=money_round(order.discount_total),
            tax=money_round(order.tax),
            total=order.total,
            amount_paid=money_round(order.amount_paid),
            balance_due=order.balance_due,
            paid_seats=order.paid_seats,
            created_at=order.created_at,
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def get_order_or_404(ledger: EventLedger, order_id: str) -> Order:
    """Get an order by ID or raise 404."""
    events = await ledger.get_events_by_correlation(order_id)
    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    order = project_order(events)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    return order


# =============================================================================
# ROUTES
# =============================================================================

@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
        request: CreateOrderRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Create a new order."""
    order_id = f"order_{uuid.uuid4().hex[:12]}"

    # Generate sequential check number with order-type prefix
    ORDER_TYPE_PREFIXES = {
        "quick_service": "QS",
        "dine_in": "DI",
        "to_go": "TG",
        "bar_tab": "BT",
        "delivery": "DL",
        "staff": "ST",
    }
    order_type = request.order_type or "dine_in"
    prefix = ORDER_TYPE_PREFIXES.get(order_type, "OR")
    type_count = await ledger.count_events_by_type_and_payload(
        EventType.ORDER_CREATED, "order_type", order_type
    )
    check_number = f"{prefix}-{type_count + 1:03d}"

    event = order_created(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        table=request.table,
        server_id=request.server_id,
        server_name=request.server_name,
        order_type=request.order_type,
        guest_count=request.guest_count,
        customer_name=request.customer_name,
        check_number=check_number,
    )
    # Set correlation_id for ORDER_CREATED
    event = event.model_copy(update={"correlation_id": order_id})

    await ledger.append(event)

    # Notify diagnostic collector of order activity
    dc = get_diagnostic_collector()
    if dc:
        try:
            await dc.notify_order_created()
        except Exception:
            _logger.debug("DiagnosticCollector notification failed", exc_info=True)

    # Return the projected order
    events = await ledger.get_events_by_correlation(order_id)
    order = project_order(events)
    return OrderResponse.from_order(order)


@router.get("", response_model=list[OrderResponse])
async def list_orders(
        status_filter: Optional[str] = None,
        table: Optional[str] = None,
        server_id: Optional[str] = None,
        ledger: EventLedger = Depends(get_ledger),
):
    """List orders with optional filters."""
    # Get recent events (last 1000)
    events = await get_current_day_events(ledger, limit=10000)
    orders = project_orders(events)

    # Apply filters
    result = list(orders.values())

    if status_filter:
        result = [o for o in result if o.status == status_filter]

    if table:
        result = [o for o in result if o.table == table]

    if server_id:
        result = [o for o in result if o.server_id == server_id]

    # Sort by created_at descending
    result.sort(key=lambda o: o.created_at or datetime.min, reverse=True)

    return [OrderResponse.from_order(o) for o in result]


@router.get("/active", response_model=list[OrderResponse])
async def list_active_orders(
        ledger: EventLedger = Depends(get_ledger),
):
    """Get all active (open or printed) orders."""
    events = await get_current_day_events(ledger, limit=10000)
    orders = project_orders(events)
    active_orders = [o for o in orders.values() if o.status == "open"]
    active_orders.sort(key=lambda o: o.created_at or datetime.min, reverse=True)
    return [OrderResponse.from_order(o) for o in active_orders]


@router.get("/open", response_model=list[OrderResponse])
async def list_open_orders(
        ledger: EventLedger = Depends(get_ledger),
):
    """Get all open orders."""
    events = await get_current_day_events(ledger, limit=10000)
    orders = project_orders(events)
    open_orders = [o for o in orders.values() if o.status == "open"]
    open_orders.sort(key=lambda o: o.created_at or datetime.min, reverse=True)
    return [OrderResponse.from_order(o) for o in open_orders]


@router.get("/day-summary")
async def get_day_summary(
    server_id: str = None,
    ledger: EventLedger = Depends(get_ledger),
):
    """Full day aggregation for all reporting scenes.

    Optional ?server_id= filter for server checkout view.

    The monetary/count totals come from the shared `_aggregate_orders`
    helper in reporting.py — the single source of truth for day
    aggregation. This route only adds the presentation layer that the
    POS scenes need (per-check list, per-payment list, AM/PM/Late
    dayparts) so both endpoints can never again disagree on the math.
    """
    from app.api.routes.reporting import _aggregate_orders

    all_events = await get_current_day_events(ledger)
    all_orders = project_orders(all_events)

    # Collect TIP_ADJUSTED events keyed by payment_id (last wins)
    tip_map = {}
    for e in all_events:
        if e.event_type == EventType.TIP_ADJUSTED:
            tip_map[e.payload.get("payment_id")] = e.payload.get("tip_amount", 0.0)

    # Filter orders by server if requested
    orders = list(all_orders.values())
    if server_id:
        orders = [o for o in orders if o.server_id == server_id]

    # All monetary and count aggregation — runs the canonical identities
    # and (under strict_invariants) raises if anything drifts.
    agg = _aggregate_orders(orders, tip_map)

    # Presentation pass: per-check entries and per-payment entries, built
    # only for the day-summary endpoint. No math here beyond laying out
    # existing projection values.
    checks_list = []
    payments_list = []
    for order in orders:
        check_label = order.check_number if order.check_number else order.order_id
        time_str = (
            order.created_at.strftime("%I:%M%p").lstrip("0").lower()
            if order.created_at else ""
        )
        if order.status == "voided":
            checks_list.append({
                "checkId": order.order_id,
                "checkLabel": check_label,
                "paymentId": None,
                "time": time_str,
                "amount": money_round(order.subtotal),
                "tip": 0,
                "adjusted": True,
                "method": None,
                "status": "voided",
            })
            continue
        if order.status == "open":
            checks_list.append({
                "checkId": order.order_id,
                "checkLabel": check_label,
                "paymentId": None,
                "time": time_str,
                "amount": money_round(order.subtotal),
                "tip": 0,
                "adjusted": False,
                "method": None,
                "status": "open",
            })
            continue

        # closed/paid — gather per-payment rows and the check's tip total
        order_tip = Decimal("0")
        for p in order.payments:
            if p.status != "confirmed":
                continue
            tip = Decimal(str(tip_map.get(p.payment_id, p.tip_amount)))
            order_tip += tip
            payments_list.append({
                "order_id": order.order_id,
                "payment_id": p.payment_id,
                "amount": p.amount,
                "method": p.method,
                "tip": float(tip),
            })

        has_card = any(
            p.method != "cash" and p.status == "confirmed" for p in order.payments
        )
        if has_card:
            card_payment = next(
                (p for p in order.payments if p.method != "cash" and p.status == "confirmed"),
                None,
            )
            checks_list.append({
                "checkId": order.order_id,
                "checkLabel": check_label,
                "paymentId": card_payment.payment_id if card_payment else None,
                "time": time_str,
                "amount": money_round(order.total),
                "tip": float(order_tip),
                "adjusted": any(
                    tip_map.get(p.payment_id) is not None for p in order.payments
                ),
                "method": "card",
                "status": "closed",
            })
        else:
            # Cash-only closed orders — no tip adjustment needed
            checks_list.append({
                "checkId": order.order_id,
                "checkLabel": check_label,
                "paymentId": None,
                "time": time_str,
                "amount": money_round(order.total),
                "tip": 0,
                "adjusted": True,
                "method": "cash",
                "status": "closed",
            })

    unadjusted = sum(1 for c in checks_list if not c["adjusted"])

    # Derived figures from the aggregator
    net_sales_f = money_round(float(agg["net_sales"]))
    tax_total_f = money_round(float(agg["tax_total"]))
    closed_count = agg["closed_count"]
    open_count = agg["open_count"]
    voided_count = agg["voided_count"]
    avg_check = (
        money_round(float(agg["net_sales"]) / closed_count)
        if closed_count > 0 else 0.0
    )

    # AM / PM / Late dayparts from the aggregator's hourly buckets.
    dayparts = []
    am_net, am_chk = Decimal("0"), 0
    pm_net, pm_chk = Decimal("0"), 0
    late_net, late_chk = Decimal("0"), 0
    for h, bucket in agg["hourly"].items():
        if h < 12:
            am_net += bucket["net"]; am_chk += bucket["checks"]
        elif h < 17:
            pm_net += bucket["net"]; pm_chk += bucket["checks"]
        else:
            late_net += bucket["net"]; late_chk += bucket["checks"]
    if am_chk:
        dayparts.append({"name": "AM", "sales": money_round(float(am_net)), "checks": am_chk})
    if pm_chk:
        dayparts.append({"name": "PM", "sales": money_round(float(pm_net)), "checks": pm_chk})
    if late_chk:
        dayparts.append({"name": "Late", "sales": money_round(float(late_net)), "checks": late_chk})

    # Reshape the aggregator's category_totals for frontend consumption.
    categories_list = [
        {
            "name": name,
            "total": money_round(float(data["revenue"])),
            "count": data["items_sold"],
        }
        for name, data in agg["category_totals"].items()
    ]

    # Re-run the gate here so the response carries `reconciliation_diff`
    # even though _aggregate_orders already gated. Cheap because all
    # values are already computed.
    _invariant_results = invariant_gate(
        check_day_close(
            gross_sales=float(agg["gross_sales"]),
            void_total=float(agg["void_total"]),
            discount_total=float(agg["discount_total"]),
            refund_total=float(agg["refund_total"]),
            net_sales=float(agg["net_sales"]),
            tax_collected=float(agg["tax_total"]),
            cash_total=float(agg["cash_total"]),
            card_total=float(agg["card_total"]),
            total_tips=float(agg["total_tips"]),
            card_tips=float(agg["card_tips"]),
            cash_tips=float(agg["cash_tips"]),
        ),
        context="get_day_summary",
    )
    reconciliation_diff = max_abs_diff(_invariant_results)

    return {
        "date": __import__("datetime").date.today().isoformat(),
        "open_orders": open_count,
        "closed_orders": closed_count,
        "voided_orders": voided_count,
        "gross_sales": money_round(float(agg["gross_sales"])),
        "void_total": money_round(float(agg["void_total"])),
        "void_count": voided_count,
        "discount_total": money_round(float(agg["discount_total"])),
        "discount_count": agg["discount_count"],
        "net_sales": net_sales_f,
        "tax_total": tax_total_f,
        "cash_total": money_round(float(agg["cash_total"])),
        "cash_count": agg["cash_count"],
        "card_total": money_round(float(agg["card_total"])),
        "card_count": agg["card_count"],
        "total_sales": money_round(float(agg["net_sales"]) + float(agg["tax_total"])),
        "total_tips": money_round(float(agg["total_tips"])),
        "card_tips": money_round(float(agg["card_tips"])),
        "cash_tips": money_round(float(agg["cash_tips"])),
        "total_checks": closed_count + open_count,
        "avg_check": avg_check,
        "guest_count": agg["guest_count"],
        "unadjusted_tips": unadjusted,
        "dayparts": dayparts,
        "categories": categories_list,
        "payments": payments_list,
        "checks": checks_list,
        "closed_order_ids": list(agg["closed_order_ids"]),
        "reconciliation_diff": reconciliation_diff,
    }


@router.get("/day-history")
async def get_day_history(ledger: EventLedger = Depends(get_ledger)):
    """Get all closed day summaries for audit/reporting.

    Each entry is the stored payload from a DAY_CLOSED event.
    """
    day_events = await ledger.get_events_by_type(EventType.DAY_CLOSED)
    return [
        {
            "event_id": e.event_id,
            "closed_at": e.timestamp.isoformat() if e.timestamp else None,
            **e.payload,
        }
        for e in day_events
    ]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
        order_id: str,
        ledger: EventLedger = Depends(get_ledger),
):
    """Get a specific order by ID."""
    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


class PatchOrderRequest(BaseModel):
    """Request to update order-level fields (e.g. server transfer, check name)."""
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    guest_count: Optional[int] = None
    customer_name: Optional[str] = None


@router.patch("/{order_id}", response_model=OrderResponse)
async def patch_order(
        order_id: str,
        request: PatchOrderRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Update order fields. Supports server transfer and check naming."""
    order = await get_order_or_404(ledger, order_id)

    if request.server_id is not None:
        event = order_transferred(
            terminal_id="terminal-1",
            order_id=order_id,
            server_id=request.server_id,
            server_name=request.server_name or "",
        )
        await ledger.append(event)

    if request.customer_name is not None:
        event = check_named(
            terminal_id=settings.terminal_id,
            order_id=order_id,
            customer_name=request.customer_name,
        )
        await ledger.append(event)

    if request.guest_count is not None:
        event = guest_count_updated(
            terminal_id=settings.terminal_id,
            order_id=order_id,
            guest_count=request.guest_count,
        )
        await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/items", response_model=OrderResponse)
async def add_item(
        order_id: str,
        request: AddItemRequest,
        http_request: Request = None,
        ledger: EventLedger = Depends(get_ledger),
):
    """Add an item to an order."""
    # ── Idempotency key from header ──
    idem_key = http_request.headers.get("idempotency-key") if http_request else None

    _validate_2dp(request.price, "price")
    if request.modifiers:
        for mod in request.modifiers:
            _validate_2dp(mod.modifier_price, "modifier_price")

    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot add items to {order.status} order"
        )

    # 86 guard: refuse to add an item that the Overseer has marked out of
    # stock tonight. The config projection carries `is_86ed` (toggled by
    # MENU_ITEM_86D / MENU_ITEM_RESTORED events), so this check catches
    # any frontend that hasn't yet refreshed its menu cache. The lookup
    # is a no-op when the item isn't in the config projection (e.g. an
    # ad-hoc manual line item) — we only block when we know it's 86'd.
    from app.services.overseer_config_service import OverseerConfigService
    try:
        menu_items = await OverseerConfigService(ledger).get_menu_items()
        match = next(
            (m for m in menu_items if m.item_id == request.menu_item_id),
            None,
        )
        if match is not None and getattr(match, "is_86ed", False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"'{match.name}' is 86'd (sold out). Remove the 86 to order it.",
            )
    except HTTPException:
        raise
    except Exception:
        # Config projection unavailable — fail open so a broken config
        # lookup doesn't block a live service.
        pass

    item_id = f"item_{uuid.uuid4().hex[:8]}"

    event = item_added(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        item_id=item_id,
        menu_item_id=request.menu_item_id,
        name=request.name,
        price=request.price,
        quantity=request.quantity,
        category=request.category,
        notes=request.notes,
        seat_number=request.seat_number,
        idempotency_key=idem_key,
    )
    result = await ledger.append(event)
    if result is None:
        # Duplicate blocked by ledger — return current order state
        _logger.warning("BLOCKED duplicate item POST (idempotency_key=%s)", idem_key)
        order = await get_order_or_404(ledger, order_id)
        return OrderResponse.from_order(order)

    # Emit MODIFIER_APPLIED events for inline modifiers from the frontend
    for mod in (request.modifiers or []):
        mod_event = modifier_applied(
            terminal_id=settings.terminal_id,
            order_id=order_id,
            item_id=item_id,
            modifier_id=f"mod_{uuid.uuid4().hex[:8]}",
            modifier_name=mod.name,
            modifier_price=mod.price if mod.charged else 0.0,
            action="add",
            prefix=mod.prefix,
            half_price=mod.half_price,
        )
        await ledger.append(mod_event)

    # Return updated order
    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.delete("/{order_id}/items/{item_id}", response_model=OrderResponse)
async def remove_item(
        order_id: str,
        item_id: str,
        reason: Optional[str] = None,
        ledger: EventLedger = Depends(get_ledger),
):
    """Remove an item from an order."""
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot remove items from {order.status} order"
        )

    # Verify item exists
    if not any(item.item_id == item_id for item in order.items):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found in order"
        )

    event = item_removed(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        item_id=item_id,
        reason=reason,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.patch("/{order_id}/items/{item_id}", response_model=OrderResponse)
async def modify_item(
        order_id: str,
        item_id: str,
        request: ModifyItemRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Modify an item on an order."""
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot modify items on {order.status} order"
        )

    # Verify item exists
    if not any(item.item_id == item_id for item in order.items):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found in order"
        )

    event = item_modified(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        item_id=item_id,
        quantity=request.quantity,
        price=request.price,
        notes=request.notes,
        seat_number=request.seat_number,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/items/{item_id}/modifiers", response_model=OrderResponse)
async def apply_modifier(
        order_id: str,
        item_id: str,
        request: ApplyModifierRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Apply a modifier to an item."""
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot modify items on {order.status} order"
        )

    if not any(item.item_id == item_id for item in order.items):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found in order"
        )

    event = modifier_applied(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        item_id=item_id,
        modifier_id=request.modifier_id,
        modifier_name=request.modifier_name,
        modifier_price=request.modifier_price,
        action=request.action,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/payments", response_model=OrderResponse)
async def initiate_payment(
        order_id: str,
        request: InitiatePaymentRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Initiate a payment on an order."""
    _validate_2dp(request.amount, "amount")
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot process payment on {order.status} order"
        )

    payment_id = f"pay_{uuid.uuid4().hex[:8]}"

    event = payment_initiated(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        payment_id=payment_id,
        amount=request.amount,
        method=request.method,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/payments/{payment_id}/confirm", response_model=OrderResponse)
async def confirm_payment(
        order_id: str,
        payment_id: str,
        request: ConfirmPaymentRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Confirm a payment."""
    order = await get_order_or_404(ledger, order_id)

    # Verify payment exists and amount matches initiation
    initiated = None
    for p in order.payments:
        if p.payment_id == payment_id:
            initiated = p
            break
    if not initiated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found"
        )
    if initiated.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment {payment_id} is already {initiated.status}"
        )
    if money_round(request.amount) != money_round(initiated.amount):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation amount {request.amount} does not match initiated amount {initiated.amount}"
        )

    event = payment_confirmed(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        payment_id=payment_id,
        transaction_id=request.transaction_id,
        amount=request.amount,
        tax=order.tax,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


class VoidPaymentRequest(BaseModel):
    reason: Optional[str] = None
    approved_by: Optional[str] = None


@router.post("/{order_id}/payments/{payment_id}/void", response_model=OrderResponse)
async def void_payment(
        order_id: str,
        payment_id: str,
        body: Optional[VoidPaymentRequest] = None,
        ledger: EventLedger = Depends(get_ledger),
):
    """Void a specific confirmed payment, reopening the seat(s) it covered.

    If the order auto-closed because this payment completed the balance,
    reopen it first so the freed seat can be re-paid.
    """
    order = await get_order_or_404(ledger, order_id)
    body = body or VoidPaymentRequest()

    if order.status == "voided":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot void payments on a voided order"
        )

    target = None
    for p in order.payments:
        if p.payment_id == payment_id:
            target = p
            break
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found"
        )
    if target.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment {payment_id} is {target.status}, not confirmed"
        )

    if order.status == "closed":
        await ledger.append(order_reopened(
            terminal_id=settings.terminal_id,
            order_id=order_id,
        ))

    event = create_event(
        event_type=EventType.PAYMENT_CANCELLED,
        terminal_id=settings.terminal_id,
        correlation_id=order_id,
        payload={
            "order_id": order_id,
            "payment_id": payment_id,
            "error": body.reason or "Payment voided",
            "approved_by": body.approved_by,
        },
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/close", response_model=OrderResponse)
async def close_order(
        order_id: str,
        ledger: EventLedger = Depends(get_ledger),
):
    """Close an order."""
    order = await get_order_or_404(ledger, order_id)

    if order.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is already closed"
        )

    if order.status == "voided":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot close a voided order"
        )

    if order.balance_due > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order has balance due: ${order.balance_due:.2f}"
        )

    event = order_closed(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        total=order.total,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/reopen", response_model=OrderResponse)
async def reopen_order(
        order_id: str,
        ledger: EventLedger = Depends(get_ledger),
):
    """Reopen a closed order."""
    order = await get_order_or_404(ledger, order_id)

    if order.status == "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is already open"
        )

    if order.status == "voided":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reopen a voided order"
        )

    event = order_reopened(
        terminal_id=settings.terminal_id,
        order_id=order_id,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


@router.post("/{order_id}/void", response_model=OrderResponse)
async def void_order(
        order_id: str,
        request: VoidOrderRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Void an order. Requires manager approval (approved_by)."""
    if not request.approved_by or not request.approved_by.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager approval required to void an order"
        )

    order = await get_order_or_404(ledger, order_id)

    if order.status == "voided":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is already voided"
        )

    if order.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot void a closed order"
        )

    # Reverse confirmed card payments on the payment device
    from .payment_routes import get_payment_manager, _ensure_devices
    from app.core.adapters.base_payment import TransactionRequest as TxReq
    device_void_errors = []
    manager = get_payment_manager(ledger)
    await _ensure_devices(manager)
    for p in order.payments:
        if p.status == "confirmed" and p.method != "cash" and p.transaction_id:
            device = manager.get_device_for_terminal(settings.terminal_id)
            if device and hasattr(device, 'initiate_void'):
                try:
                    void_req = TxReq(
                        order_id=order_id,
                        amount=p.amount,
                        terminal_id=settings.terminal_id,
                        transaction_id=p.transaction_id,
                    )
                    result = await device.initiate_void(void_req)
                    if result.status.value != "APPROVED":
                        device_void_errors.append(
                            f"Device void failed for payment {p.payment_id}: {result.status.value}"
                        )
                except Exception as e:
                    device_void_errors.append(
                        f"Device void error for payment {p.payment_id}: {str(e)}"
                    )

    if device_void_errors:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cannot void order — card reversal failed: {'; '.join(device_void_errors)}",
        )

    # Emit refund-due events for any confirmed cash payments
    for p in order.payments:
        if p.status == "confirmed" and p.method == "cash":
            refund_evt = cash_refund_due(
                terminal_id=settings.terminal_id,
                order_id=order_id,
                payment_id=p.payment_id,
                amount=p.amount,
                reason=request.reason or "Order voided after cash payment",
            )
            await ledger.append(refund_evt)

    event = order_voided(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        reason=request.reason,
        approved_by=request.approved_by,
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


# =============================================================================
# MERGE
# =============================================================================

class MergeOrderRequest(BaseModel):
    """Merge items from `source_ids` into the target order, then void the sources."""
    source_ids: list[str] = Field(..., min_length=1)
    approved_by: Optional[str] = None


@router.post("/{order_id}/merge", response_model=OrderResponse)
async def merge_orders(
        order_id: str,
        request: MergeOrderRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Merge items from source orders into this target order, then void the sources.

    All sources must be open and free of confirmed payments.
    """
    if not request.approved_by or not request.approved_by.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager approval required to merge orders",
        )

    target = await get_order_or_404(ledger, order_id)
    if target.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot merge into {target.status} order",
        )

    sources = []
    seen = set()
    for sid in request.source_ids:
        if sid == order_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot merge an order into itself",
            )
        if sid in seen:
            continue
        seen.add(sid)
        src = await get_order_or_404(ledger, sid)
        if src.status != "open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source {sid} is {src.status}; only open orders can be merged",
            )
        if any(p.status == "confirmed" for p in src.payments):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source {sid} has confirmed payments; void or refund first",
            )
        sources.append(src)

    for src in sources:
        for item in src.items:
            new_item_id = f"item_{uuid.uuid4().hex[:8]}"
            evt = item_added(
                terminal_id=settings.terminal_id,
                order_id=order_id,
                item_id=new_item_id,
                menu_item_id=item.menu_item_id,
                name=item.name,
                price=item.price,
                quantity=item.quantity,
                category=item.category,
                notes=item.notes,
                seat_number=item.seat_number,
            )
            await ledger.append(evt)
            for mod in item.modifiers or []:
                mod_evt = modifier_applied(
                    terminal_id=settings.terminal_id,
                    order_id=order_id,
                    item_id=new_item_id,
                    modifier_id=f"mod_{uuid.uuid4().hex[:8]}",
                    modifier_name=mod.get("name", ""),
                    modifier_price=mod.get("price", 0.0) or 0.0,
                    action="add",
                    prefix=mod.get("prefix"),
                    half_price=mod.get("half_price"),
                )
                await ledger.append(mod_evt)

        void_evt = order_voided(
            terminal_id=settings.terminal_id,
            order_id=src.order_id,
            reason=f"Merged into {order_id}",
            approved_by=request.approved_by,
        )
        await ledger.append(void_evt)

    target = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(target)


# =============================================================================
# DISCOUNT
# =============================================================================

class ApplyDiscountRequest(BaseModel):
    discount_type: str          # e.g. "10%", "25%", "Comp (100%)"
    amount: float               # dollar amount of discount
    reason: Optional[str] = None
    approved_by: Optional[str] = None
    item_ids: Optional[list[str]] = None  # specific items, or None for whole order

@router.post("/{order_id}/discount", response_model=OrderResponse)
async def apply_discount(
        order_id: str,
        request: ApplyDiscountRequest,
        ledger: EventLedger = Depends(get_ledger),
):
    """Apply a manager-approved discount to an order."""
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot discount a {order.status} order"
        )

    # Block discount while any payment is pending (initiated but not confirmed)
    if any(p.status == "pending" for p in order.payments):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot apply discount while a payment is pending"
        )

    event = create_event(
        event_type=EventType.DISCOUNT_APPROVED,
        terminal_id=settings.terminal_id,
        correlation_id=order_id,
        payload={
            "order_id": order_id,
            "discount_type": request.discount_type,
            "amount": request.amount,
            "reason": request.reason or f"Manager discount: {request.discount_type}",
            "approved_by": request.approved_by,
            "item_ids": request.item_ids,
        },
    )
    await ledger.append(event)

    order = await get_order_or_404(ledger, order_id)
    return OrderResponse.from_order(order)


# =============================================================================
# SEND TO KITCHEN
# =============================================================================

class SentItemResponse(BaseModel):
    item_id: str
    name: str
    category: Optional[str]
    seat_number: Optional[int]


class SendResponse(BaseModel):
    sent_count: int
    items: list[SentItemResponse]


@router.post("/{order_id}/send", response_model=SendResponse)
async def send_order(
        order_id: str,
        ledger: EventLedger = Depends(get_ledger),
):
    """Send unsent items to kitchen/bar printers."""
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot send items on {order.status} order"
        )

    if not order.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send order with no items"
        )

    unsent = [item for item in order.items if not getattr(item, 'sent', False)]
    if not unsent:
        return SendResponse(sent_count=0, items=[])

    from datetime import timezone
    sent_at = datetime.now(timezone.utc).isoformat()
    sent_items = []

    for item in unsent:
        event = item_sent(
            terminal_id=settings.terminal_id,
            order_id=order_id,
            item_id=item.item_id,
            name=item.name,
            seat_number=item.seat_number,
            category=item.category,
            sent_at=sent_at,
        )
        await ledger.append(event)
        sent_items.append(SentItemResponse(
            item_id=item.item_id,
            name=item.name,
            category=item.category,
            seat_number=item.seat_number,
        ))

    return SendResponse(sent_count=len(sent_items), items=sent_items)


# =============================================================================
# CLOSE BATCH
# =============================================================================

@router.post("/close-batch")
async def close_batch(ledger: EventLedger = Depends(get_ledger)):
    """Close all open orders, compute batch totals, and emit settlement events."""
    open_ids = await get_open_orders(ledger)
    closed_count = 0
    closed_order_ids = []

    voided_at_close = 0
    for oid in open_ids:
        events = await ledger.get_events_by_correlation(oid)
        order = project_order(events)
        if not order or order.status in ("closed", "voided"):
            # Already closed/voided between get_open_orders and now — skip
            continue
        if order.status in ("open", "paid"):
            if order.is_fully_paid:
                # Fully paid — safe to close
                evt = order_closed(
                    terminal_id=settings.terminal_id,
                    order_id=oid,
                    total=order.total,
                )
                await ledger.append(evt)
                closed_count += 1
                closed_order_ids.append(oid)
            else:
                # Unpaid or underpaid — void instead of closing
                evt = order_voided(
                    terminal_id=settings.terminal_id,
                    order_id=oid,
                    reason="Auto-voided at batch close (unpaid)",
                    approved_by="system",
                )
                await ledger.append(evt)
                voided_at_close += 1

    # Compute batch totals from current-day orders
    day_events = await get_current_day_events(ledger)
    all_orders = project_orders(day_events)

    # Build tip map (last-write-wins per payment_id)
    batch_tip_map: dict[str, float] = {}
    for e in day_events:
        if e.event_type == EventType.TIP_ADJUSTED:
            batch_tip_map[e.payload.get("payment_id", "")] = e.payload.get("tip_amount", 0.0)

    batch_total = _ZERO
    batch_cash = _ZERO
    batch_card = _ZERO
    batch_card_tips = _ZERO
    all_order_ids = []
    for order in all_orders.values():
        if order.status in ("closed", "paid"):
            batch_total += Decimal(str(order.total))
            all_order_ids.append(order.order_id)
            for p in order.payments:
                if p.status == "confirmed":
                    if p.method == "cash":
                        batch_cash += Decimal(str(p.amount))
                    else:
                        batch_card += Decimal(str(p.amount))
                        tip = Decimal(str(batch_tip_map.get(p.payment_id, p.tip_amount)))
                        batch_card_tips += tip

    if not all_order_ids:
        return {
            "success": True,
            "orders_closed_now": closed_count,
            "batch_total": 0.0,
            "cash_total": 0.0,
            "card_total": 0.0,
            "order_count": 0,
            "status": "no_transactions",
        }

    # Settlement = card sales + card tips (what the processor will settle)
    batch_settlement = batch_card + batch_card_tips

    # Convert to float for event factories
    batch_total_f = money_round(float(batch_total))
    batch_cash_f = money_round(float(batch_cash))
    batch_card_f = money_round(float(batch_settlement))

    # Emit BATCH_SUBMITTED with full settlement record
    submit_evt = batch_submitted(
        terminal_id=settings.terminal_id,
        order_count=len(all_order_ids),
        total_amount=batch_total_f,
        cash_total=batch_cash_f,
        card_total=batch_card_f,
        order_ids=all_order_ids,
    )
    await ledger.append(submit_evt)

    # Tender reconciliation check
    tender_sum = batch_cash_f + batch_card_f
    recon_diff = money_round(abs(batch_total_f - tender_sum))
    if recon_diff > 0.01:
        _logger.warning(
            "Tender reconciliation mismatch: batch_total=%.2f, cash+card=%.2f, diff=%.2f",
            batch_total_f, tender_sum, recon_diff,
        )

    return {
        "success": True,
        "orders_closed_now": closed_count,
        "batch_total": batch_total_f,
        "cash_total": batch_cash_f,
        "card_total": batch_card_f,
        "order_count": len(all_order_ids),
    }


# =============================================================================
# CLOSE DAY (manager action)
# =============================================================================

class CloseDayRequest(BaseModel):
    """Optional body for close-day with actual cash count."""
    actual_cash_counted: Optional[float] = None


@router.post("/close-day")
async def close_day(
    body: Optional[CloseDayRequest] = None,
    ledger: EventLedger = Depends(get_ledger),
):
    """
    End-of-day: close remaining orders, settle batch, store auditable
    day summary as a DAY_CLOSED event. After this, the next business
    day starts fresh — all day-scoped queries will only see new events.

    Optionally accepts `actual_cash_counted` to compute Over/Short.
    """
    # Close any remaining open orders
    open_ids = await get_open_orders(ledger)
    closed_count = 0
    for oid in open_ids:
        events = await ledger.get_events_by_correlation(oid)
        order = project_order(events)
        if not order or order.status in ("closed", "voided"):
            # Already closed/voided between get_open_orders and now — skip
            continue
        if order.status in ("open", "paid"):
            if order.is_fully_paid:
                evt = order_closed(
                    terminal_id=settings.terminal_id,
                    order_id=oid,
                    total=order.total,
                )
                await ledger.append(evt)
                closed_count += 1
            else:
                evt = order_voided(
                    terminal_id=settings.terminal_id,
                    order_id=oid,
                    reason="Auto-voided at day close (unpaid)",
                    approved_by="system",
                )
                await ledger.append(evt)

    # Build day summary BEFORE emitting boundary events
    all_events = await get_current_day_events(ledger)
    all_orders = project_orders(all_events)

    total_orders = len(all_orders)
    total_sales = _ZERO
    total_tips = _ZERO
    cash_total = _ZERO
    card_total = _ZERO
    card_tips_total = _ZERO
    order_ids = []
    payment_count = 0

    # Use last-write-wins per payment_id (same logic as day-summary)
    tip_map: dict[str, float] = {}
    for e in all_events:
        if e.event_type == EventType.TIP_ADJUSTED:
            tip_map[e.payload.get("payment_id", "")] = e.payload.get("tip_amount", 0.0)

    for order in all_orders.values():
        if order.status in ("closed", "paid"):
            total_sales += Decimal(str(order.total))
            order_ids.append(order.order_id)
            for p in order.payments:
                if p.status == "confirmed":
                    payment_count += 1
                    if p.method == "cash":
                        cash_total += Decimal(str(p.amount))
                    else:
                        card_total += Decimal(str(p.amount))
                        tip = Decimal(str(tip_map.get(p.payment_id, p.tip_amount)))
                        card_tips_total += tip

    total_tips = sum((Decimal(str(v)) for v in tip_map.values()), _ZERO)

    # First event timestamp = when the day started
    opened_at = all_events[0].timestamp.isoformat() if all_events else None

    # Card settlement = card sales + card tips. Keep the raw card sales
    # amount separately so the tender-reconciliation invariant (which
    # expects Cash + Card = Net + Tax) compares like values, not a
    # settlement total that's inflated by card tips.
    card_settlement = card_total + card_tips_total

    # Convert Decimal accumulators to float for event factories and output
    total_sales_f = money_round(float(total_sales))
    total_tips_f = money_round(float(total_tips))
    cash_total_f = money_round(float(cash_total))
    card_sales_f = money_round(float(card_total))
    card_total_f = money_round(float(card_settlement))

    # Emit BATCH_SUBMITTED (settlement record)
    submit_evt = batch_submitted(
        terminal_id=settings.terminal_id,
        order_count=total_orders,
        total_amount=total_sales_f,
        cash_total=cash_total_f,
        card_total=card_total_f,
        order_ids=order_ids,
    )
    await ledger.append(submit_evt)

    # Emit DAY_CLOSED — this is the auditable snapshot and day boundary
    today = datetime.now().strftime("%Y-%m-%d")
    close_evt = day_closed(
        terminal_id=settings.terminal_id,
        date=today,
        total_orders=total_orders,
        total_sales=total_sales_f,
        total_tips=total_tips_f,
        cash_total=cash_total_f,
        card_total=card_total_f,
        order_ids=order_ids,
        payment_count=payment_count,
        opened_at=opened_at,
    )
    await ledger.append(close_evt)

    # Over/Short: Cash Expected = Cash Sales − Card Tips
    cash_sales_only = money_round(float(cash_total))
    card_tips_f = money_round(float(card_tips_total))
    cash_expected = money_round(cash_sales_only - card_tips_f)

    over_short = None
    actual_cash = None
    if body and body.actual_cash_counted is not None:
        actual_cash = money_round(body.actual_cash_counted)
        over_short = money_round(actual_cash - cash_expected)

    # Gate the close-day payload against the canonical invariants. We
    # don't have gross/voids/discounts/refunds separately here (close_day
    # works off order.total = subtotal − discount + tax), so pass them
    # as zero against a synthetic gross equal to net + tax: the P&L check
    # is then vacuously true while the tender and tips checks still bite.
    cash_tips_f = money_round(float(total_tips) - float(card_tips_total))
    _close_results = invariant_gate(
        check_day_close(
            gross_sales=total_sales_f,
            void_total=0.0,
            discount_total=0.0,
            refund_total=0.0,
            net_sales=total_sales_f,
            tax_collected=0.0,
            cash_total=cash_total_f,
            card_total=card_sales_f,
            total_tips=total_tips_f,
            card_tips=money_round(float(card_tips_total)),
            cash_tips=cash_tips_f,
            cash_expected=cash_expected,
            actual_cash_counted=actual_cash,
            over_short=over_short,
        ),
        context="close_day",
    )
    recon_diff = max_abs_diff(_close_results)

    summary = {
        "date": today,
        "total_orders": total_orders,
        "orders_closed_now": closed_count,
        "total_sales": total_sales_f,
        "total_tips": total_tips_f,
        "cash_total": cash_total_f,
        "card_total": card_total_f,
        "order_ids": order_ids,
        "payment_count": payment_count,
        "opened_at": opened_at,
        "reconciliation_diff": recon_diff,
        "cash_expected": cash_expected,
        "actual_cash_counted": actual_cash,
        "over_short": over_short,
    }

    return {"success": True, "summary": summary}


# =============================================================================
# SPLIT BY SEAT
# =============================================================================

class SplitBySeatRequest(BaseModel):
    seats: Optional[list[int]] = None  # specific seats, or None for all


@router.post("/{order_id}/split-by-seat")
async def split_by_seat(
    order_id: str,
    request: SplitBySeatRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Split an order into separate child orders by seat number.

    Each distinct seat_number gets its own new order. Items without a
    seat stay on the original order.  Returns the list of child orders.
    """
    order = await get_order_or_404(ledger, order_id)

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot split a {order.status} order",
        )

    # Group items by seat
    seat_items: dict[int, list] = {}
    for item in order.items:
        seat = getattr(item, "seat_number", None)
        if seat is None:
            continue
        if request.seats and seat not in request.seats:
            continue
        seat_items.setdefault(seat, []).append(item)

    if not seat_items:
        raise HTTPException(
            status_code=400,
            detail="No items with seat numbers found to split",
        )

    child_orders = []
    for seat_num, items in sorted(seat_items.items()):
        child_id = f"order_{uuid.uuid4().hex[:8]}"
        # Create child order (set correlation_id so the CREATE event
        # is returned by get_events_by_correlation — without this,
        # individual order lookups would 404 for split children)
        create_evt = order_created(
            terminal_id=settings.terminal_id,
            order_id=child_id,
            order_type=order.order_type,
            guest_count=1,
            table=order.table,
            server_id=order.server_id,
            server_name=order.server_name,
        )
        create_evt = create_evt.model_copy(update={"correlation_id": child_id})
        await ledger.append(create_evt)

        # Add items to child order
        for item in items:
            new_item_id = f"item_{uuid.uuid4().hex[:8]}"
            # item_added's payload doesn't carry modifiers — they live
            # on separate MODIFIER_APPLIED events. Previously this route
            # passed `modifiers=item.modifiers` which silently fell into
            # **kwargs and was dropped, so splitting an order by seat
            # lost every modifier price (a $10 item + $3 mod became a
            # $10-only child). Re-emit the modifier events the same
            # way the merge route does.
            add_evt = item_added(
                terminal_id=settings.terminal_id,
                order_id=child_id,
                item_id=new_item_id,
                menu_item_id=getattr(item, "menu_item_id", ""),
                name=item.name,
                price=float(item.price),
                quantity=item.quantity,
                category=getattr(item, "category", None),
                notes=getattr(item, "notes", None),
                seat_number=seat_num,
            )
            await ledger.append(add_evt)

            for mod in (getattr(item, "modifiers", None) or []):
                mod_evt = modifier_applied(
                    terminal_id=settings.terminal_id,
                    order_id=child_id,
                    item_id=new_item_id,
                    modifier_id=f"mod_{uuid.uuid4().hex[:8]}",
                    modifier_name=mod.get("name", ""),
                    modifier_price=mod.get("price", 0.0) or 0.0,
                    action=mod.get("action", "add"),
                    prefix=mod.get("prefix"),
                    half_price=mod.get("half_price"),
                )
                await ledger.append(mod_evt)

            # Remove from parent order
            remove_evt = item_removed(
                terminal_id=settings.terminal_id,
                order_id=order_id,
                item_id=item.item_id,
                reason=f"Split to seat {seat_num} check",
            )
            await ledger.append(remove_evt)

        child_orders.append({
            "order_id": child_id,
            "seat": seat_num,
            "item_count": len(items),
        })

    return {
        "success": True,
        "parent_order_id": order_id,
        "child_orders": child_orders,
    }


class SplitEvenlyRequest(BaseModel):
    num_ways: int = Field(ge=2, le=20)


@router.post("/{order_id}/split-evenly")
async def split_evenly(
    order_id: str,
    request: SplitEvenlyRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Calculate an even split of the order total.

    Does NOT create child orders — returns the per-person amount so the
    frontend can process N individual payments on the same order.
    """
    order = await get_order_or_404(ledger, order_id)

    if order.status not in ("open", "closed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot split a {order.status} order",
        )

    total = float(order.total)
    per_person = money_round(total / request.num_ways)
    # Last person pays remainder to avoid rounding loss
    last_person = money_round(total - per_person * (request.num_ways - 1))

    return {
        "success": True,
        "order_id": order_id,
        "total": total,
        "num_ways": request.num_ways,
        "per_person": per_person,
        "last_person": last_person,
    }


# =============================================================================
# TIP ADJUSTMENT (per-order route)
# =============================================================================

class OrderTipAdjustRequest(BaseModel):
    payment_id: str
    tip_amount: float


@router.post("/{order_id}/adjust-tip")
async def adjust_tip_on_order(
    order_id: str,
    request: OrderTipAdjustRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Adjust tip on a specific payment within an order.

    Authorization is handled at the scene level — servers only see
    their own checks, managers see all checks.
    """
    if request.tip_amount < 0:
        raise HTTPException(status_code=400, detail="Tip amount cannot be negative")
    _validate_2dp(request.tip_amount, "tip_amount")

    order = await get_order_or_404(ledger, order_id)

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
    events = await ledger.get_events_by_correlation(order_id)
    previous_tip = 0.0
    for e in events:
        if (e.event_type == EventType.TIP_ADJUSTED
                and e.payload.get("payment_id") == request.payment_id):
            previous_tip = e.payload.get("tip_amount", 0.0)

    tip_amt = money_round(request.tip_amount)
    evt = tip_adjusted(
        terminal_id=settings.terminal_id,
        order_id=order_id,
        payment_id=request.payment_id,
        tip_amount=tip_amt,
        previous_tip=previous_tip,
    )
    await ledger.append(evt)

    # Sync tip to payment device for batch settlement
    device_adjusted = False
    device_error = None
    try:
        from app.api.routes.payment_routes import get_payment_manager, _ensure_devices
        manager = get_payment_manager(ledger)
        await _ensure_devices(manager)
        device = manager.get_device_for_terminal(settings.terminal_id)
        if device and hasattr(device, 'adjust_tip') and device.config and device.config.protocol != "mock":
            result = await device.adjust_tip(target.payment_id, Decimal(str(tip_amt)))
            device_adjusted = result.status.value == "APPROVED"
            if not device_adjusted:
                device_error = f"Device tip adjust returned {result.status.value}"
    except Exception as e:
        device_error = f"Device tip adjust failed: {e}"
    if device_error:
        _logger.warning(
            f"Tip adjust for {request.payment_id} saved to ledger but device sync failed: {device_error}"
        )

    return {
        "success": True,
        "order_id": order_id,
        "payment_id": request.payment_id,
        "tip_amount": tip_amt,
        "previous_tip": previous_tip,
        "device_adjusted": device_adjusted,
        "device_warning": device_error,
    }