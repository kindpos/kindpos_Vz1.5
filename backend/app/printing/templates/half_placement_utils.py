"""
Half Placement Utilities

Shared helpers for detecting and categorizing Left/Right half-placement
modifiers, including Extra detection logic.
"""

from typing import Any, Dict, List, Optional, Tuple


def has_half_modifiers(modifiers: List[Any]) -> bool:
    """Return True if any modifier has prefix 'Left' or 'Right'."""
    for mod in modifiers:
        if isinstance(mod, dict):
            prefix = mod.get('prefix')
            if prefix in ('Left', 'Right'):
                return True
    return False


def get_half_modifiers(
    modifiers: List[Any],
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Partition modifiers into whole, left, and right lists.

    Extra detection: if the same modifier name appears both as whole
    (prefix is null/missing) AND as Left or Right, the half entry is
    marked as extra.

    Each returned entry is a dict with:
        name, price, half_price, is_extra, display_name, display_price

    Returns:
        (whole_mods, left_mods, right_mods)
    """
    whole: List[Dict] = []
    left: List[Dict] = []
    right: List[Dict] = []

    # Collect whole modifier names for extra detection
    whole_names: set = set()
    for mod in modifiers:
        if isinstance(mod, dict):
            prefix = mod.get('prefix')
            if not prefix:
                name = mod.get('text') or mod.get('kitchen_text') or mod.get('name', '')
                whole_names.add(name)

    for mod in modifiers:
        if isinstance(mod, dict):
            prefix = mod.get('prefix')
            name = mod.get('text') or mod.get('kitchen_text') or mod.get('name', '')
            price = mod.get('price', 0)
            half_price = mod.get('half_price')

            if prefix == 'Left' or prefix == 'Right':
                is_extra = name in whole_names
                entry = {
                    'name': name,
                    'price': price,
                    'half_price': half_price,
                    'is_extra': is_extra,
                    'display_name': f"Xtra {name}" if is_extra else name,
                    'display_price': half_price,
                }
                if prefix == 'Left':
                    left.append(entry)
                else:
                    right.append(entry)
            else:
                whole.append({
                    'name': name,
                    'price': price,
                    'half_price': half_price,
                    'is_extra': False,
                    'display_name': name,
                    'display_price': price,
                })
        else:
            # Plain string modifier — always whole
            whole.append({
                'name': str(mod),
                'price': 0,
                'half_price': None,
                'is_extra': False,
                'display_name': str(mod),
                'display_price': 0,
            })

    return whole, left, right
