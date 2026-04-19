"""
Seed script — appends menu categories, items, and modifier groups for the demo
pizza shop menu.

Usage (from backend/ directory):
    python seed_demo_data.py

Idempotent: checks for existing MENU_ITEM_CREATED events before seeding.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.event_ledger import EventLedger
from app.core.events import create_event, EventType

# ── Categories ────────────────────────────────────────────────────────────────

# ── Tax Rules ─────────────────────────────────────────────────────────────────

TAX_RULES = [
    {"tax_rule_id": "food_tax",    "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "pizza"},
    {"tax_rule_id": "food_tax_2",  "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "apps"},
    {"tax_rule_id": "food_tax_3",  "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "subs"},
    {"tax_rule_id": "food_tax_4",  "name": "Prepared Food",  "rate_percent": 7.0,  "applies_to": "category", "category_id": "sides"},
    {"tax_rule_id": "bev_tax",     "name": "Beverage Tax",   "rate_percent": 9.0,  "applies_to": "category", "category_id": "drinks"},
]

CATEGORIES = [
    {"category_id": "pizza",  "name": "Pizza",       "label": "PIZZA",  "color": "#c0392b", "display_order": 1, "tax_rule_id": "food_tax", "pizza_builder": True},
    {"category_id": "apps",   "name": "Appetizers",  "label": "APPS",   "color": "#d4a017", "display_order": 2, "tax_rule_id": "food_tax_2"},
    {"category_id": "subs",   "name": "Subs",        "label": "SUBS",   "color": "#7ac943", "display_order": 3, "tax_rule_id": "food_tax_3"},
    {"category_id": "sides",  "name": "Sides",       "label": "SIDES",  "color": "#00bcd4", "display_order": 4, "tax_rule_id": "food_tax_4"},
    {"category_id": "drinks", "name": "Drinks",      "label": "DRINKS", "color": "#2196f3", "display_order": 5, "tax_rule_id": "bev_tax"},
]

# ── Menu Items ────────────────────────────────────────────────────────────────

MENU_ITEMS = [
    # Pizza — single item, size/crust/toppings handled by modifier panel
    {"item_id": "pizza",         "name": "Pizza",           "price":  0,    "category": "Pizza",       "display_order": 1},
    # Appetizers
    {"item_id": "garlic_knots", "name": "Garlic Knots",    "price":  6.00, "category": "Appetizers",  "display_order": 1},
    {"item_id": "mozz_sticks",  "name": "Mozz Sticks",     "price":  8.00, "category": "Appetizers",  "display_order": 2},
    {"item_id": "buffalo_wings","name": "Buffalo Wings",    "price": 10.00, "category": "Appetizers",  "display_order": 3},
    {"item_id": "garlic_bread", "name": "Garlic Bread",    "price":  5.00, "category": "Appetizers",  "display_order": 4},
    # Subs
    {"item_id": "italian_sub",  "name": "Italian Sub",     "price": 10.00, "category": "Subs",        "display_order": 1},
    {"item_id": "meatball_sub", "name": "Meatball Sub",    "price":  9.00, "category": "Subs",        "display_order": 2},
    {"item_id": "chx_parm_sub", "name": "Chicken Parm Sub","price": 11.00, "category": "Subs",        "display_order": 3},
    # Sides
    {"item_id": "house_salad",  "name": "House Salad",     "price":  7.00, "category": "Sides",       "display_order": 1},
    {"item_id": "caesar_salad", "name": "Caesar Salad",    "price":  8.00, "category": "Sides",       "display_order": 2},
    {"item_id": "fries",        "name": "Fries",           "price":  4.00, "category": "Sides",       "display_order": 3},
    # Drinks
    {"item_id": "soda",         "name": "Soda",            "price":  2.50, "category": "Drinks",      "display_order": 1},
    {"item_id": "iced_tea",     "name": "Iced Tea",        "price":  2.50, "category": "Drinks",      "display_order": 2},
    {"item_id": "water",        "name": "Water",           "price":  1.50, "category": "Drinks",      "display_order": 3},
]

# ── Modifier Groups ──────────────────────────────────────────────────────────

MODIFIER_GROUPS = [
    # ── Pizza builder groups ─────────────────────────────────────────────
    {
        "group_id": "pizza-specials",
        "name": "Specials",
        "category_id": "pizza",
        "builder": True,
        "color": "#fcbe40",
        "text_color": "#1a1000",
        "display_order": 1,
        "modifiers": [
            {"modifier_id": "bianco",          "name": "Bianco",          "price": 0},
            {"modifier_id": "breakfast-bacon", "name": "Breakfast Bacon", "price": 0},
            {"modifier_id": "cheeseburger",    "name": "Cheeseburger",    "price": 0},
            {"modifier_id": "chicken-alfredo", "name": "Chicken Alfredo", "price": 0},
            {"modifier_id": "crew",            "name": "Crew",            "price": 0},
            {"modifier_id": "hawaiian",        "name": "Hawaiian",        "price": 0},
            {"modifier_id": "house",           "name": "House",           "price": 0},
            {"modifier_id": "kosher",          "name": "Kosher",          "price": 0},
            {"modifier_id": "mac-n-cheese",    "name": "Mac N Cheese",    "price": 0},
            {"modifier_id": "moccho",          "name": "Moccho",          "price": 0},
            {"modifier_id": "nick-special",    "name": "Nick Special",    "price": 0},
            {"modifier_id": "primo",           "name": "Primo",           "price": 0},
            {"modifier_id": "sammys-special",  "name": "Sammy's Special", "price": 0},
            {"modifier_id": "taco",            "name": "Taco",            "price": 0},
            {"modifier_id": "veggie",          "name": "Veggie",          "price": 0},
        ],
    },
    {
        "group_id": "pizza-prep",
        "name": "Prep",
        "category_id": "pizza",
        "builder": True,
        "color": "#b48efa",
        "text_color": "#1a0030",
        "display_order": 2,
        "modifiers": [],
        "subcats": [
            {"id": "prep-crust", "name": "Crust", "modifiers": [
                {"modifier_id": "gf-crust",      "name": "Sub GF Crust",  "price": 0},
                {"modifier_id": "thin-crust",    "name": "Thin Crust",    "price": 0},
                {"modifier_id": "thick-crust",   "name": "Thick Crust",   "price": 0},
                {"modifier_id": "stuffed-crust", "name": "Stuffed Crust", "price": 0},
            ]},
            {"id": "prep-temp", "name": "Temp", "modifiers": [
                {"modifier_id": "well-done",  "name": "Well Done",  "price": 0},
                {"modifier_id": "light-bake", "name": "Light Bake", "price": 0},
            ]},
            {"id": "prep-sauce", "name": "Sauce", "modifiers": [
                {"modifier_id": "light-sauce", "name": "Light Sauce", "price": 0},
                {"modifier_id": "extra-sauce", "name": "Extra Sauce", "price": 0},
                {"modifier_id": "no-sauce",    "name": "No Sauce",    "price": 0},
                {"modifier_id": "white-sauce", "name": "White Sauce", "price": 0},
                {"modifier_id": "bbq-sauce",   "name": "BBQ Sauce",   "price": 0},
            ]},
            {"id": "prep-cut", "name": "Cut", "modifiers": [
                {"modifier_id": "cut-square", "name": "Cut Square", "price": 0},
                {"modifier_id": "no-cut",     "name": "No Cut",     "price": 0},
            ]},
        ],
    },
    {
        "group_id": "pizza-toppings",
        "name": "Toppings",
        "category_id": "pizza",
        "builder": True,
        "color": "#ff4757",
        "text_color": "#1a0a0a",
        "display_order": 3,
        "modifiers": [
            {"modifier_id": "banana-peppers",  "name": "Banana Peppers",  "price": 1.00},
            {"modifier_id": "beef",            "name": "Beef",            "price": 1.50},
            {"modifier_id": "black-olives",    "name": "Black Olives",    "price": 1.00},
            {"modifier_id": "canadian-bacon",  "name": "Canadian Bacon",  "price": 1.50},
            {"modifier_id": "cheddar",         "name": "Cheddar",         "price": 1.50},
            {"modifier_id": "chicken",         "name": "Chicken",         "price": 2.00},
            {"modifier_id": "garlic",          "name": "Garlic",          "price": 0.50},
            {"modifier_id": "green-olives",    "name": "Green Olives",    "price": 1.00},
            {"modifier_id": "green-peppers",   "name": "Green Peppers",   "price": 1.00},
            {"modifier_id": "ground-beef",     "name": "Ground Beef",     "price": 1.50},
            {"modifier_id": "jalapenos",       "name": "Jalapenos",       "price": 1.00},
            {"modifier_id": "mozzarella",      "name": "Mozzarella",      "price": 1.50},
            {"modifier_id": "mushroom",        "name": "Mushroom",        "price": 1.00},
            {"modifier_id": "onion",           "name": "Onion",           "price": 1.00},
            {"modifier_id": "pepperoni",       "name": "Pepperoni",       "price": 1.50},
            {"modifier_id": "pineapple",       "name": "Pineapple",       "price": 1.00},
            {"modifier_id": "sausage",         "name": "Sausage",         "price": 1.50},
            {"modifier_id": "spinach",         "name": "Spinach",         "price": 1.00},
            {"modifier_id": "tomatoe",         "name": "Tomatoe",         "price": 1.00},
        ],
    },
    # ── Standard modifier groups ─────────────────────────────────────────
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


async def main():
    ledger = EventLedger("data/event_ledger.db")
    await ledger.connect()

    # ── Check existing data for idempotency ───────────────────────────────
    existing_items = await ledger.get_events_by_type(EventType.MENU_ITEM_CREATED, limit=1000)
    existing_item_ids = {e.payload.get("item_id") for e in existing_items}

    existing_cats = await ledger.get_events_by_type(EventType.MENU_CATEGORY_CREATED, limit=1000)
    existing_cat_ids = {e.payload.get("category_id") for e in existing_cats}

    existing_mods = await ledger.get_events_by_type(EventType.MODIFIER_GROUP_CREATED, limit=1000)
    existing_mod_ids = {e.payload.get("group_id") for e in existing_mods}

    existing_tax = await ledger.get_events_by_type(EventType.STORE_TAX_RULE_CREATED, limit=1000)
    existing_tax_ids = {e.payload.get("tax_rule_id") for e in existing_tax}

    seeded = 0

    # ── Seed tax rules ────────────────────────────────────────────────────
    for rule in TAX_RULES:
        if rule["tax_rule_id"] in existing_tax_ids:
            print(f"  skip  tax rule: {rule['name']} (already in ledger)")
            continue
        event = create_event(
            event_type=EventType.STORE_TAX_RULE_CREATED,
            terminal_id="SEED",
            payload=rule,
        )
        await ledger.append(event)
        print(f"  added tax rule: {rule['name']}  {rule['rate_percent']}% → {rule['applies_to']}")
        seeded += 1

    # ── Seed categories ───────────────────────────────────────────────────
    for cat in CATEGORIES:
        if cat["category_id"] in existing_cat_ids:
            print(f"  skip  category: {cat['name']} (already in ledger)")
            continue
        event = create_event(
            event_type=EventType.MENU_CATEGORY_CREATED,
            terminal_id="SEED",
            payload=cat,
        )
        await ledger.append(event)
        print(f"  added category: {cat['name']}")
        seeded += 1

    # ── Seed menu items ───────────────────────────────────────────────────
    for item in MENU_ITEMS:
        if item["item_id"] in existing_item_ids:
            print(f"  skip  item: {item['name']} (already in ledger)")
            continue
        event = create_event(
            event_type=EventType.MENU_ITEM_CREATED,
            terminal_id="SEED",
            payload=item,
        )
        await ledger.append(event)
        print(f"  added item: {item['name']}  ${item['price']:.2f}")
        seeded += 1

    # ── Seed modifier groups ──────────────────────────────────────────────
    for group in MODIFIER_GROUPS:
        if group["group_id"] in existing_mod_ids:
            print(f"  skip  modifier group: {group['name']} (already in ledger)")
            continue
        event = create_event(
            event_type=EventType.MODIFIER_GROUP_CREATED,
            terminal_id="SEED",
            payload=group,
        )
        await ledger.append(event)
        mods_str = ", ".join(m["name"] for m in group["modifiers"])
        print(f"  added modifier group: {group['name']}  [{mods_str}]")
        seeded += 1

    await ledger.close()
    print(f"\nDone — {seeded} event(s) seeded ({len(MENU_ITEMS)} items, {len(CATEGORIES)} categories, {len(MODIFIER_GROUPS)} modifier groups).")


if __name__ == "__main__":
    asyncio.run(main())
