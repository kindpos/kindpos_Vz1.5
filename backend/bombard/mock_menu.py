"""
Mock Menu Data for KINDpos Bombard Simulation

Premium sit-down dining menu: ~40 items across 6+ categories.
All prices use Decimal for 2dp precision safety.
"""

from decimal import Decimal
import random

# ─── Categories ─────────────────────────────────────────────
CATEGORIES = [
    {"category_id": "cat_appetizers", "name": "Appetizers", "display_order": 1, "color": "orange"},
    {"category_id": "cat_entrees", "name": "Entrees", "display_order": 2, "color": "red"},
    {"category_id": "cat_desserts", "name": "Desserts", "display_order": 3, "color": "pink"},
    {"category_id": "cat_beverages", "name": "Beverages", "display_order": 4, "color": "blue"},
    {"category_id": "cat_sides", "name": "Sides", "display_order": 5, "color": "green"},
    {"category_id": "cat_specials", "name": "Specials", "display_order": 6, "color": "gold"},
]

# ─── Menu Items ─────────────────────────────────────────────
# price stored as string to init Decimal cleanly
MENU_ITEMS = [
    # Appetizers ($8-16)
    {"item_id": "mi_bruschetta",   "name": "Bruschetta",              "price": "12.00", "category": "Appetizers", "category_id": "cat_appetizers"},
    {"item_id": "mi_calamari",     "name": "Fried Calamari",          "price": "14.00", "category": "Appetizers", "category_id": "cat_appetizers"},
    {"item_id": "mi_crab_cakes",   "name": "Crab Cakes",             "price": "16.00", "category": "Appetizers", "category_id": "cat_appetizers"},
    {"item_id": "mi_soup",         "name": "Soup of the Day",        "price": "9.00",  "category": "Appetizers", "category_id": "cat_appetizers"},
    {"item_id": "mi_shrimp_cock",  "name": "Shrimp Cocktail",        "price": "15.00", "category": "Appetizers", "category_id": "cat_appetizers"},
    {"item_id": "mi_caprese",      "name": "Caprese Salad",          "price": "11.00", "category": "Appetizers", "category_id": "cat_appetizers"},
    {"item_id": "mi_wings",        "name": "Buffalo Wings",          "price": "13.00", "category": "Appetizers", "category_id": "cat_appetizers"},

    # Entrees ($22-45)
    {"item_id": "mi_salmon",       "name": "Atlantic Salmon",        "price": "32.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_ribeye",       "name": "12oz Ribeye Steak",      "price": "45.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_chicken",      "name": "Grilled Chicken Breast", "price": "24.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_pasta",        "name": "Lobster Pasta",          "price": "38.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_duck",         "name": "Pan-Seared Duck",        "price": "36.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_lamb",         "name": "Rack of Lamb",           "price": "42.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_seabass",      "name": "Chilean Sea Bass",       "price": "40.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_burger",       "name": "Wagyu Burger",           "price": "22.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_risotto",      "name": "Mushroom Risotto",       "price": "26.00", "category": "Entrees", "category_id": "cat_entrees"},
    {"item_id": "mi_pork_chop",    "name": "Bone-In Pork Chop",     "price": "30.00", "category": "Entrees", "category_id": "cat_entrees"},

    # Desserts ($10-14)
    {"item_id": "mi_tiramisu",     "name": "Tiramisu",               "price": "12.00", "category": "Desserts", "category_id": "cat_desserts"},
    {"item_id": "mi_cheesecake",   "name": "NY Cheesecake",          "price": "11.00", "category": "Desserts", "category_id": "cat_desserts"},
    {"item_id": "mi_creme_brulee", "name": "Creme Brulee",           "price": "10.00", "category": "Desserts", "category_id": "cat_desserts"},
    {"item_id": "mi_lava_cake",    "name": "Chocolate Lava Cake",    "price": "14.00", "category": "Desserts", "category_id": "cat_desserts"},
    {"item_id": "mi_gelato",       "name": "Artisan Gelato",         "price": "10.00", "category": "Desserts", "category_id": "cat_desserts"},

    # Beverages ($4-12)
    {"item_id": "mi_soda",         "name": "Fountain Soda",          "price": "4.00",  "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_iced_tea",     "name": "Fresh Iced Tea",         "price": "4.00",  "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_lemonade",     "name": "Housemade Lemonade",     "price": "5.00",  "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_espresso",     "name": "Double Espresso",        "price": "6.00",  "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_wine_glass",   "name": "House Wine (Glass)",     "price": "12.00", "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_beer",         "name": "Craft Beer",             "price": "8.00",  "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_cocktail",     "name": "Signature Cocktail",     "price": "14.00", "category": "Beverages", "category_id": "cat_beverages"},
    {"item_id": "mi_water",        "name": "Sparkling Water",        "price": "4.00",  "category": "Beverages", "category_id": "cat_beverages"},

    # Sides ($6-10)
    {"item_id": "mi_fries",        "name": "Truffle Fries",          "price": "9.00",  "category": "Sides", "category_id": "cat_sides"},
    {"item_id": "mi_asparagus",    "name": "Grilled Asparagus",      "price": "8.00",  "category": "Sides", "category_id": "cat_sides"},
    {"item_id": "mi_mac_cheese",   "name": "Lobster Mac & Cheese",   "price": "10.00", "category": "Sides", "category_id": "cat_sides"},
    {"item_id": "mi_caesar",       "name": "Caesar Salad",           "price": "7.00",  "category": "Sides", "category_id": "cat_sides"},
    {"item_id": "mi_baked_potato", "name": "Loaded Baked Potato",    "price": "6.00",  "category": "Sides", "category_id": "cat_sides"},

    # Specials ($28-55)
    {"item_id": "mi_lobster_tail", "name": "Lobster Tail",           "price": "55.00", "category": "Specials", "category_id": "cat_specials"},
    {"item_id": "mi_surf_turf",    "name": "Surf & Turf",            "price": "52.00", "category": "Specials", "category_id": "cat_specials"},
    {"item_id": "mi_tasting",      "name": "Chef's Tasting Menu",    "price": "48.00", "category": "Specials", "category_id": "cat_specials"},
    {"item_id": "mi_wagyu",        "name": "A5 Wagyu Strip",         "price": "55.00", "category": "Specials", "category_id": "cat_specials"},
    {"item_id": "mi_oysters",      "name": "Oyster Platter (Dozen)", "price": "36.00", "category": "Specials", "category_id": "cat_specials"},
]

# ─── Modifier Groups ───────────────────────────────────────
MODIFIER_GROUPS = [
    {
        "group_id": "mg_steak_temp",
        "name": "Steak Temperature",
        "modifiers": [
            {"id": "mod_rare",        "name": "Rare",        "price": "0.00"},
            {"id": "mod_med_rare",    "name": "Medium Rare", "price": "0.00"},
            {"id": "mod_medium",      "name": "Medium",      "price": "0.00"},
            {"id": "mod_well_done",   "name": "Well Done",   "price": "0.00"},
        ],
        "applies_to": ["mi_ribeye", "mi_wagyu", "mi_pork_chop"],
    },
    {
        "group_id": "mg_additions",
        "name": "Add-Ons",
        "modifiers": [
            {"id": "mod_extra_cheese", "name": "Extra Cheese",   "price": "2.00"},
            {"id": "mod_bacon",        "name": "Add Bacon",      "price": "3.00"},
            {"id": "mod_avocado",      "name": "Add Avocado",    "price": "2.50"},
            {"id": "mod_truffle",      "name": "Truffle Drizzle","price": "5.00"},
        ],
        "applies_to": ["mi_burger", "mi_fries", "mi_caesar", "mi_mac_cheese", "mi_risotto"],
    },
    {
        "group_id": "mg_removal",
        "name": "Removals",
        "modifiers": [
            {"id": "mod_no_onion",  "name": "No Onion",  "price": "0.00"},
            {"id": "mod_no_garlic", "name": "No Garlic", "price": "0.00"},
            {"id": "mod_no_nuts",   "name": "No Nuts",   "price": "0.00"},
            {"id": "mod_no_gluten", "name": "Gluten Free","price": "1.50"},
        ],
        "applies_to": None,  # applies to any item
    },
]

# ─── Items to 86 ───────────────────────────────────────────
ITEM_TO_86_APPETIZER = "mi_crab_cakes"   # 86'd before service
ITEM_TO_86_ENTREE = "mi_duck"            # 86'd before service, un-86'd at 15:30

# ─── Restaurant Setup ──────────────────────────────────────
TABLES = [f"table_{i:02d}" for i in range(1, 26)]
SERVERS = [f"server_{i:02d}" for i in range(1, 7)]
SERVER_NAMES = {
    "server_01": "Alice", "server_02": "Bob", "server_03": "Carlos",
    "server_04": "Diana", "server_05": "Ethan", "server_06": "Fiona",
}

# Server table assignments (each server handles ~4 tables)
SERVER_TABLE_MAP = {
    "server_01": TABLES[0:4],    # tables 01-04
    "server_02": TABLES[4:8],    # tables 05-08
    "server_03": TABLES[8:12],   # tables 09-12
    "server_04": TABLES[12:16],  # tables 13-16
    "server_05": TABLES[16:20],  # tables 17-20
    "server_06": TABLES[20:25],  # tables 21-25
}

# Reverse map: table -> server
TABLE_SERVER_MAP = {}
for server_id, tables in SERVER_TABLE_MAP.items():
    for table in tables:
        TABLE_SERVER_MAP[table] = server_id

TAX_RATE = Decimal("0.07")  # 7% Florida


def get_available_items(eighty_sixed: set[str]) -> list[dict]:
    """Return menu items not currently 86'd."""
    return [item for item in MENU_ITEMS if item["item_id"] not in eighty_sixed]


def pick_random_items(available_items: list[dict], count: int) -> list[dict]:
    """Pick random items from available menu."""
    return random.choices(available_items, k=count)


def get_random_modifier(item_id: str) -> dict | None:
    """Get a random applicable modifier for an item. Returns None if none apply."""
    applicable_groups = []
    for group in MODIFIER_GROUPS:
        if group["applies_to"] is None or item_id in group["applies_to"]:
            applicable_groups.append(group)
    if not applicable_groups:
        return None
    group = random.choice(applicable_groups)
    mod = random.choice(group["modifiers"])
    return {
        "modifier_id": mod["id"],
        "modifier_name": mod["name"],
        "modifier_price": float(Decimal(mod["price"])),
    }
