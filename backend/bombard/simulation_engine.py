"""
KINDpos Bombard Simulation Engine

Generates ~350 checks across a simulated restaurant day,
writing directly to the EventLedger using real event factory functions.
"""

import asyncio
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    create_event,
    order_created,
    item_added,
    item_removed,
    item_sent,
    modifier_applied,
    payment_initiated,
    payment_confirmed,
    order_closed,
    order_voided,
    tip_adjusted,
    batch_submitted,
    day_closed,
)
from app.core.projections import project_order
from app.config import settings

from .mock_menu import (
    CATEGORIES,
    MENU_ITEMS,
    MODIFIER_GROUPS,
    TABLES,
    SERVERS,
    SERVER_NAMES,
    TABLE_SERVER_MAP,
    SERVER_TABLE_MAP,
    ITEM_TO_86_APPETIZER,
    ITEM_TO_86_ENTREE,
    TAX_RATE,
    get_available_items,
    pick_random_items,
    get_random_modifier,
)

TERMINAL_ID = "terminal_01"


# ─── Tracking Structures ───────────────────────────────────

@dataclass
class CheckRecord:
    """Tracks a single check through its lifecycle."""
    order_id: str
    table: str
    server_id: str
    guest_count: int
    item_ids: list = field(default_factory=list)
    payment_ids: list = field(default_factory=list)
    status: str = "open"
    subtotal: Decimal = Decimal("0.00")
    tip_amount: Decimal = Decimal("0.00")
    payment_method: str = ""
    is_split: bool = False
    is_voided: bool = False
    is_comped: bool = False
    had_item_void: bool = False
    had_second_round: bool = False
    had_modifier: bool = False
    had_86_rejection: bool = False
    phase: str = ""
    sim_time: datetime = None


@dataclass
class SimulationMetrics:
    """Collects timing and count metrics during simulation."""
    event_write_times: list = field(default_factory=list)
    order_lifecycle_times: list = field(default_factory=list)
    total_events: int = 0
    checks_created: int = 0
    checks_closed: int = 0
    checks_voided: int = 0
    items_added: int = 0
    payments_processed: int = 0
    tips_adjusted: int = 0
    modifiers_applied: int = 0
    item_voids: int = 0
    comps: int = 0
    split_tenders: int = 0
    second_rounds: int = 0
    eighty_six_rejections: int = 0
    full_check_voids: int = 0
    start_time: float = 0.0
    end_time: float = 0.0


class SimulationEngine:
    """
    Drives the bombard simulation against a live EventLedger.

    Does NOT use HTTP — calls event factories and ledger.append() directly,
    exactly as the API routes do internally.
    """

    def __init__(self, ledger: EventLedger):
        self.ledger = ledger
        self.metrics = SimulationMetrics()
        self.checks: dict[str, CheckRecord] = {}
        self.table_occupancy: dict[str, Optional[str]] = {t: None for t in TABLES}
        self.table_turn_count: dict[str, int] = {t: 0 for t in TABLES}
        self.eighty_sixed: set[str] = set()
        self.all_check_records: list[CheckRecord] = []

        # Financial accumulators (Decimal for precision)
        self.total_gross_sales = Decimal("0.00")
        self.total_discounts = Decimal("0.00")
        self.total_voids = Decimal("0.00")
        self.total_tips = Decimal("0.00")
        self.total_tax = Decimal("0.00")
        self.total_card_payments = Decimal("0.00")
        self.total_cash_payments = Decimal("0.00")

        # Server tracking
        self.server_checks: dict[str, list[str]] = {s: [] for s in SERVERS}
        self.server_tips: dict[str, Decimal] = {s: Decimal("0.00") for s in SERVERS}

    # ─── Helpers ────────────────────────────────────────────

    async def _append(self, event) -> None:
        """Append event to ledger with timing."""
        t0 = time.perf_counter()
        await self.ledger.append(event)
        elapsed = time.perf_counter() - t0
        self.metrics.event_write_times.append(elapsed)
        self.metrics.total_events += 1

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _pick_table(self) -> Optional[str]:
        """Pick a free table, or None if all occupied."""
        free = [t for t, occ in self.table_occupancy.items() if occ is None]
        return random.choice(free) if free else None

    def _free_table(self, table: str):
        self.table_occupancy[table] = None

    def _d(self, val) -> Decimal:
        """Convert to 2dp Decimal."""
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ─── Menu Setup ─────────────────────────────────────────

    async def setup_menu(self):
        """Load the mock menu into the ledger via batch events."""
        # Restaurant config
        evt = create_event(
            event_type=EventType.RESTAURANT_CONFIGURED,
            terminal_id=TERMINAL_ID,
            payload={
                "restaurant_name": "KINDpos Test Kitchen",
                "address": "123 Bombard Lane, Tampa FL 33602",
                "phone": "813-555-0100",
            },
        )
        await self._append(evt)

        # Tax rules
        evt = create_event(
            event_type=EventType.TAX_RULES_BATCH_CREATED,
            terminal_id=TERMINAL_ID,
            payload={
                "tax_rules": [
                    {"tax_rule_id": "tax_default", "name": "FL Sales Tax",
                     "rate_percent": 7.0, "applies_to": "all"},
                ],
            },
        )
        await self._append(evt)

        # Categories
        evt = create_event(
            event_type=EventType.CATEGORIES_BATCH_CREATED,
            terminal_id=TERMINAL_ID,
            payload={"categories": CATEGORIES},
        )
        await self._append(evt)

        # Items
        items_payload = []
        for item in MENU_ITEMS:
            items_payload.append({
                "item_id": item["item_id"],
                "name": item["name"],
                "price": float(Decimal(item["price"])),
                "category": item["category"],
                "category_id": item["category_id"],
            })
        evt = create_event(
            event_type=EventType.ITEMS_BATCH_CREATED,
            terminal_id=TERMINAL_ID,
            payload={"items": items_payload},
        )
        await self._append(evt)

        # Modifier groups
        for group in MODIFIER_GROUPS:
            evt = create_event(
                event_type=EventType.MODIFIER_GROUP_CREATED,
                terminal_id=TERMINAL_ID,
                payload={
                    "group_id": group["group_id"],
                    "name": group["name"],
                    "modifiers": group["modifiers"],
                    "applies_to": group["applies_to"],
                },
            )
            await self._append(evt)

    async def eighty_six_item(self, item_id: str):
        """86 an item (mark unavailable)."""
        self.eighty_sixed.add(item_id)
        evt = create_event(
            event_type=EventType.MENU_ITEM_86D,
            terminal_id=TERMINAL_ID,
            payload={"item_id": item_id, "reason": "Out of stock"},
        )
        await self._append(evt)

    async def un_eighty_six_item(self, item_id: str):
        """Restore an 86'd item."""
        self.eighty_sixed.discard(item_id)
        evt = create_event(
            event_type=EventType.MENU_ITEM_RESTORED,
            terminal_id=TERMINAL_ID,
            payload={"item_id": item_id},
        )
        await self._append(evt)

    # ─── Check Lifecycle ────────────────────────────────────

    async def create_check(self, phase: str, sim_time: datetime) -> Optional[CheckRecord]:
        """Create a new check on a free table."""
        table = self._pick_table()
        if table is None:
            return None  # All tables occupied

        order_id = self._new_id("order")
        server_id = TABLE_SERVER_MAP[table]
        guest_count = random.randint(1, 6)

        evt = order_created(
            terminal_id=TERMINAL_ID,
            order_id=order_id,
            table=table,
            server_id=server_id,
            server_name=SERVER_NAMES.get(server_id, server_id),
            order_type="dine_in",
            guest_count=guest_count,
        )
        evt = evt.model_copy(update={"correlation_id": order_id})
        await self._append(evt)

        self.table_occupancy[table] = order_id
        self.table_turn_count[table] += 1
        self.metrics.checks_created += 1
        self.server_checks[server_id].append(order_id)

        check = CheckRecord(
            order_id=order_id,
            table=table,
            server_id=server_id,
            guest_count=guest_count,
            phase=phase,
            sim_time=sim_time,
        )
        self.checks[order_id] = check
        self.all_check_records.append(check)
        return check

    async def add_items_to_check(self, check: CheckRecord, count: int,
                                  attempt_86: bool = False):
        """Add items to a check. If attempt_86, try to include an 86'd item."""
        available = get_available_items(self.eighty_sixed)
        if not available:
            return

        # Possibly attempt an 86'd item
        if attempt_86 and self.eighty_sixed:
            eighty_sixed_id = random.choice(list(self.eighty_sixed))
            eighty_sixed_item = next(
                (i for i in MENU_ITEMS if i["item_id"] == eighty_sixed_id), None
            )
            if eighty_sixed_item:
                # Record that we tried — the system should block this
                check.had_86_rejection = True
                self.metrics.eighty_six_rejections += 1
                # We note it but don't add the event (simulating rejection at the POS)

        items = pick_random_items(available, count)
        for menu_item in items:
            item_id = self._new_id("item")
            price = self._d(menu_item["price"])
            seat = random.randint(1, check.guest_count)

            evt = item_added(
                terminal_id=TERMINAL_ID,
                order_id=check.order_id,
                item_id=item_id,
                menu_item_id=menu_item["item_id"],
                name=menu_item["name"],
                price=float(price),
                quantity=1,
                category=menu_item["category"],
                seat_number=seat,
            )
            await self._append(evt)
            check.item_ids.append(item_id)
            check.subtotal += price
            self.metrics.items_added += 1

            # ~30% chance of modifier
            if random.random() < 0.30:
                mod = get_random_modifier(menu_item["item_id"])
                if mod:
                    evt = modifier_applied(
                        terminal_id=TERMINAL_ID,
                        order_id=check.order_id,
                        item_id=item_id,
                        modifier_id=mod["modifier_id"],
                        modifier_name=mod["modifier_name"],
                        modifier_price=mod["modifier_price"],
                    )
                    await self._append(evt)
                    check.subtotal += self._d(mod["modifier_price"])
                    check.had_modifier = True
                    self.metrics.modifiers_applied += 1

        # Send items to kitchen
        for item_id_sent in check.item_ids[-count:]:
            evt = item_sent(
                terminal_id=TERMINAL_ID,
                order_id=check.order_id,
                item_id=item_id_sent,
                name="",  # Name not required for sent event tracking
            )
            await self._append(evt)

    async def void_item(self, check: CheckRecord):
        """Void a single item from a check (mid-check void)."""
        if len(check.item_ids) < 2:
            return  # Keep at least 1 item
        item_to_void = random.choice(check.item_ids)
        evt = item_removed(
            terminal_id=TERMINAL_ID,
            order_id=check.order_id,
            item_id=item_to_void,
            reason="Customer changed mind",
        )
        await self._append(evt)
        check.item_ids.remove(item_to_void)
        check.had_item_void = True
        self.metrics.item_voids += 1

    async def comp_item(self, check: CheckRecord):
        """Comp an item (zero-dollar via discount event)."""
        if not check.item_ids:
            return
        # Use DISCOUNT_APPROVED to record a comp
        # Pick a random item's price as the comp amount
        events = await self.ledger.get_events_by_correlation(check.order_id)
        order = project_order(events)
        if not order or not order.items:
            return
        comped_item = random.choice(order.items)
        comp_amount = self._d(comped_item.subtotal)

        evt = create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL_ID,
            payload={
                "order_id": check.order_id,
                "discount_type": "comp",
                "amount": float(comp_amount),
                "reason": "Manager comp",
                "approved_by": "manager_01",
                "item_id": comped_item.item_id,
            },
            correlation_id=check.order_id,
        )
        await self._append(evt)
        check.is_comped = True
        self.total_discounts += comp_amount
        self.metrics.comps += 1

    async def void_check(self, check: CheckRecord):
        """Full check void before payment."""
        evt = order_voided(
            terminal_id=TERMINAL_ID,
            order_id=check.order_id,
            reason="Customer walked out",
            approved_by="manager_01",
        )
        await self._append(evt)
        check.status = "voided"
        check.is_voided = True
        self._free_table(check.table)
        self.metrics.checks_voided += 1
        self.metrics.full_check_voids += 1

        # Track void amount
        events = await self.ledger.get_events_by_correlation(check.order_id)
        order = project_order(events)
        if order:
            self.total_voids += self._d(order.total)

    async def pay_and_close(self, check: CheckRecord, method_override: str = None):
        """Pay and close a check. Handles card, cash, and split tender."""
        events = await self.ledger.get_events_by_correlation(check.order_id)
        order = project_order(events)
        if not order or order.status == "voided":
            return

        total = self._d(order.total)
        if total <= 0:
            # Zero-dollar check after comp — just close it
            evt = order_closed(
                terminal_id=TERMINAL_ID,
                order_id=check.order_id,
                total=0.0,
            )
            await self._append(evt)
            check.status = "closed"
            self._free_table(check.table)
            self.metrics.checks_closed += 1
            return

        # Determine payment method
        roll = random.random() if method_override is None else -1
        if method_override:
            method = method_override
        elif roll < 0.60:
            method = "card"
        elif roll < 0.85:
            method = "cash"
        else:
            method = "split"

        check.payment_method = method

        if method == "split":
            # Split tender: card + cash
            card_portion = self._d(total * Decimal("0.6"))
            cash_portion = total - card_portion
            await self._process_payment(check, card_portion, "card")
            await self._process_payment(check, cash_portion, "cash")
            check.is_split = True
            self.metrics.split_tenders += 1
        elif method == "card":
            await self._process_payment(check, total, "card")
        else:
            await self._process_payment(check, total, "cash")

        # Tip on card payments
        if method in ("card", "split"):
            # Tip 15-25% of pre-tax subtotal
            pretax = self._d(order.subtotal - order.discount_total)
            tip_pct = Decimal(str(random.randint(15, 25))) / Decimal("100")
            tip = (pretax * tip_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Find a card payment to attach tip to
            card_pay_id = None
            for pid in check.payment_ids:
                # We stored method info — find card payment
                card_pay_id = pid  # Use the last one
                break

            if card_pay_id and tip > 0:
                evt = tip_adjusted(
                    terminal_id=TERMINAL_ID,
                    order_id=check.order_id,
                    payment_id=card_pay_id,
                    tip_amount=float(tip),
                )
                await self._append(evt)
                check.tip_amount = tip
                self.total_tips += tip
                self.server_tips[check.server_id] += tip
                self.metrics.tips_adjusted += 1

        # Close the order
        # Re-project to get final total
        events = await self.ledger.get_events_by_correlation(check.order_id)
        order = project_order(events)
        if order:
            evt = order_closed(
                terminal_id=TERMINAL_ID,
                order_id=check.order_id,
                total=order.total,
            )
            await self._append(evt)
            self.total_gross_sales += self._d(order.subtotal)
            self.total_tax += self._d(order.tax)

        check.status = "closed"
        self._free_table(check.table)
        self.metrics.checks_closed += 1

    async def _process_payment(self, check: CheckRecord, amount: Decimal, method: str):
        """Process a single payment (card or cash) on a check."""
        payment_id = self._new_id("pay")
        check.payment_ids.append(payment_id)

        evt = payment_initiated(
            terminal_id=TERMINAL_ID,
            order_id=check.order_id,
            payment_id=payment_id,
            amount=float(amount),
            method=method,
        )
        await self._append(evt)

        txn_id = f"{method}_{uuid.uuid4().hex[:8]}"
        evt = payment_confirmed(
            terminal_id=TERMINAL_ID,
            order_id=check.order_id,
            payment_id=payment_id,
            transaction_id=txn_id,
            amount=float(amount),
        )
        await self._append(evt)

        if method == "card":
            self.total_card_payments += amount
        else:
            self.total_cash_payments += amount
        self.metrics.payments_processed += 1

    # ─── Phase Runners ──────────────────────────────────────

    async def run_phase1_pre_service(self):
        """Phase 1: Pre-Service (10:30-11:00). Setup, 86 items."""
        print("  Phase 1: Pre-Service (10:30-11:00)")
        await self.setup_menu()
        await self.eighty_six_item(ITEM_TO_86_APPETIZER)
        await self.eighty_six_item(ITEM_TO_86_ENTREE)
        print(f"    Menu loaded: {len(MENU_ITEMS)} items, {len(CATEGORIES)} categories")
        print(f"    86'd: {ITEM_TO_86_APPETIZER}, {ITEM_TO_86_ENTREE}")

    async def run_phase2_lunch(self):
        """Phase 2: Lunch Rush (11:00-14:00). Target ~120 checks."""
        print("  Phase 2: Lunch Rush (11:00-14:00)")
        target = 120
        created = 0
        sim_time = datetime(2026, 3, 29, 11, 0, tzinfo=timezone.utc)

        while created < target:
            # Ramp rate: peak at 12:15-13:00
            hour = sim_time.hour + sim_time.minute / 60
            if 12.25 <= hour <= 13.0:
                orders_this_batch = random.randint(6, 8)
            elif 11.0 <= hour < 12.25:
                orders_this_batch = random.randint(2, 5)
            else:
                orders_this_batch = random.randint(1, 3)

            orders_this_batch = min(orders_this_batch, target - created)

            for _ in range(orders_this_batch):
                check = await self.create_check("lunch", sim_time)
                if check is None:
                    # All tables full — close some
                    await self._close_random_open_checks(5)
                    check = await self.create_check("lunch", sim_time)
                    if check is None:
                        continue

                # 2-6 items
                item_count = random.randint(2, 6)
                attempt_86 = random.random() < 0.03  # 3% try 86'd item
                await self.add_items_to_check(check, item_count, attempt_86=attempt_86)

                # 10% second round
                if random.random() < 0.10:
                    await self.add_items_to_check(check, random.randint(1, 2))
                    check.had_second_round = True
                    self.metrics.second_rounds += 1

                # 5% mid-check item void
                if random.random() < 0.05:
                    await self.void_item(check)

                # 5% comp
                if random.random() < 0.05:
                    await self.comp_item(check)

                # 2% full void (before payment)
                if random.random() < 0.02:
                    await self.void_check(check)
                else:
                    await self.pay_and_close(check)

                created += 1

            sim_time += timedelta(minutes=random.randint(1, 3))

        print(f"    Created {created} checks")

    async def run_phase3_afternoon(self):
        """Phase 3: Slow Afternoon (14:00-17:00). Target ~30 checks."""
        print("  Phase 3: Slow Afternoon (14:00-17:00)")
        target = 30
        created = 0
        sim_time = datetime(2026, 3, 29, 14, 0, tzinfo=timezone.utc)

        while created < target:
            check = await self.create_check("afternoon", sim_time)
            if check is None:
                await self._close_random_open_checks(3)
                check = await self.create_check("afternoon", sim_time)
                if check is None:
                    continue

            item_count = random.randint(2, 4)
            attempt_86 = random.random() < 0.03
            await self.add_items_to_check(check, item_count, attempt_86=attempt_86)

            # 10% second round
            if random.random() < 0.10:
                await self.add_items_to_check(check, 1)
                check.had_second_round = True
                self.metrics.second_rounds += 1

            # Un-86 duck at ~15:30
            if sim_time.hour == 15 and sim_time.minute >= 25 and ITEM_TO_86_ENTREE in self.eighty_sixed:
                await self.un_eighty_six_item(ITEM_TO_86_ENTREE)
                print(f"    Un-86'd {ITEM_TO_86_ENTREE} at 15:30")

            await self.pay_and_close(check)
            created += 1
            sim_time += timedelta(minutes=random.randint(3, 5))

        print(f"    Created {created} checks")

    async def run_phase4_dinner(self):
        """Phase 4: Dinner Rush (17:00-22:00). Target ~200 checks."""
        print("  Phase 4: Dinner Rush (17:00-22:00)")
        target = 200
        created = 0
        sim_time = datetime(2026, 3, 29, 17, 0, tzinfo=timezone.utc)

        while created < target:
            hour = sim_time.hour + sim_time.minute / 60
            if 19.0 <= hour <= 20.5:
                orders_this_batch = random.randint(8, 10)
            elif 17.0 <= hour < 19.0:
                orders_this_batch = random.randint(3, 7)
            else:
                orders_this_batch = random.randint(1, 4)

            orders_this_batch = min(orders_this_batch, target - created)

            for _ in range(orders_this_batch):
                check = await self.create_check("dinner", sim_time)
                if check is None:
                    await self._close_random_open_checks(5)
                    check = await self.create_check("dinner", sim_time)
                    if check is None:
                        continue

                item_count = random.randint(2, 6)
                attempt_86 = random.random() < 0.03
                await self.add_items_to_check(check, item_count, attempt_86=attempt_86)

                # 10% second round (dessert course)
                if random.random() < 0.10:
                    await self.add_items_to_check(check, random.randint(1, 3))
                    check.had_second_round = True
                    self.metrics.second_rounds += 1

                # 5% mid-check item void
                if random.random() < 0.05:
                    await self.void_item(check)

                # 5% comp
                if random.random() < 0.05:
                    await self.comp_item(check)

                # 2% full void
                if random.random() < 0.02:
                    await self.void_check(check)
                else:
                    await self.pay_and_close(check)

                created += 1

            sim_time += timedelta(minutes=random.randint(1, 3))

        print(f"    Created {created} checks")

    async def run_phase5_close_day(self):
        """Phase 5: Close Day (22:00-22:30). Close remaining, settle batch."""
        print("  Phase 5: Close Day (22:00-22:30)")

        # Close any remaining open checks
        open_checks = [c for c in self.checks.values() if c.status == "open"]
        print(f"    Closing {len(open_checks)} remaining open checks...")
        for check in open_checks:
            await self.pay_and_close(check)

        # Build day summary from all events
        all_events = await self.ledger.get_events_since(0, limit=100000)
        from app.core.projections import project_orders
        all_orders = project_orders(all_events)

        total_sales = 0.0
        total_tips_from_events = 0.0
        cash_total = 0.0
        card_total = 0.0
        order_ids = []
        payment_count = 0

        for order in all_orders.values():
            if order.status in ("closed", "paid"):
                total_sales += order.total
                order_ids.append(order.order_id)
                for p in order.payments:
                    if p.status == "confirmed":
                        payment_count += 1
                        if p.method == "cash":
                            cash_total += p.amount
                        else:
                            card_total += p.amount

        for e in all_events:
            if e.event_type == EventType.TIP_ADJUSTED:
                total_tips_from_events += e.payload.get("tip_amount", 0.0)

        # Emit BATCH_SUBMITTED
        evt = batch_submitted(
            terminal_id=TERMINAL_ID,
            order_count=len(order_ids),
            total_amount=total_sales,
            cash_total=cash_total,
            card_total=card_total,
            order_ids=order_ids,
        )
        await self._append(evt)

        # Emit DAY_CLOSED
        evt = day_closed(
            terminal_id=TERMINAL_ID,
            date="2026-03-29",
            total_orders=len(all_orders),
            total_sales=total_sales,
            total_tips=total_tips_from_events,
            cash_total=cash_total,
            card_total=card_total,
            order_ids=order_ids,
            payment_count=payment_count,
            opened_at=all_events[0].timestamp.isoformat() if all_events else None,
        )
        await self._append(evt)
        print(f"    DAY_CLOSED emitted. {len(order_ids)} orders settled.")

    async def _close_random_open_checks(self, count: int):
        """Close some random open checks to free tables."""
        open_checks = [c for c in self.checks.values() if c.status == "open"]
        to_close = random.sample(open_checks, min(count, len(open_checks)))
        for check in to_close:
            await self.pay_and_close(check)

    # ─── Main Runner ────────────────────────────────────────

    async def run(self) -> SimulationMetrics:
        """Run the full day simulation."""
        self.metrics.start_time = time.perf_counter()
        print("\n" + "=" * 70)
        print("KINDpos BUSY DAY BOMBARD SIMULATION")
        print("=" * 70)

        await self.run_phase1_pre_service()
        await self.run_phase2_lunch()
        await self.run_phase3_afternoon()
        await self.run_phase4_dinner()
        await self.run_phase5_close_day()

        self.metrics.end_time = time.perf_counter()

        total_time = self.metrics.end_time - self.metrics.start_time
        print(f"\n  Simulation complete in {total_time:.2f}s")
        print(f"  Total events: {self.metrics.total_events}")
        print(f"  Total checks: {self.metrics.checks_created}")
        return self.metrics
