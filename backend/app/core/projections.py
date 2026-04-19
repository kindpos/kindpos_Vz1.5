"""
KINDpos Projections

Projections rebuild current state from events.
The Event Ledger stores what happened; projections answer "what is the current state?"

This is the magic of event sourcing:
- Events are the source of truth
- State is always derived, never stored
- Any state can be rebuilt by replaying events
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from decimal import Decimal

from .events import Event, EventType
from .money import money_round


@dataclass
class OrderItem:
    """A single item on an order."""
    item_id: str
    menu_item_id: str
    name: str
    price: float
    quantity: int
    category: Optional[str] = None
    notes: Optional[str] = None
    seat_number: Optional[int] = None
    modifiers: list[dict] = field(default_factory=list)
    added_at: Optional[datetime] = None
    sent: bool = False
    sent_at: Optional[datetime] = None

    @property
    def subtotal(self) -> float:
        """Calculate item subtotal including modifiers.
        Uses Decimal to avoid float drift (e.g. 0.01 × 100)."""
        modifier_total = sum(Decimal(str(m.get("price", 0))) for m in self.modifiers)
        return float((Decimal(str(self.price)) + modifier_total) * self.quantity)


@dataclass
class Payment:
    """A payment attempt on an order."""
    payment_id: str
    amount: float
    method: str
    status: str = "pending"  # pending, confirmed, failed
    transaction_id: Optional[str] = None
    error: Optional[str] = None
    initiated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    tip_amount: float = 0.0
    tax_amount: float = 0.0  # Tax captured at payment time
    seat_numbers: list[int] = field(default_factory=list)  # Seats covered by this payment


@dataclass
class Order:
    """
    Current state of an order, projected from events.

    This is NOT stored - it's computed by replaying events.
    """
    order_id: str
    check_number: Optional[str] = None
    table: Optional[str] = None
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    customer_name: Optional[str] = None
    order_type: str = "dine_in"
    guest_count: int = 1
    status: str = "open"  # open, paid, closed, voided

    items: list[OrderItem] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    discounts: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)

    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    void_reason: Optional[str] = None

    # Printing history
    print_history: list[dict] = field(default_factory=list)

    # Tax rate — read from settings by default, overridable via project_order()
    _tax_rate: float = None

    @property
    def subtotal(self) -> float:
        """Sum of all items. Rounded to prevent float addition drift."""
        return money_round(sum(item.subtotal for item in self.items))

    @property
    def discount_total(self) -> float:
        """Sum of all discounts. Rounded to prevent float addition drift."""
        return money_round(sum(d.get("amount", 0) for d in self.discounts))

    @property
    def refund_total(self) -> float:
        """Sum of all refunds issued on this order."""
        return money_round(sum(r.get("amount", 0) for r in self.refunds))

    @property
    def tax_rate(self) -> float:
        if self._tax_rate is not None:
            return self._tax_rate
        from app.config import settings
        return settings.tax_rate

    @property
    def tax(self) -> float:
        """Tax collected — prefer event-sourced value from confirmed payments.
        Falls back to computed tax only when no payment has captured tax.
        Fallback is rounded to avoid float drift (e.g. 10.00*0.07)."""
        captured = sum(p.tax_amount for p in self.payments if p.status == "confirmed")
        if captured > 0:
            return captured
        taxable = max(0.0, self.subtotal - self.discount_total)
        return money_round(taxable * self.tax_rate)

    @property
    def total(self) -> float:
        """Final total (clamped to zero — discount cannot make total negative)."""
        raw = self.subtotal - self.discount_total + self.tax
        return money_round(max(0.0, raw))

    @property
    def amount_paid(self) -> float:
        """Sum of confirmed payments. Rounded to avoid float addition drift."""
        return money_round(sum(p.amount for p in self.payments if p.status == "confirmed"))

    @property
    def balance_due(self) -> float:
        """Remaining balance."""
        return money_round(self.total - self.amount_paid)

    @property
    def paid_seats(self) -> list[int]:
        """Seat numbers covered by confirmed payments."""
        seats = set()
        for p in self.payments:
            if p.status == "confirmed" and p.seat_numbers:
                seats.update(p.seat_numbers)
        return sorted(seats)

    @property
    def is_fully_paid(self) -> bool:
        """Check if order is fully paid."""
        return self.amount_paid >= self.total


def project_order(events: list[Event], tax_rate: float = None) -> Optional[Order]:
    """
    Rebuild an Order from a list of events.

    This is the core projection logic. Given all events for an order,
    replay them in sequence to compute current state.

    Args:
        tax_rate: Override the default tax rate (0.06) for this projection.
    """
    if not events:
        return None

    # Sort by sequence number to ensure correct order
    events = sorted(events, key=lambda e: e.sequence_number or 0)

    order: Optional[Order] = None

    for event in events:
        payload = event.payload

        # --- ORDER LIFECYCLE ---

        if event.event_type == EventType.ORDER_CREATED:
            order = Order(
                order_id=payload["order_id"],
                check_number=payload.get("check_number"),
                table=payload.get("table"),
                server_id=payload.get("server_id"),
                server_name=payload.get("server_name"),
                customer_name=payload.get("customer_name"),
                order_type=payload.get("order_type", "dine_in"),
                guest_count=payload.get("guest_count", 1),
                created_at=event.timestamp,
            )
            if tax_rate is not None:
                order._tax_rate = tax_rate

        elif event.event_type == EventType.ORDER_CLOSED:
            if order:
                order.status = "closed"
                order.closed_at = event.timestamp

        elif event.event_type == EventType.ORDER_REOPENED:
            if order:
                order.status = "open"
                order.closed_at = None

        elif event.event_type == EventType.ORDER_VOIDED:
            if order:
                order.status = "voided"
                order.voided_at = event.timestamp
                order.void_reason = payload.get("reason")

        elif event.event_type == EventType.ORDER_TRANSFERRED:
            if order:
                order.server_id = payload.get("server_id")
                order.server_name = payload.get("server_name")

        elif event.event_type == EventType.CHECK_NAMED:
            if order:
                order.customer_name = payload.get("customer_name")

        elif event.event_type == EventType.GUEST_COUNT_UPDATED:
            if order:
                order.guest_count = payload.get("guest_count", order.guest_count)

        # --- ITEMS ---

        elif event.event_type == EventType.ITEM_ADDED:
            if order:
                item = OrderItem(
                    item_id=payload["item_id"],
                    menu_item_id=payload["menu_item_id"],
                    name=payload["name"],
                    price=payload["price"],
                    quantity=payload.get("quantity", 1),
                    category=payload.get("category"),
                    notes=payload.get("notes"),
                    seat_number=payload.get("seat_number"),
                    added_at=event.timestamp,
                )
                order.items.append(item)

        elif event.event_type == EventType.ITEM_REMOVED:
            if order:
                item_id = payload["item_id"]
                order.items = [i for i in order.items if i.item_id != item_id]

        elif event.event_type == EventType.ITEM_MODIFIED:
            if order:
                item_id = payload["item_id"]
                for item in order.items:
                    if item.item_id == item_id:
                        if "quantity" in payload:
                            item.quantity = payload["quantity"]
                        if "price" in payload:
                            item.price = payload["price"]
                        if "notes" in payload:
                            item.notes = payload["notes"]
                        if "seat_number" in payload:
                            item.seat_number = payload["seat_number"]
                        break

        elif event.event_type == EventType.MODIFIER_APPLIED:
            if order:
                item_id = payload["item_id"]
                for item in order.items:
                    if item.item_id == item_id:
                        modifier = {
                            "modifier_id": payload["modifier_id"],
                            "name": payload["modifier_name"],
                            "price": payload.get("modifier_price", 0),
                            "action": payload.get("action", "add"),
                            "prefix": payload.get("prefix"),
                            "half_price": payload.get("half_price"),
                        }
                        if payload.get("action") == "remove":
                            item.modifiers = [
                                m for m in item.modifiers
                                if m["modifier_id"] != payload["modifier_id"]
                            ]
                        else:
                            if not any(m["modifier_id"] == modifier["modifier_id"] for m in item.modifiers):
                                item.modifiers.append(modifier)
                        break

        elif event.event_type == EventType.ITEM_SENT:
            if order:
                item_id = payload["item_id"]
                for item in order.items:
                    if item.item_id == item_id:
                        item.sent = True
                        item.sent_at = event.timestamp
                        break

        # --- DISCOUNTS ---

        elif event.event_type == EventType.DISCOUNT_APPROVED:
            if order:
                order.discounts.append({
                    "type": payload.get("discount_type"),
                    "amount": payload.get("amount", 0),
                    "reason": payload.get("reason"),
                    "approved_by": payload.get("approved_by"),
                    "approved_at": event.timestamp,
                })

        # --- PAYMENTS ---

        elif event.event_type == EventType.PAYMENT_INITIATED:
            if order:
                pid = payload.get("payment_id") or payload.get("transaction_id")
                amt = payload.get("amount", 0)
                if isinstance(amt, str):
                    amt = float(amt)
                payment = Payment(
                    payment_id=pid,
                    amount=amt,
                    method=payload.get("method", payload.get("payment_type", "card")),
                    status="pending",
                    initiated_at=event.timestamp,
                    seat_numbers=payload.get("seat_numbers", []),
                )
                order.payments.append(payment)

        elif event.event_type == EventType.PAYMENT_CONFIRMED:
            if order:
                pid = payload.get("payment_id") or payload.get("transaction_id")
                for payment in order.payments:
                    if payment.payment_id == pid:
                        payment.status = "confirmed"
                        payment.transaction_id = payload.get("transaction_id")
                        payment.confirmed_at = event.timestamp
                        payment.tax_amount = payload.get("tax", 0.0)
                        if payload.get("seat_numbers"):
                            payment.seat_numbers = payload["seat_numbers"]
                        break

                # Auto-update order status if fully paid
                if order.is_fully_paid and order.status == "open":
                    order.status = "paid"

        elif event.event_type in (
            EventType.PAYMENT_DECLINED,
            EventType.PAYMENT_CANCELLED,
            EventType.PAYMENT_TIMED_OUT,
            EventType.PAYMENT_ERROR,
        ):
            if order:
                pid = payload.get("payment_id") or payload.get("transaction_id")
                for payment in order.payments:
                    if payment.payment_id == pid:
                        payment.status = "failed"
                        payment.error = payload.get("error") or payload.get("processor_message")
                        break

                # Revert order to "open" if no longer fully paid
                if order.status == "paid" and not order.is_fully_paid:
                    order.status = "open"

        elif event.event_type == EventType.TIP_ADJUSTED:
            if order:
                for payment in order.payments:
                    if payment.payment_id == payload["payment_id"]:
                        payment.tip_amount = payload.get("tip_amount", 0.0)
                        break

        elif event.event_type == EventType.PAYMENT_REFUNDED:
            if order:
                order.refunds.append({
                    "payment_id": payload.get("payment_id"),
                    "amount": payload.get("amount", 0),
                    "reason": payload.get("reason"),
                    "refunded_at": event.timestamp,
                })

        # --- PRINTING ---

        elif event.event_type == EventType.TICKET_PRINTED:
            if order:
                order.print_history.append({
                    "printer_id": payload["printer_id"],
                    "printer_name": payload["printer_name"],
                    "ticket_type": payload.get("ticket_type", "kitchen"),
                    "printed_at": event.timestamp,
                })

    return order


def project_orders(events: list[Event]) -> dict[str, Order]:
    """
    Project multiple orders from a list of events.

    Groups events by order_id and projects each order.
    """
    # Group events by order_id
    events_by_order: dict[str, list[Event]] = {}

    for event in events:
        order_id = event.payload.get("order_id") or event.correlation_id
        if order_id:
            if order_id not in events_by_order:
                events_by_order[order_id] = []
            events_by_order[order_id].append(event)

    # Project each order
    orders = {}
    for order_id, order_events in events_by_order.items():
        order = project_order(order_events)
        if order:
            orders[order_id] = order

    return orders


def get_open_orders(orders: dict[str, Order]) -> list[Order]:
    """Filter to only open orders."""
    return [o for o in orders.values() if o.status == "open"]


def get_orders_by_table(orders: dict[str, Order], table: str) -> list[Order]:
    """Get orders for a specific table."""
    return [o for o in orders.values() if o.table == table and o.status in ("open", "paid")]


def get_orders_by_server(orders: dict[str, Order], server_id: str) -> list[Order]:
    """Get orders for a specific server."""
    return [o for o in orders.values() if o.server_id == server_id]
