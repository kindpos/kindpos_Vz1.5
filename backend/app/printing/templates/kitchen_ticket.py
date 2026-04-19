"""
KINDpos Kitchen Ticket Template — Five-Zone Model v2.0

Hardware: Epson TM-U220 — 9-pin dot matrix, 76mm paper, 33 chars/line
Uses ESC ! only (GS ! silently ignored on this printer).

Zones:
  Zone 1: Header   — Check #, Order Type Code, Time         (LARGE_BOLD / WIDE)
  Zone 2: Context  — Server, Seats                           (BOLD)
  Zone 3: Items    — Per-seat items, modifiers, half/half    (WIDE_BOLD / NORMAL)
  Zone 4: Alerts   — Allergy, RUSH, VIP                     (existing, correct)
  Zone 5: Footer   — Terminal, ticket x of y, type           (FONT_B)

Ticket types: ORIGINAL, REPRINT, VOID, REFIRE
"""

from typing import List, Dict, Any, Tuple
from collections import Counter
from .base_template import BaseTemplate
from .half_placement_utils import has_half_modifiers, get_half_modifiers

# ── Sizing constants (TM-U220 @ 33 cpl) ──────────────────────────────
KITCHEN_CPL = 33
WIDE_MAX    = KITCHEN_CPL // 2         # 16 — max chars at 2x wide
BOX_COL_W   = (KITCHEN_CPL - 3) // 2   # 15 — pizza box column width

# ── Order type display mapping ────────────────────────────────────────
ORDER_TYPE_DISPLAY = {
    'c': 'C', 'dine_in': 'C',
    'qs': 'QS', 'quick_service': 'QS',
    'tg': 'TG', 'to_go': 'TG', 'togo': 'TG', 'takeout': 'TG',
    'dl': 'DL', 'delivery': 'DL',
}


def flush_sequence() -> bytes:
    """Prepend before INIT to clear stale bytes from previous job."""
    from backend.app.printing.escpos_formatter import CUT_FULL
    return b'\x0a' * 4 + CUT_FULL


class KitchenTicketTemplate(BaseTemplate):

    # Ticket type constants
    ORIGINAL = "ORIGINAL"
    REPRINT = "REPRINT"
    VOID = "VOID"
    REFIRE = "REFIRE"

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        super().__init__(
            paper_width=paper_width,
            chars_per_line=chars_per_line if chars_per_line is not None else KITCHEN_CPL,
        )

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)
        ticket_type = context.get('ticket_type', self.ORIGINAL).upper()
        supports_red = context.get('supports_red', False)

        # Zone 1 — Header Block
        commands.extend(self._render_zone1(context, ticket_type, supports_red))

        # Zone 2 — Context Line
        commands.extend(self._render_zone2(context))

        # Zone 3 — Item Block
        zone3_cmds, allergies = self._render_zone3(context, ticket_type, supports_red)
        commands.extend(zone3_cmds)

        # Zone 4 — Alert Block
        commands.extend(self._render_zone4(context, allergies, supports_red))

        # Companion items — "Send with" block for multi-station orders
        companion = context.get('companion_items', [])
        if companion:
            commands.append({'type': 'divider', 'char': '='})
            names = ', '.join(c.get('name') or c.get('kitchen_text', '') for c in companion)
            commands.append({
                'type': 'text', 'content': f"Send with: {names}",
                'bold': True,
            })

        # Zone 5 — Footer
        commands.extend(self._render_zone5(context, ticket_type))

        commands.append({'type': 'feed', 'lines': 7})
        commands.append({'type': 'cut', 'partial': False})
        return commands

    # ------------------------------------------------------------------
    # Zone 1 — Header Block
    # ------------------------------------------------------------------

    def _render_zone1(self, ctx: Dict, ticket_type: str, supports_red: bool) -> List[Dict]:
        cmds: List[Dict] = []

        # Line 1 — Check number (LARGE_BOLD = 2x2 + bold)
        check = ctx.get('check_number') or ctx.get('ticket_number', 'N/A')
        cmds.append({
            'type': 'text', 'content': str(check),
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })

        # Ticket-type header additions (REPRINT / VOID / REFIRE)
        if ticket_type == self.REPRINT:
            cmds.append({
                'type': 'text', 'content': 'REPRINT',
                'bold': True, 'align': 'center',
            })
        elif ticket_type == self.VOID:
            cmds.append({
                'type': 'text', 'content': '  VOID  ',
                'bold': True, 'align': 'center',
                'reverse': True, 'red': supports_red,
            })
        elif ticket_type == self.REFIRE:
            cmds.append({
                'type': 'text', 'content': '** REFIRE **',
                'bold': True, 'align': 'center', 'red': supports_red,
            })

        # Line 2 — Order Type Code (LARGE_BOLD = 2x2 + bold)
        order_type = (ctx.get('order_type') or 'dine_in').lower().replace('-', '_')
        order_type_code = ORDER_TYPE_DISPLAY.get(order_type, order_type.upper())
        cmds.append({
            'type': 'text', 'content': order_type_code,
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })

        # Line 3 — Time (WIDE = 2x1 wide only)
        fired_at = ctx.get('fired_at') or ctx.get('ordered_at')
        if fired_at:
            cmds.append({
                'type': 'text', 'content': self._format_time(fired_at),
                'double_width': True, 'align': 'center',
            })

        # Reset before divider to prevent size leakage
        cmds.append({
            'type': 'text', 'content': '',
            'bold': False, 'double_width': False, 'double_height': False,
        })
        cmds.append({'type': 'divider'})
        return cmds

    # ------------------------------------------------------------------
    # Zone 2 — Context Line
    # ------------------------------------------------------------------

    def _render_zone2(self, ctx: Dict) -> List[Dict]:
        parts: List[str] = []

        server = ctx.get('server') or ctx.get('server_name')
        if server:
            parts.append(f"Server: {server}")

        seats = ctx.get('seats')
        if seats:
            if isinstance(seats, list):
                if len(seats) == 1:
                    parts.append(f"Seats: {seats[0]}")
                else:
                    parts.append(f"Seats: {','.join(str(s) for s in seats)}")
            else:
                parts.append(f"Seats: {seats}")

        if not parts:
            return []

        return [
            {'type': 'text', 'content': ' | '.join(parts), 'bold': True},
            {'type': 'divider'},
        ]

    # ------------------------------------------------------------------
    # Zone 3 — Item Block (per seat)
    # ------------------------------------------------------------------

    def _render_zone3(
        self, ctx: Dict, ticket_type: str, supports_red: bool,
    ) -> Tuple[List[Dict], List[str]]:
        """Returns (commands, allergy_types_collected)."""
        cmds: List[Dict] = []
        allergies: List[str] = []
        items = ctx.get('items', [])

        # Consolidate identical items (same name + same modifier set)
        if ticket_type == self.ORIGINAL:
            items = self._consolidate_items(items)

        # Group items by seat
        seat_groups = self._group_by_seat(items)
        seat_keys = list(seat_groups.keys())

        for seat_idx, seat_key in enumerate(seat_keys):
            seat_items = seat_groups[seat_key]

            # Seat header (BOLD)
            if len(seat_keys) > 1 or seat_key != '_default':
                cmds.append({
                    'type': 'text', 'content': f"SEAT {seat_key}",
                    'bold': True,
                })

            for item in seat_items:
                qty = item.get('qty', item.get('quantity', 1))
                name = item.get('kitchen_text') or item.get('name', '')
                modifiers = item.get('modifiers', [])
                special = item.get('special_instructions', '')
                allergy = item.get('allergy') or item.get('allergy_type', '')
                reason = item.get('reason', '')

                # Item line: WIDE_BOLD (2x wide + bold), truncate to fit
                prefix = ""
                if ticket_type == self.VOID:
                    prefix = "[VOID] "

                # Truncate name so qty prefix + name fits in WIDE_MAX chars
                qty_prefix = f"{prefix}{qty}x "
                max_name_len = WIDE_MAX - len(qty_prefix)
                truncated_name = name[:max_name_len] if len(name) > max_name_len else name
                item_line = f"{qty_prefix}{truncated_name}"

                cmds.append({
                    'type': 'text', 'content': item_line,
                    'bold': True, 'double_width': True,
                })

                # Modifiers — half-placement split or flat
                has_halves = has_half_modifiers(modifiers)
                if has_halves:
                    cmds.extend(self._render_half_placement_block(modifiers, supports_red))
                else:
                    for mod in modifiers:
                        mod_cmds = self._render_modifier(mod, supports_red)
                        cmds.extend(mod_cmds)

                # Special instructions (below modifiers)
                if special and not self._is_allergy_instruction(special):
                    cmds.append({'type': 'text', 'content': f'      "{special}"'})

                # Refire reason
                if ticket_type == self.REFIRE and reason:
                    cmds.append({'type': 'text', 'content': f'      Reason: {reason}'})

                # Inline allergy flag (Zone 3 placement)
                if allergy:
                    allergy_upper = allergy.upper()
                    allergies.append(allergy_upper)
                    cmds.append({
                        'type': 'text',
                        'content': f"  {allergy_upper} ALLERGY  ",
                        'bold': True, 'reverse': True, 'red': supports_red, 'align': 'center',
                    })
                elif self._is_allergy_instruction(special):
                    allergy_type = self._extract_allergy_type(special)
                    if allergy_type:
                        allergies.append(allergy_type)
                        cmds.append({
                            'type': 'text',
                            'content': f"  {allergy_type} ALLERGY  ",
                            'bold': True, 'reverse': True, 'red': supports_red, 'align': 'center',
                        })

            # RED seat divider between seats (not after last seat)
            if seat_idx < len(seat_keys) - 1:
                cmds.append({
                    'type': 'divider', 'char': '-',
                    'red': supports_red,
                })

        return cmds, allergies

    def _group_by_seat(self, items: List[Dict]) -> Dict[str, List[Dict]]:
        """Group items by seat number. Items without a seat go to '_default'."""
        groups: Dict[str, List[Dict]] = {}
        for item in items:
            seat = str(item.get('seat', '_default'))
            groups.setdefault(seat, []).append(item)
        return groups

    def _render_modifier(self, mod: Any, supports_red: bool) -> List[Dict]:
        """Render a single modifier line — 6-space indent, NORMAL weight, BLACK."""
        if isinstance(mod, dict):
            prefix = mod.get('prefix', '')
            text = mod.get('text') or mod.get('kitchen_text') or mod.get('name', '')
            mod_type = mod.get('type') or mod.get('action', '')
            if not prefix and mod_type:
                prefix = self._default_prefix(mod_type)
            # Sub-modifiers (modified modifiers) — 9-space indent
            sub_mods = mod.get('sub_modifiers', mod.get('modifiers', []))
        else:
            prefix, text = self._parse_modifier_string(str(mod))
            sub_mods = []

        cmds: List[Dict] = []
        if prefix:
            cmds.append({
                'type': 'text',
                'content': f"      [{prefix}] {text}",
            })
        else:
            cmds.append({'type': 'text', 'content': f"      {text}"})

        # Sub-modifiers at 9-space indent
        for sub in sub_mods:
            sub_text = sub if isinstance(sub, str) else (
                sub.get('text') or sub.get('kitchen_text') or sub.get('name', '')
            )
            cmds.append({'type': 'text', 'content': f"         > {sub_text}"})

        return cmds

    def _render_half_placement_block(
        self, modifiers: List[Any], supports_red: bool,
    ) -> List[Dict]:
        """Render pizza half/half table with red borders and black content."""
        cmds: List[Dict] = []
        whole_mods, left_mods, right_mods = get_half_modifiers(modifiers)

        # Whole modifiers above the table (flat)
        for wm in whole_mods:
            cmds.append({'type': 'text', 'content': f"      {wm['name']}"})

        # +---+---+ box table
        border_line = '+' + '-' * BOX_COL_W + '+' + '-' * BOX_COL_W + '+'

        # Top border (red)
        cmds.append({'type': 'text', 'content': border_line, 'red': supports_red})

        # Header row: |  1ST  |  2ND  | — bold content, red pipes
        hdr_left = '1ST'.center(BOX_COL_W)
        hdr_right = '2ND'.center(BOX_COL_W)
        cmds.append({
            'type': 'text',
            'content': f"|{hdr_left}|{hdr_right}|",
            'bold': True,
        })

        # Middle border (red)
        cmds.append({'type': 'text', 'content': border_line, 'red': supports_red})

        # Content rows — black text, red pipes
        max_rows = max(len(left_mods), len(right_mods), 1) if (left_mods or right_mods) else 0
        for row in range(max_rows):
            left_text = ''
            right_text = ''
            if row < len(left_mods):
                name = left_mods[row]['display_name']
                left_text = name[:BOX_COL_W].ljust(BOX_COL_W)
            else:
                left_text = ' ' * BOX_COL_W
            if row < len(right_mods):
                name = right_mods[row]['display_name']
                right_text = name[:BOX_COL_W].ljust(BOX_COL_W)
            else:
                right_text = ' ' * BOX_COL_W

            cmds.append({
                'type': 'text',
                'content': f"|{left_text}|{right_text}|",
            })

        # Bottom border (red)
        cmds.append({'type': 'text', 'content': border_line, 'red': supports_red})
        return cmds

    def _parse_modifier_string(self, mod: str) -> Tuple[str, str]:
        """Try to extract a prefix from a plain string modifier."""
        known_prefixes = {
            'no ': 'NO', 'add ': 'ADD', 'sub ': 'SUB',
            'extra ': 'EXTRA', 'light ': 'LIGHT', 'side ': 'SIDE',
            'ots ': 'OTS', 'on the side ': 'OTS',
            '86 ': '86',
        }
        mod_lower = mod.lower()
        for pattern, prefix in known_prefixes.items():
            if mod_lower.startswith(pattern):
                return prefix, mod[len(pattern):]
        return '', mod

    def _default_prefix(self, mod_type: str) -> str:
        """Map modifier type to default prefix."""
        return {
            'remove': 'NO', 'add': 'ADD', 'substitute': 'SUB',
            'extra': 'EXTRA', 'light': 'LIGHT', 'side': 'SIDE',
            'on_the_side': 'OTS',
        }.get(mod_type.lower(), '')

    def _consolidate_items(self, items: List[Dict]) -> List[Dict]:
        """
        Identical items with identical modifiers collapse into a single {qty}x line.
        Modifier match is order-independent.
        """
        groups: List[Tuple[str, frozenset, Dict]] = []

        for item in items:
            name = item.get('kitchen_text') or item.get('name', '')
            mods = item.get('modifiers', [])
            mod_key = frozenset(str(m) for m in mods)
            allergy = item.get('allergy') or item.get('allergy_type', '')
            special = item.get('special_instructions', '')

            matched = False
            for i, (g_name, g_mods, g_item) in enumerate(groups):
                if g_name == name and g_mods == mod_key:
                    g_allergy = g_item.get('allergy') or g_item.get('allergy_type', '')
                    g_special = g_item.get('special_instructions', '')
                    if g_allergy == allergy and g_special == special:
                        g_item['qty'] = g_item.get('qty', 1) + 1
                        matched = True
                        break

            if not matched:
                consolidated = dict(item)
                consolidated.setdefault('qty', 1)
                groups.append((name, mod_key, consolidated))

        return [g[2] for g in groups]

    def _is_allergy_instruction(self, text: str) -> bool:
        if not text:
            return False
        return 'ALLERGY' in text.upper()

    def _extract_allergy_type(self, text: str) -> str:
        """Extract allergy type from strings like '!! ALLERGY: NO PEANUTS !!'."""
        upper = text.upper().strip('! ').strip()
        if ':' in upper:
            after_colon = upper.split(':', 1)[1].strip()
            if after_colon.startswith('NO '):
                after_colon = after_colon[3:]
            return after_colon
        return upper.replace('ALLERGY', '').strip()

    # ------------------------------------------------------------------
    # Zone 4 — Alert Block (safety-critical) — existing impl is correct
    # ------------------------------------------------------------------

    def _render_zone4(
        self, ctx: Dict, allergies: List[str], supports_red: bool,
    ) -> List[Dict]:
        cmds: List[Dict] = []

        if allergies:
            cmds.append({'type': 'divider'})
            unique_allergies = sorted(set(allergies))
            allergy_text = ', '.join(unique_allergies)
            cmds.append({
                'type': 'text',
                'content': f"  ALLERGY: {allergy_text}  ",
                'bold': True, 'reverse': True, 'red': supports_red, 'align': 'center',
            })
            cmds.append({'type': 'divider'})

        if ctx.get('rush'):
            cmds.append({
                'type': 'text', 'content': '** RUSH **',
                'bold': True, 'red': supports_red, 'align': 'center',
            })

        if ctx.get('vip'):
            cmds.append({
                'type': 'text', 'content': '** VIP TABLE **',
                'bold': True, 'red': supports_red, 'align': 'center',
            })

        for warning in ctx.get('warnings_86', []):
            cmds.append({
                'type': 'text', 'content': f"** 86 {warning} AFTER THIS **",
                'bold': True, 'red': supports_red, 'align': 'center',
            })

        return cmds

    # ------------------------------------------------------------------
    # Zone 5 — Footer (FONT_B, centered)
    # ------------------------------------------------------------------

    def _render_zone5(self, ctx: Dict, ticket_type: str) -> List[Dict]:
        cmds: List[Dict] = []
        cmds.append({'type': 'divider'})

        terminal_id = ctx.get('terminal_id', '')
        ticket_index = ctx.get('ticket_index', 1)
        ticket_total = ctx.get('ticket_total', 1)

        footer_parts = []
        if terminal_id:
            footer_parts.append(f"Terminal: {terminal_id}")
        footer_parts.append(f"Ticket {ticket_index} of {ticket_total}")

        cmds.append({
            'type': 'text', 'content': ' | '.join(footer_parts),
            'font': 'b', 'align': 'center',
        })

        if ticket_type == self.ORIGINAL:
            label = 'ORIGINAL'
        elif ticket_type == self.REPRINT:
            label = '*** REPRINT ***'
        elif ticket_type == self.VOID:
            label = '*** VOID ***'
        elif ticket_type == self.REFIRE:
            label = '*** REFIRE ***'
        else:
            label = ticket_type

        cmds.append({
            'type': 'text', 'content': label,
            'font': 'b', 'align': 'center',
        })

        cmds.append({'type': 'divider'})
        return cmds
