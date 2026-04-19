"""
Sample order seeder — generates 30 days of realistic pizza shop order history.

Called automatically on first boot (when no orders exist) so the dashboard
graphs are populated for demos.  Idempotent: skips if ORDER_CREATED events
already exist in the ledger.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.event_ledger import EventLedger
from app.core.events import create_event, EventType
from app.core.money import money_round

# ─── Configuration ───────────────────────────────────────────────────────────

TERMINAL_ID = "terminal_01"
TAX_RATE = 0.07
CASH_DISCOUNT_RATE = 0.04
DAYS_OF_HISTORY = 30
SEED = 42

TABLES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "B1", "B2", "B3", "B4"]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ts(base_date, hour, minute=0, second=0):
    return datetime(
        base_date.year, base_date.month, base_date.day,
        hour, minute, second, tzinfo=timezone.utc,
    )


def _make_event(event_type, payload, timestamp, user_id=None, correlation_id=None):
    event = create_event(
        event_type=event_type,
        terminal_id=TERMINAL_ID,
        payload=payload,
        user_id=user_id,
        correlation_id=correlation_id,
    )
    object.__setattr__(event, "timestamp", timestamp)
    return event


def _order_volume(day_date):
    dow = day_date.weekday()
    if dow == 4:       # Friday
        base = random.randint(45, 60)
    elif dow == 5:     # Saturday
        base = random.randint(50, 65)
    elif dow == 6:     # Sunday
        base = random.randint(30, 40)
    else:
        base = random.randint(25, 40)
    return max(15, base + random.randint(-5, 5))


def _pick_order_hour():
    weights = {
        11: 12, 12: 15, 13: 13, 14: 8,
        15: 4, 16: 5,
        17: 10, 18: 14, 19: 15, 20: 12, 21: 6,
    }
    hours = list(weights.keys())
    w = list(weights.values())
    return random.choices(hours, weights=w, k=1)[0]


def _build_weighted_items(menu_items):
    """Build weighted item list from menu items for realistic ordering."""
    # Default weights by category — pizza slices and drinks are most popular
    category_weights = {
        "Pizza": 12, "Appetizers": 7, "Apps": 7,
        "Subs": 5, "Sides": 5,
        "Drinks": 15,
    }
    # Cheaper items ordered more often
    weighted = []
    for item in menu_items:
        cat = item.get("category", "")
        base_w = category_weights.get(cat, 5)
        price = item.get("price", 10)
        if price <= 5:
            base_w = int(base_w * 1.5)
        elif price >= 15:
            base_w = max(3, base_w // 2)
        weighted.extend([item] * base_w)
    return weighted


def _pick_items(weighted_items):
    num = random.choices([1, 2, 3, 4, 5], weights=[8, 25, 35, 22, 10], k=1)[0]
    return [random.choice(weighted_items) for _ in range(num)]


def _generate_shift_events(day_date, staff):
    events = []
    for emp in staff:
        clock_in_hour = random.choice([10, 10, 11])
        clock_in_min = random.randint(0, 30)
        clock_in_ts = _ts(day_date, clock_in_hour, clock_in_min)

        events.append(_make_event(
            EventType.USER_LOGGED_IN,
            {"employee_id": emp["employee_id"], "employee_name": emp["display_name"]},
            clock_in_ts,
            user_id=emp["employee_id"],
        ))

        shift_hours = random.randint(6, 9)
        clock_out_ts = clock_in_ts + timedelta(hours=shift_hours, minutes=random.randint(0, 30))
        events.append(_make_event(
            EventType.USER_LOGGED_OUT,
            {"employee_id": emp["employee_id"], "employee_name": emp["display_name"]},
            clock_out_ts,
            user_id=emp["employee_id"],
        ))
    return events


def _generate_order_events(day_date, order_num, servers, weighted_items):
    events = []
    order_id = f"ord-{day_date.strftime('%Y%m%d')}-{order_num:04d}"

    hour = _pick_order_hour()
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    order_ts = _ts(day_date, hour, minute, second)

    server = random.choice(servers)
    order_type = random.choices(["dine_in", "to_go", "delivery"], weights=[60, 25, 15], k=1)[0]
    guest_count = random.choices([1, 2, 3, 4, 5, 6], weights=[15, 35, 25, 15, 7, 3], k=1)[0]
    table = random.choice(TABLES) if order_type == "dine_in" else None
    check_number = f"#{order_num}"

    # ORDER_CREATED
    events.append(_make_event(
        EventType.ORDER_CREATED,
        {
            "order_id": order_id,
            "check_number": check_number,
            "table": table,
            "server_id": server["employee_id"],
            "server_name": server["display_name"],
            "order_type": order_type,
            "guest_count": guest_count,
            "customer_name": None,
        },
        order_ts,
        user_id=server["employee_id"],
        correlation_id=order_id,
    ))

    # ITEM_ADDED + ITEM_SENT
    items = _pick_items(weighted_items)
    subtotal = 0.0
    for idx, menu_item in enumerate(items):
        item_id = f"{order_id}-i{idx+1}"
        item_ts = order_ts + timedelta(seconds=30 * (idx + 1))
        price = float(menu_item["price"])
        subtotal += price

        events.append(_make_event(
            EventType.ITEM_ADDED,
            {
                "order_id": order_id,
                "item_id": item_id,
                "menu_item_id": menu_item["item_id"],
                "name": menu_item["name"],
                "price": float(price),
                "quantity": 1,
                "category": menu_item.get("category"),
                "notes": None,
                "seat_number": random.randint(1, guest_count) if order_type == "dine_in" else None,
            },
            item_ts,
            user_id=server["employee_id"],
            correlation_id=order_id,
        ))

        sent_ts = item_ts + timedelta(seconds=random.randint(5, 60))
        events.append(_make_event(
            EventType.ITEM_SENT,
            {
                "order_id": order_id,
                "item_id": item_id,
                "name": menu_item["name"],
                "seat_number": None,
                "category": menu_item.get("category"),
                "sent_at": sent_ts.isoformat(),
            },
            sent_ts,
            correlation_id=order_id,
        ))

    # ~2% void rate
    if random.random() < 0.02:
        void_ts = order_ts + timedelta(minutes=random.randint(5, 20))
        events.append(_make_event(
            EventType.ORDER_VOIDED,
            {"order_id": order_id, "void_reason": "Customer changed mind"},
            void_ts,
            user_id=server["employee_id"],
            correlation_id=order_id,
        ))
        return events

    # PAYMENT
    tax = money_round(subtotal * TAX_RATE)
    card_total = money_round(subtotal + tax)
    payment_id = f"pay-{order_id}"
    payment_ts = order_ts + timedelta(minutes=random.randint(15, 45))
    method = random.choices(["card", "cash"], weights=[70, 30], k=1)[0]

    if method == "cash":
        cash_discount = money_round(card_total * CASH_DISCOUNT_RATE)
        sale_amount = money_round(card_total - cash_discount)
        events.append(_make_event(
            EventType.DISCOUNT_APPROVED,
            {
                "order_id": order_id,
                "discount_type": "cash_dual_pricing",
                "amount": cash_discount,
                "reason": "Cash dual-pricing discount",
            },
            payment_ts,
            correlation_id=order_id,
        ))
    else:
        sale_amount = card_total

    events.append(_make_event(
        EventType.PAYMENT_INITIATED,
        {"order_id": order_id, "payment_id": payment_id, "amount": sale_amount, "method": method},
        payment_ts,
        correlation_id=order_id,
    ))

    confirm_ts = payment_ts + timedelta(seconds=random.randint(3, 15))
    transaction_id = f"txn-{uuid.uuid4().hex[:12]}"
    events.append(_make_event(
        EventType.PAYMENT_CONFIRMED,
        {"order_id": order_id, "payment_id": payment_id, "transaction_id": transaction_id, "amount": sale_amount},
        confirm_ts,
        correlation_id=order_id,
    ))

    # TIP (card orders, ~90%)
    if method == "card" and random.random() < 0.90:
        tip_pct = random.choices([0.15, 0.18, 0.20, 0.22, 0.25], weights=[20, 30, 30, 15, 5], k=1)[0]
        tip_amount = money_round(card_total * tip_pct)
        tip_ts = confirm_ts + timedelta(seconds=random.randint(5, 60))
        events.append(_make_event(
            EventType.TIP_ADJUSTED,
            {"order_id": order_id, "payment_id": payment_id, "tip_amount": tip_amount, "previous_tip": 0.0},
            tip_ts,
            correlation_id=order_id,
        ))

    # ORDER_CLOSED
    close_ts = confirm_ts + timedelta(seconds=random.randint(10, 120))
    events.append(_make_event(
        EventType.ORDER_CLOSED,
        {"order_id": order_id, "total": sale_amount},
        close_ts,
        correlation_id=order_id,
    ))

    return events


def _generate_day(day_date, staff, weighted_items, is_today=False):
    all_events = []

    # Pick 2-4 servers and 1-2 cooks for the day
    servers = [s for s in staff if "server" in s.get("role_ids", [])]
    cooks = [s for s in staff if "cook" in s.get("role_ids", [])]
    num_servers = min(random.choices([2, 3, 4], weights=[30, 50, 20], k=1)[0], len(servers))
    num_cooks = min(random.choices([1, 2], weights=[40, 60], k=1)[0], len(cooks))
    servers_on = random.sample(servers, num_servers) if servers else staff[:2]
    cooks_on = random.sample(cooks, num_cooks) if cooks else []

    all_events.extend(_generate_shift_events(day_date, servers_on + cooks_on))

    num_orders = _order_volume(day_date)
    day_total_sales = 0.0
    day_total_tips = 0.0
    day_cash = 0.0
    day_card = 0.0
    order_ids = []
    payment_count = 0

    for i in range(1, num_orders + 1):
        order_events = _generate_order_events(day_date, i, servers_on, weighted_items)
        all_events.extend(order_events)

        for e in order_events:
            if e.event_type == EventType.PAYMENT_CONFIRMED:
                day_total_sales += e.payload.get("amount", 0)
                payment_count += 1
            if e.event_type == EventType.TIP_ADJUSTED:
                day_total_tips += e.payload.get("tip_amount", 0)
            if e.event_type == EventType.PAYMENT_INITIATED:
                if e.payload.get("method") == "cash":
                    day_cash += e.payload.get("amount", 0)
                else:
                    day_card += e.payload.get("amount", 0)
            if e.event_type == EventType.ORDER_CREATED:
                order_ids.append(e.payload["order_id"])

    all_events.sort(key=lambda e: e.timestamp)

    if not is_today:
        close_ts = _ts(day_date, 23, 59, 59)
        all_events.append(_make_event(
            EventType.DAY_CLOSED,
            {
                "date": day_date.strftime("%Y-%m-%d"),
                "total_orders": len(order_ids),
                "total_sales": money_round(day_total_sales),
                "total_tips": money_round(day_total_tips),
                "cash_total": money_round(day_cash),
                "card_total": money_round(day_card),
                "order_ids": order_ids,
                "payment_count": payment_count,
            },
            close_ts,
        ))

    return all_events


# ─── Public API ──────────────────────────────────────────────────────────────

async def seed_sample_orders_if_empty(ledger: EventLedger) -> None:
    """Generate 30 days of sample orders if none exist.

    Reads employees and menu items from the ledger so it works with
    whatever was seeded by demo_seeder (or seed_demo_data.py).
    """
    existing = await ledger.get_events_by_type(EventType.ORDER_CREATED, limit=1)
    if existing:
        return

    random.seed(SEED)

    # Read employees from ledger
    emp_events = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED, limit=100)
    if not emp_events:
        print("  No employees in ledger — skipping sample order seeding")
        return

    staff = []
    for e in emp_events:
        p = e.payload
        staff.append({
            "employee_id": p["employee_id"],
            "display_name": p.get("display_name", p.get("first_name", "Unknown")),
            "role_ids": p.get("role_ids", [p.get("role", "server")]),
        })

    # Ensure at least one server exists
    servers = [s for s in staff if "server" in s.get("role_ids", [])]
    if not servers:
        # Treat first employee as a server
        staff[0]["role_ids"] = staff[0].get("role_ids", []) + ["server"]

    # Read menu items from ledger
    item_events = await ledger.get_events_by_type(EventType.MENU_ITEM_CREATED, limit=200)
    if not item_events:
        print("  No menu items in ledger — skipping sample order seeding")
        return

    menu_items = []
    for e in item_events:
        p = e.payload
        menu_items.append({
            "item_id": p["item_id"],
            "name": p["name"],
            "price": p["price"],
            "category": p.get("category"),
        })

    weighted_items = _build_weighted_items(menu_items)

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=DAYS_OF_HISTORY)

    # Seed only previous days — today starts empty so real usage isn't mixed with demo data
    print(f"  Seeding {DAYS_OF_HISTORY} days of sample orders ({start_date} → {today - timedelta(days=1)})...")

    total_events = 0
    for day_offset in range(DAYS_OF_HISTORY):
        day_date = start_date + timedelta(days=day_offset)

        day_events = _generate_day(day_date, staff, weighted_items, is_today=False)
        if day_events:
            await ledger.append_batch(day_events)
            total_events += len(day_events)

    print(f"  Sample order seed complete — {total_events:,} events across {DAYS_OF_HISTORY + 1} days")
