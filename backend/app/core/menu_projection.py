"""
Menu Projection

Projects the current menu state from the Event Ledger.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from .events import Event, EventType

class MenuItem(BaseModel):
    item_id: str
    name: str
    price: float
    category: str
    description: Optional[str] = None
    display_order: int = 999
    mods: Dict[str, Any] = {}

class MenuCategory(BaseModel):
    category_id: str
    name: str
    label: str
    color: str = "orange"
    display_order: int = 999
    subcats: Dict[str, Any] = {}

class MenuState(BaseModel):
    restaurant: Dict[str, Any] = {}
    categories: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    items_by_category: Dict[str, List[Dict[str, Any]]] = {}
    tax_rules: List[Dict[str, Any]] = []
    modifier_groups: List[Dict[str, Any]] = []

def project_menu(events: List[Event]) -> MenuState:
    """
    Build current menu state by replaying events.
    Supports both legacy batch events and new granular events.
    """
    state = MenuState()
    
    # We use dictionaries internally during projection for easy updates
    categories_map = {}
    items_map = {}
    modifier_groups_map = {}
    
    for event in events:
        payload = event.payload
        
        # Legacy batch events (from Terminal prototype)
        if event.event_type == "restaurant.configured":
            state.restaurant = {k: v for k, v in payload.items() if k != 'import_id'}
            
        elif event.event_type == "tax_rules.batch_created":
            state.tax_rules = payload.get('tax_rules', [])
            
        elif event.event_type == "categories.batch_created":
            cats = payload.get('categories', [])
            for cat in cats:
                categories_map[cat['category_id']] = cat
                
        elif event.event_type == "items.batch_created":
            items = payload.get('items', [])
            for item in items:
                items_map[item['item_id']] = item
                
        # Modern granular events (from core/backend)
        elif event.event_type == EventType.MENU_CATEGORY_CREATED:
            cat_id = payload.get('category_id')
            categories_map[cat_id] = payload
            
        elif event.event_type == EventType.MENU_CATEGORY_UPDATED:
            cat_id = payload.get('category_id')
            if cat_id in categories_map:
                categories_map[cat_id].update(payload)
                
        elif event.event_type == EventType.MENU_ITEM_CREATED:
            item_id = payload.get('item_id')
            items_map[item_id] = payload
            
        elif event.event_type == EventType.MENU_ITEM_UPDATED:
            item_id = payload.get('item_id')
            if item_id in items_map:
                items_map[item_id].update(payload)
                
        elif event.event_type == EventType.MENU_ITEM_DELETED:
            item_id = payload.get('item_id')
            if item_id in items_map:
                del items_map[item_id]
        
        elif event.event_type == EventType.MODIFIER_GROUP_CREATED:
            group_id = payload.get('group_id')
            modifier_groups_map[group_id] = payload
            
        elif event.event_type == EventType.MODIFIER_GROUP_UPDATED:
            group_id = payload.get('group_id')
            if group_id in modifier_groups_map:
                modifier_groups_map[group_id].update(payload)
                
        elif event.event_type == EventType.MODIFIER_GROUP_DELETED:
            group_id = payload.get('group_id')
            if group_id in modifier_groups_map:
                del modifier_groups_map[group_id]

    # Finalize state
    state.categories = sorted(categories_map.values(), key=lambda c: c.get('display_order', 999))
    state.items = list(items_map.values())
    state.modifier_groups = list(modifier_groups_map.values())
    
    # Build items_by_category
    for item in state.items:
        cat_name = item.get('category', 'Uncategorized')
        if cat_name not in state.items_by_category:
            state.items_by_category[cat_name] = []
        state.items_by_category[cat_name].append(item)
        
    return state
