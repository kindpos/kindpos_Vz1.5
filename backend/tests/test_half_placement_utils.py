"""
Tests for half placement utility functions.
"""

import pytest
from app.printing.templates.half_placement_utils import (
    has_half_modifiers,
    get_half_modifiers,
)


class TestHasHalfModifiers:

    def test_no_half_mods(self):
        mods = [
            {'name': 'Pepperoni', 'price': 1.50},
            {'name': 'Mushrooms', 'price': 1.00},
        ]
        assert has_half_modifiers(mods) is False

    def test_left_mod(self):
        mods = [{'name': 'Pepperoni', 'price': 1.50, 'prefix': 'Left'}]
        assert has_half_modifiers(mods) is True

    def test_right_mod(self):
        mods = [{'name': 'Pepperoni', 'price': 1.50, 'prefix': 'Right'}]
        assert has_half_modifiers(mods) is True

    def test_string_mods(self):
        mods = ['Pepperoni', 'Mushrooms']
        assert has_half_modifiers(mods) is False

    def test_empty(self):
        assert has_half_modifiers([]) is False


class TestGetHalfModifiers:

    def test_whole_only(self):
        """Whole-only: no extras, all in whole list."""
        mods = [
            {'name': 'Pepperoni', 'price': 1.50, 'half_price': 0.75},
            {'name': 'Mushrooms', 'price': 1.00, 'half_price': 0.50},
        ]
        whole, left, right = get_half_modifiers(mods)
        assert len(whole) == 2
        assert len(left) == 0
        assert len(right) == 0
        assert whole[0]['display_name'] == 'Pepperoni'
        assert whole[0]['display_price'] == 1.50
        assert whole[0]['is_extra'] is False

    def test_left_only(self):
        """Left-only: in left list, not extra."""
        mods = [
            {'name': 'Pepperoni', 'price': 1.50, 'half_price': 0.75, 'prefix': 'Left'},
        ]
        whole, left, right = get_half_modifiers(mods)
        assert len(whole) == 0
        assert len(left) == 1
        assert len(right) == 0
        assert left[0]['display_name'] == 'Pepperoni'
        assert left[0]['display_price'] == 0.75
        assert left[0]['is_extra'] is False

    def test_right_only(self):
        """Right-only: in right list, not extra."""
        mods = [
            {'name': 'Mushrooms', 'price': 1.00, 'half_price': 0.50, 'prefix': 'Right'},
        ]
        whole, left, right = get_half_modifiers(mods)
        assert len(whole) == 0
        assert len(left) == 0
        assert len(right) == 1
        assert right[0]['display_name'] == 'Mushrooms'
        assert right[0]['display_price'] == 0.50
        assert right[0]['is_extra'] is False

    def test_whole_plus_left_extra(self):
        """Whole + Left (extra): same modifier appears both whole and left."""
        mods = [
            {'name': 'Pepperoni', 'price': 1.50, 'half_price': 0.75},
            {'name': 'Pepperoni', 'price': 1.50, 'half_price': 0.75, 'prefix': 'Left'},
        ]
        whole, left, right = get_half_modifiers(mods)
        assert len(whole) == 1
        assert len(left) == 1
        assert left[0]['is_extra'] is True
        assert left[0]['display_name'] == 'Xtra Pepperoni'
        assert left[0]['display_price'] == 0.75

    def test_whole_plus_right_extra(self):
        """Whole + Right (extra): same modifier appears both whole and right."""
        mods = [
            {'name': 'Sausage', 'price': 2.00, 'half_price': 1.00},
            {'name': 'Sausage', 'price': 2.00, 'half_price': 1.00, 'prefix': 'Right'},
        ]
        whole, left, right = get_half_modifiers(mods)
        assert len(whole) == 1
        assert len(right) == 1
        assert right[0]['is_extra'] is True
        assert right[0]['display_name'] == 'Xtra Sausage'
        assert right[0]['display_price'] == 1.00

    def test_mixed(self):
        """Mixed: combination of whole, left, right, with extras."""
        mods = [
            {'name': 'Pepperoni', 'price': 1.50, 'half_price': 0.75},          # whole
            {'name': 'Basil', 'price': 0.50, 'half_price': 0.25},              # whole
            {'name': 'Pepperoni', 'price': 1.50, 'half_price': 0.75, 'prefix': 'Left'},  # extra left
            {'name': 'Sausage', 'price': 1.50, 'half_price': 0.75, 'prefix': 'Left'},    # left only
            {'name': 'Mushrooms', 'price': 1.00, 'half_price': 0.50, 'prefix': 'Right'}, # right only
        ]
        whole, left, right = get_half_modifiers(mods)

        assert len(whole) == 2
        assert len(left) == 2
        assert len(right) == 1

        # Pepperoni on left is extra (also exists as whole)
        pep_left = [m for m in left if m['name'] == 'Pepperoni'][0]
        assert pep_left['is_extra'] is True
        assert pep_left['display_name'] == 'Xtra Pepperoni'
        assert pep_left['display_price'] == 0.75

        # Sausage on left is NOT extra (no whole version)
        sausage_left = [m for m in left if m['name'] == 'Sausage'][0]
        assert sausage_left['is_extra'] is False
        assert sausage_left['display_name'] == 'Sausage'

        # Mushrooms on right is NOT extra
        mush_right = right[0]
        assert mush_right['is_extra'] is False
        assert mush_right['display_name'] == 'Mushrooms'
        assert mush_right['display_price'] == 0.50

    def test_free_half_price(self):
        """Half price is None — display_price should be None."""
        mods = [
            {'name': 'Basil', 'price': 0, 'half_price': None, 'prefix': 'Left'},
        ]
        whole, left, right = get_half_modifiers(mods)
        assert left[0]['display_price'] is None
        assert left[0]['is_extra'] is False
