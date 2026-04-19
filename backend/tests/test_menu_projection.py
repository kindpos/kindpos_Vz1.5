"""
Tests for menu projection — building MenuState from event streams.
"""

import pytest
from app.core.menu_projection import project_menu, MenuState
from app.core.events import create_event, EventType, Event


def _evt(event_type, payload, terminal_id="t1"):
    """Shortcut to create an Event for testing."""
    return create_event(
        event_type=event_type,
        terminal_id=terminal_id,
        payload=payload,
    )


class TestMenuProjection:

    def test_empty_events(self):
        state = project_menu([])
        assert isinstance(state, MenuState)
        assert state.categories == []
        assert state.items == []

    def test_batch_categories(self):
        event = _evt(EventType.CATEGORIES_BATCH_CREATED, {
            'categories': [
                {'category_id': 'cat-1', 'name': 'Appetizers', 'label': 'Apps', 'display_order': 1},
                {'category_id': 'cat-2', 'name': 'Entrees', 'label': 'Entrees', 'display_order': 2},
            ]
        })
        state = project_menu([event])
        assert len(state.categories) == 2
        assert state.categories[0]['name'] == 'Appetizers'

    def test_batch_items(self):
        event = _evt(EventType.ITEMS_BATCH_CREATED, {
            'items': [
                {'item_id': 'item-1', 'name': 'Burger', 'price': 12.50, 'category': 'Entrees'},
                {'item_id': 'item-2', 'name': 'Fries', 'price': 5.00, 'category': 'Sides'},
            ]
        })
        state = project_menu([event])
        assert len(state.items) == 2

    def test_restaurant_configured(self):
        event = _evt(EventType.RESTAURANT_CONFIGURED, {
            'restaurant_name': 'Test Grill',
            'address': '123 Main St',
        })
        state = project_menu([event])
        assert state.restaurant['restaurant_name'] == 'Test Grill'

    def test_modern_category_created(self):
        event = _evt(EventType.MENU_CATEGORY_CREATED, {
            'category_id': 'cat-new',
            'name': 'Desserts',
            'label': 'Desserts',
            'display_order': 5,
        })
        state = project_menu([event])
        assert len(state.categories) == 1
        assert state.categories[0]['name'] == 'Desserts'

    def test_modern_item_created(self):
        event = _evt(EventType.MENU_ITEM_CREATED, {
            'item_id': 'item-new',
            'name': 'Cake',
            'price': 8.00,
            'category': 'Desserts',
        })
        state = project_menu([event])
        assert len(state.items) == 1
        assert state.items[0]['name'] == 'Cake'

    def test_item_updated(self):
        e1 = _evt(EventType.MENU_ITEM_CREATED, {
            'item_id': 'item-1',
            'name': 'Burger',
            'price': 12.00,
            'category': 'Entrees',
        })
        e2 = _evt(EventType.MENU_ITEM_UPDATED, {
            'item_id': 'item-1',
            'price': 14.00,
        })
        state = project_menu([e1, e2])
        assert len(state.items) == 1
        assert state.items[0]['price'] == 14.00

    def test_item_deleted(self):
        e1 = _evt(EventType.MENU_ITEM_CREATED, {
            'item_id': 'item-1',
            'name': 'Burger',
            'price': 12.00,
            'category': 'Entrees',
        })
        e2 = _evt(EventType.MENU_ITEM_DELETED, {'item_id': 'item-1'})
        state = project_menu([e1, e2])
        assert len(state.items) == 0

    def test_category_updated(self):
        e1 = _evt(EventType.MENU_CATEGORY_CREATED, {
            'category_id': 'cat-1',
            'name': 'Apps',
            'label': 'Apps',
            'display_order': 1,
        })
        e2 = _evt(EventType.MENU_CATEGORY_UPDATED, {
            'category_id': 'cat-1',
            'name': 'Appetizers',
        })
        state = project_menu([e1, e2])
        assert len(state.categories) == 1
        assert state.categories[0]['name'] == 'Appetizers'

    def test_items_by_category(self):
        events = [
            _evt(EventType.MENU_ITEM_CREATED, {
                'item_id': 'i1', 'name': 'Burger', 'price': 12.00, 'category': 'Entrees',
            }),
            _evt(EventType.MENU_ITEM_CREATED, {
                'item_id': 'i2', 'name': 'Steak', 'price': 25.00, 'category': 'Entrees',
            }),
            _evt(EventType.MENU_ITEM_CREATED, {
                'item_id': 'i3', 'name': 'Fries', 'price': 5.00, 'category': 'Sides',
            }),
        ]
        state = project_menu(events)
        assert 'Entrees' in state.items_by_category
        assert 'Sides' in state.items_by_category
        assert len(state.items_by_category['Entrees']) == 2
        assert len(state.items_by_category['Sides']) == 1

    def test_modifier_group_lifecycle(self):
        e1 = _evt(EventType.MODIFIER_GROUP_CREATED, {
            'group_id': 'mg-1',
            'name': 'Cooking Temp',
            'options': ['Rare', 'Medium', 'Well Done'],
        })
        state = project_menu([e1])
        assert len(state.modifier_groups) == 1
        assert state.modifier_groups[0]['name'] == 'Cooking Temp'

        # Update
        e2 = _evt(EventType.MODIFIER_GROUP_UPDATED, {
            'group_id': 'mg-1',
            'name': 'Temperature',
        })
        state = project_menu([e1, e2])
        assert len(state.modifier_groups) == 1
        assert state.modifier_groups[0]['name'] == 'Temperature'

        # Delete
        e3 = _evt(EventType.MODIFIER_GROUP_DELETED, {'group_id': 'mg-1'})
        state = project_menu([e1, e2, e3])
        assert len(state.modifier_groups) == 0

    def test_category_sort_order(self):
        events = [
            _evt(EventType.MENU_CATEGORY_CREATED, {
                'category_id': 'c3', 'name': 'Desserts', 'label': 'Desserts', 'display_order': 30,
            }),
            _evt(EventType.MENU_CATEGORY_CREATED, {
                'category_id': 'c1', 'name': 'Appetizers', 'label': 'Apps', 'display_order': 10,
            }),
            _evt(EventType.MENU_CATEGORY_CREATED, {
                'category_id': 'c2', 'name': 'Entrees', 'label': 'Entrees', 'display_order': 20,
            }),
        ]
        state = project_menu(events)
        assert len(state.categories) == 3
        assert state.categories[0]['name'] == 'Appetizers'
        assert state.categories[1]['name'] == 'Entrees'
        assert state.categories[2]['name'] == 'Desserts'
