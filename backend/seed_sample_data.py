"""
Generate 3 months of realistic sample data for a mom & pop pizza shop.

Creates a fresh event_ledger.db with:
  - Pizza shop menu (categories, items, modifiers)
  - Golden Girls employee roster
  - Store configuration
  - ~90 days of orders, payments, tips, and shift data
  - DAY_CLOSED events separating each business day
  - "Today" data (no DAY_CLOSED) so the dashboard shows live charts

Usage (from backend/ directory):
    python seed_sample_data.py
"""

import asyncio
import os
import sys
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from app.core.event_ledger import EventLedger
from app.core.events import create_event, EventType
from app.core.money import money_round

# ─── Configuration ────────────────────────────────────────────────────────────

DB_PATH = "data/event_ledger.db"
TERMINAL_ID = "terminal_01"
TAX_RATE = 0.07
CASH_DISCOUNT_RATE = 0.04  # 4% dual-pricing cash discount
DAYS_OF_HISTORY = 90
SEED = 42  # reproducible data

random.seed(SEED)

# ─── Menu Data ────────────────────────────────────────────────────────────────

# ─── Tax Rules ────────────────────────────────────────────────────────────────
# Florida-style: food is generally exempt from sales tax, but prepared food
# and beverages are taxable. We model this as category-specific rules.

TAX_RULES = [
    {"tax_rule_id": "food_tax",    "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "pizza"},
    {"tax_rule_id": "food_tax_2",  "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "apps"},
    {"tax_rule_id": "food_tax_3",  "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "subs"},
    {"tax_rule_id": "food_tax_4",  "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "sides"},
    {"tax_rule_id": "bev_tax",     "name": "Beverage Tax",   "rate_percent": 9.0,  "applies_to": "category", "category_id": "drinks"},
]

CATEGORIES = [
    {"category_id": "pizza",  "name": "Pizza",       "label": "PIZZA",  "color": "#c0392b", "display_order": 1, "tax_rule_id": "food_tax"},
    {"category_id": "apps",   "name": "Appetizers",  "label": "APPS",   "color": "#d4a017", "display_order": 2, "tax_rule_id": "food_tax_2"},
    {"category_id": "subs",   "name": "Subs",        "label": "SUBS",   "color": "#7ac943", "display_order": 3, "tax_rule_id": "food_tax_3"},
    {"category_id": "sides",  "name": "Sides",       "label": "SIDES",  "color": "#00bcd4", "display_order": 4, "tax_rule_id": "food_tax_4"},
    {"category_id": "drinks", "name": "Drinks",      "label": "DRINKS", "color": "#2196f3", "display_order": 5, "tax_rule_id": "bev_tax"},
]

MENU_ITEMS = [
    # Pizza
    {"item_id": "lg_cheese",    "name": "Large Cheese",     "price": 14.00, "category": "Pizza",       "display_order": 1, "revenue_category": "Food"},
    {"item_id": "lg_pepperoni", "name": "Large Pepperoni",  "price": 16.00, "category": "Pizza",       "display_order": 2, "revenue_category": "Food"},
    {"item_id": "lg_supreme",   "name": "Large Supreme",    "price": 18.00, "category": "Pizza",       "display_order": 3, "revenue_category": "Food"},
    {"item_id": "sl_cheese",    "name": "Slice Cheese",     "price":  3.50, "category": "Pizza",       "display_order": 4, "revenue_category": "Food"},
    {"item_id": "sl_pepperoni", "name": "Slice Pepperoni",  "price":  4.00, "category": "Pizza",       "display_order": 5, "revenue_category": "Food"},
    {"item_id": "calzone",      "name": "Calzone",          "price": 12.00, "category": "Pizza",       "display_order": 6, "revenue_category": "Food"},
    # Appetizers
    {"item_id": "garlic_knots", "name": "Garlic Knots",     "price":  6.00, "category": "Appetizers",  "display_order": 1, "revenue_category": "Food"},
    {"item_id": "mozz_sticks",  "name": "Mozz Sticks",      "price":  8.00, "category": "Appetizers",  "display_order": 2, "revenue_category": "Food"},
    {"item_id": "buffalo_wings","name": "Buffalo Wings",     "price": 10.00, "category": "Appetizers",  "display_order": 3, "revenue_category": "Food"},
    {"item_id": "garlic_bread", "name": "Garlic Bread",     "price":  5.00, "category": "Appetizers",  "display_order": 4, "revenue_category": "Food"},
    # Subs
    {"item_id": "italian_sub",  "name": "Italian Sub",      "price": 10.00, "category": "Subs",        "display_order": 1, "revenue_category": "Food"},
    {"item_id": "meatball_sub", "name": "Meatball Sub",     "price":  9.00, "category": "Subs",        "display_order": 2, "revenue_category": "Food"},
    {"item_id": "chx_parm_sub", "name": "Chicken Parm Sub", "price": 11.00, "category": "Subs",        "display_order": 3, "revenue_category": "Food"},
    # Sides
    {"item_id": "house_salad",  "name": "House Salad",      "price":  7.00, "category": "Sides",       "display_order": 1, "revenue_category": "Food"},
    {"item_id": "caesar_salad", "name": "Caesar Salad",     "price":  8.00, "category": "Sides",       "display_order": 2, "revenue_category": "Food"},
    {"item_id": "fries",        "name": "Fries",            "price":  4.00, "category": "Sides",       "display_order": 3, "revenue_category": "Food"},
    # Drinks
    {"item_id": "soda",         "name": "Soda",             "price":  2.50, "category": "Drinks",      "display_order": 1, "revenue_category": "Beverage"},
    {"item_id": "iced_tea",     "name": "Iced Tea",         "price":  2.50, "category": "Drinks",      "display_order": 2, "revenue_category": "Beverage"},
    {"item_id": "water",        "name": "Water",            "price":  1.50, "category": "Drinks",      "display_order": 3, "revenue_category": "Beverage"},
]

MODIFIER_GROUPS = [
    {
        "group_id": "toppings",
        "name": "Toppings",
        "modifiers": [
            {"modifier_id": "pepperoni",    "name": "Pepperoni",    "price": 1.50},
            {"modifier_id": "sausage",      "name": "Sausage",      "price": 1.50},
            {"modifier_id": "mushrooms",    "name": "Mushrooms",    "price": 1.00},
            {"modifier_id": "onions",       "name": "Onions",       "price": 1.00},
            {"modifier_id": "peppers",      "name": "Peppers",      "price": 1.00},
            {"modifier_id": "extra_cheese", "name": "Extra Cheese", "price": 2.00},
        ],
    },
    {
        "group_id": "dressing",
        "name": "Dressing",
        "modifiers": [
            {"modifier_id": "ranch",       "name": "Ranch",       "price": 0.00},
            {"modifier_id": "blue_cheese", "name": "Blue Cheese", "price": 0.00},
            {"modifier_id": "italian",     "name": "Italian",     "price": 0.00},
            {"modifier_id": "caesar",      "name": "Caesar",      "price": 0.00},
        ],
    },
]

# ─── Employee Data ────────────────────────────────────────────────────────────

STAFF = [
    {"employee_id": "rose",    "first_name": "Rose",    "last_name": "N.",  "display_name": "Rose N.",    "role_ids": ["manager", "server"],  "pin": "1234", "hourly_rate": 18.00},
    {"employee_id": "blanche", "first_name": "Blanche", "last_name": "D.",  "display_name": "Blanche D.", "role_ids": ["server", "host"],     "pin": "5678", "hourly_rate": 14.00},
    {"employee_id": "dorothy", "first_name": "Dorothy", "last_name": "Z.",  "display_name": "Dorothy Z.", "role_ids": ["server"],              "pin": "1111", "hourly_rate": 14.00},
    {"employee_id": "sophia",  "first_name": "Sophia",  "last_name": "P.",  "display_name": "Sophia P.",  "role_ids": ["cook", "server"],     "pin": "2222", "hourly_rate": 16.00},
    {"employee_id": "miles",   "first_name": "Miles",   "last_name": "W.",  "display_name": "Miles W.",   "role_ids": ["cook", "busser"],     "pin": "3456", "hourly_rate": 12.00},
]

# Servers (those who take orders and receive tips)
SERVERS = [s for s in STAFF if "server" in s["role_ids"]]
COOKS   = [s for s in STAFF if "cook" in s["role_ids"]]

# ─── Realistic item weights (popularity) ──────────────────────────────────────

# Items ordered most frequently get higher weights
ITEM_WEIGHTS = {
    "sl_cheese": 18, "sl_pepperoni": 15, "lg_cheese": 12, "lg_pepperoni": 14,
    "lg_supreme": 8, "calzone": 6,
    "garlic_knots": 10, "mozz_sticks": 7, "buffalo_wings": 9, "garlic_bread": 5,
    "italian_sub": 6, "meatball_sub": 5, "chx_parm_sub": 5,
    "house_salad": 4, "caesar_salad": 3, "fries": 8,
    "soda": 20, "iced_tea": 8, "water": 6,
}

ITEM_BY_ID = {item["item_id"]: item for item in MENU_ITEMS}
WEIGHTED_ITEMS = []
for item in MENU_ITEMS:
    w = ITEM_WEIGHTS.get(item["item_id"], 5)
    WEIGHTED_ITEMS.extend([item] * w)

TABLES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "B1", "B2", "B3", "B4"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ts(base_date, hour, minute=0, second=0):
    """Build a timezone-aware datetime from a date and time components."""
    return datetime(
        base_date.year, base_date.month, base_date.day,
        hour, minute, second, tzinfo=timezone.utc,
    )


def _make_event(event_type, payload, timestamp, user_id=None, correlation_id=None):
    """Create an event with a specific timestamp."""
    event = create_event(
        event_type=event_type,
        terminal_id=TERMINAL_ID,
        payload=payload,
        user_id=user_id,
        correlation_id=correlation_id,
    )
    # Override the auto-generated timestamp
    object.__setattr__(event, "timestamp", timestamp)
    return event


def _order_volume(day_date):
    """Return the target number of orders for a given date."""
    dow = day_date.weekday()  # 0=Mon, 6=Sun
    if dow == 4:       # Friday
        base = random.randint(45, 60)
    elif dow == 5:     # Saturday
        base = random.randint(50, 65)
    elif dow == 6:     # Sunday
        base = random.randint(30, 40)
    else:              # Mon-Thu
        base = random.randint(25, 40)
    # Add some noise
    return max(15, base + random.randint(-5, 5))


def _pick_order_hour():
    """Pick an order hour weighted toward lunch and dinner rushes."""
    # Lunch 11-14, Dinner 17-21, slow otherwise
    weights = {
        11: 12, 12: 15, 13: 13, 14: 8,        # lunch
        15: 4, 16: 5,                           # afternoon lull
        17: 10, 18: 14, 19: 15, 20: 12, 21: 6, # dinner
    }
    hours = list(weights.keys())
    w = list(weights.values())
    return random.choices(hours, weights=w, k=1)[0]


def _pick_items_for_order():
    """Pick 1-5 items for a realistic pizza shop order."""
    num_items = random.choices([1, 2, 3, 4, 5], weights=[8, 25, 35, 22, 10], k=1)[0]
    items = []
    for _ in range(num_items):
        item = random.choice(WEIGHTED_ITEMS)
        items.append(item)
    return items


def _generate_shift_events(day_date, servers_on_duty, cooks_on_duty):
    """Generate clock-in/out events for the day's staff."""
    events = []
    for emp in servers_on_duty + cooks_on_duty:
        # Morning shift starts 10:00-11:00
        clock_in_hour = random.choice([10, 10, 11])
        clock_in_min = random.randint(0, 30)
        clock_in_ts = _ts(day_date, clock_in_hour, clock_in_min)

        events.append(_make_event(
            EventType.USER_LOGGED_IN,
            {"employee_id": emp["employee_id"], "employee_name": emp["display_name"]},
            clock_in_ts,
            user_id=emp["employee_id"],
        ))

        # Shift ends after 6-9 hours
        shift_hours = random.randint(6, 9)
        clock_out_ts = clock_in_ts + timedelta(hours=shift_hours, minutes=random.randint(0, 30))

        events.append(_make_event(
            EventType.USER_LOGGED_OUT,
            {"employee_id": emp["employee_id"], "employee_name": emp["display_name"]},
            clock_out_ts,
            user_id=emp["employee_id"],
        ))

    return events


def _generate_order_events(day_date, order_num, servers_on_duty):
    """Generate the full event chain for a single order."""
    events = []
    order_id = f"ord-{day_date.strftime('%Y%m%d')}-{order_num:04d}"
    correlation_id = order_id

    # Pick time, server, order type
    hour = _pick_order_hour()
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    order_ts = _ts(day_date, hour, minute, second)

    server = random.choice(servers_on_duty)
    order_type = random.choices(
        ["dine_in", "to_go", "delivery"],
        weights=[60, 25, 15], k=1
    )[0]

    guest_count = random.choices([1, 2, 3, 4, 5, 6], weights=[15, 35, 25, 15, 7, 3], k=1)[0]
    table = random.choice(TABLES) if order_type == "dine_in" else None
    check_number = f"#{order_num}"

    # 1) ORDER_CREATED
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
        correlation_id=correlation_id,
    ))

    # 2) ITEM_ADDED for each item
    items = _pick_items_for_order()
    item_events = []
    subtotal = Decimal("0")
    for idx, menu_item in enumerate(items):
        item_id = f"{order_id}-i{idx+1}"
        item_ts = order_ts + timedelta(seconds=30 * (idx + 1))
        price = Decimal(str(menu_item["price"]))
        subtotal += price

        item_events.append(_make_event(
            EventType.ITEM_ADDED,
            {
                "order_id": order_id,
                "item_id": item_id,
                "menu_item_id": menu_item["item_id"],
                "name": menu_item["name"],
                "price": float(price),
                "quantity": 1,
                "category": menu_item["category"],
                "notes": None,
                "seat_number": random.randint(1, guest_count) if order_type == "dine_in" else None,
            },
            item_ts,
            user_id=server["employee_id"],
            correlation_id=correlation_id,
        ))

        # ITEM_SENT shortly after
        sent_ts = item_ts + timedelta(seconds=random.randint(5, 60))
        item_events.append(_make_event(
            EventType.ITEM_SENT,
            {
                "order_id": order_id,
                "item_id": item_id,
                "name": menu_item["name"],
                "seat_number": None,
                "category": menu_item["category"],
                "sent_at": sent_ts.isoformat(),
            },
            sent_ts,
            correlation_id=correlation_id,
        ))

    events.extend(item_events)

    # ~2% chance of void
    if random.random() < 0.02:
        void_ts = order_ts + timedelta(minutes=random.randint(5, 20))
        events.append(_make_event(
            EventType.ORDER_VOIDED,
            {"order_id": order_id, "void_reason": "Customer changed mind"},
            void_ts,
            user_id=server["employee_id"],
            correlation_id=correlation_id,
        ))
        return events  # No payment for voided orders

    # 3) PAYMENT — with dual-pricing cash discount
    subtotal_f = float(subtotal)
    tax = money_round(subtotal_f * TAX_RATE)
    card_total = money_round(subtotal_f + tax)
    payment_id = f"pay-{order_id}"
    payment_ts = order_ts + timedelta(minutes=random.randint(15, 45))
    method = random.choices(["card", "cash"], weights=[70, 30], k=1)[0]

    if method == "cash":
        # Apply dual-pricing cash discount: 4% off the card total
        cash_discount = money_round(card_total * CASH_DISCOUNT_RATE)
        sale_amount = money_round(card_total - cash_discount)

        # Emit DISCOUNT_APPROVED event (same as real payment flow)
        events.append(_make_event(
            EventType.DISCOUNT_APPROVED,
            {
                "order_id": order_id,
                "discount_type": "cash_dual_pricing",
                "amount": cash_discount,
                "reason": "Cash dual-pricing discount",
            },
            payment_ts,
            correlation_id=correlation_id,
        ))
    else:
        sale_amount = card_total

    events.append(_make_event(
        EventType.PAYMENT_INITIATED,
        {
            "order_id": order_id,
            "payment_id": payment_id,
            "amount": sale_amount,
            "method": method,
        },
        payment_ts,
        correlation_id=correlation_id,
    ))

    confirm_ts = payment_ts + timedelta(seconds=random.randint(3, 15))
    transaction_id = f"txn-{uuid.uuid4().hex[:12]}"

    events.append(_make_event(
        EventType.PAYMENT_CONFIRMED,
        {
            "order_id": order_id,
            "payment_id": payment_id,
            "transaction_id": transaction_id,
            "amount": sale_amount,
        },
        confirm_ts,
        correlation_id=correlation_id,
    ))

    # 4) TIP (card orders, ~90% of the time)
    if method == "card" and random.random() < 0.90:
        tip_pct = random.choices(
            [0.15, 0.18, 0.20, 0.22, 0.25],
            weights=[20, 30, 30, 15, 5], k=1
        )[0]
        tip_amount = money_round(card_total * tip_pct)
        tip_ts = confirm_ts + timedelta(seconds=random.randint(5, 60))

        events.append(_make_event(
            EventType.TIP_ADJUSTED,
            {
                "order_id": order_id,
                "payment_id": payment_id,
                "tip_amount": tip_amount,
                "previous_tip": 0.0,
            },
            tip_ts,
            correlation_id=correlation_id,
        ))

    # 5) ORDER_CLOSED
    close_ts = confirm_ts + timedelta(seconds=random.randint(10, 120))
    events.append(_make_event(
        EventType.ORDER_CLOSED,
        {"order_id": order_id, "total": sale_amount},
        close_ts,
        correlation_id=correlation_id,
    ))

    return events


def _generate_day(day_date, is_today=False):
    """Generate all events for a single business day."""
    all_events = []

    # Pick staff on duty (2-3 servers, 1-2 cooks)
    num_servers = random.choices([2, 3, 4], weights=[30, 50, 20], k=1)[0]
    num_cooks = random.choices([1, 2], weights=[40, 60], k=1)[0]
    servers_on_duty = random.sample(SERVERS, min(num_servers, len(SERVERS)))
    cooks_on_duty = random.sample(COOKS, min(num_cooks, len(COOKS)))

    # Shift events
    all_events.extend(_generate_shift_events(day_date, servers_on_duty, cooks_on_duty))

    # Orders
    num_orders = _order_volume(day_date)
    day_total_sales = 0.0
    day_total_tips = 0.0
    day_cash = 0.0
    day_card = 0.0
    order_ids = []
    payment_count = 0

    for i in range(1, num_orders + 1):
        order_events = _generate_order_events(day_date, i, servers_on_duty)
        all_events.extend(order_events)

        # Track day totals for DAY_CLOSED
        for e in order_events:
            if e.event_type == EventType.PAYMENT_CONFIRMED:
                amt = e.payload.get("amount", 0)
                day_total_sales += amt
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

    # Sort all events chronologically
    all_events.sort(key=lambda e: e.timestamp)

    # DAY_CLOSED (not for today — keep today's open for dashboard)
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


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    # Delete existing DB for a fresh start
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing {DB_PATH}")

    # Also remove WAL/SHM files
    for suffix in ["-wal", "-shm"]:
        path = DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)

    ledger = EventLedger(DB_PATH)
    await ledger.connect()

    total_events = 0

    # ── 1. Store config ───────────────────────────────────────────────────
    print("\n── Seeding store config ──")
    event = _make_event(
        EventType.STORE_INFO_UPDATED,
        {
            "name": "KIND Pizza",
            "legal_entity_name": "KIND Pizza LLC",
            "address_line_1": "6151 Richmond Hwy",
            "address_line_2": None,
            "city": "Miami",
            "state": "FL",
            "zip": "33101",
            "phone": "(305) 555-0187",
            "email": "hello@kindpizza.com",
            "website": None,
            "tax_rate": 0.07,
            "timezone": "America/New_York",
        },
        datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
    )
    await ledger.append(event)
    total_events += 1
    print("  KIND Pizza config seeded")

    # ── 1b. Tax rules ─────────────────────────────────────────────────────
    print("\n── Seeding tax rules ──")
    for rule in TAX_RULES:
        event = _make_event(
            EventType.STORE_TAX_RULE_CREATED,
            rule,
            datetime(2026, 1, 1, 8, 0, 30, tzinfo=timezone.utc),
        )
        await ledger.append(event)
        total_events += 1
        applies = f"category:{rule['category_id']}" if rule["applies_to"] == "category" else "all items"
        print(f"  {rule['name']:20s} {rule['rate_percent']}% → {applies}")

    # ── 2. Categories ─────────────────────────────────────────────────────
    print("\n── Seeding categories ──")
    for cat in CATEGORIES:
        event = _make_event(
            EventType.MENU_CATEGORY_CREATED,
            cat,
            datetime(2026, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
        )
        await ledger.append(event)
        total_events += 1
        print(f"  {cat['name']}")

    # ── 3. Menu items ─────────────────────────────────────────────────────
    print("\n── Seeding menu items ──")
    for item in MENU_ITEMS:
        event = _make_event(
            EventType.MENU_ITEM_CREATED,
            item,
            datetime(2026, 1, 1, 8, 2, 0, tzinfo=timezone.utc),
        )
        await ledger.append(event)
        total_events += 1
        print(f"  {item['name']:25s} ${item['price']:.2f}")

    # ── 4. Modifier groups ────────────────────────────────────────────────
    print("\n── Seeding modifier groups ──")
    for group in MODIFIER_GROUPS:
        event = _make_event(
            EventType.MODIFIER_GROUP_CREATED,
            group,
            datetime(2026, 1, 1, 8, 3, 0, tzinfo=timezone.utc),
        )
        await ledger.append(event)
        total_events += 1
        mods = ", ".join(m["name"] for m in group["modifiers"])
        print(f"  {group['name']}: [{mods}]")

    # ── 5. Employees ──────────────────────────────────────────────────────
    print("\n── Seeding employees ──")
    for emp in STAFF:
        event = _make_event(
            EventType.EMPLOYEE_CREATED,
            {**emp, "active": True},
            datetime(2026, 1, 1, 8, 4, 0, tzinfo=timezone.utc),
        )
        await ledger.append(event)
        total_events += 1
        print(f"  {emp['display_name']:15s} {emp['role_ids']}  PIN:{emp['pin']}")

    # ── 6. Generate daily data ────────────────────────────────────────────
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=DAYS_OF_HISTORY)

    print(f"\n── Generating {DAYS_OF_HISTORY} days of order data ──")
    print(f"   {start_date} → {today}")

    for day_offset in range(DAYS_OF_HISTORY + 1):
        day_date = start_date + timedelta(days=day_offset)
        is_today = (day_date == today)

        day_events = _generate_day(day_date, is_today=is_today)

        # Batch insert for performance
        if day_events:
            await ledger.append_batch(day_events)
            total_events += len(day_events)

        # Progress indicator
        order_count = sum(1 for e in day_events if e.event_type == EventType.ORDER_CREATED)
        marker = " ← TODAY (open)" if is_today else ""
        dow = day_date.strftime("%a")
        print(f"  {day_date}  {dow}  {order_count:3d} orders  {len(day_events):4d} events{marker}")

    await ledger.close()
    print(f"\n{'='*60}")
    print(f"Done! {total_events:,} total events seeded into {DB_PATH}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
