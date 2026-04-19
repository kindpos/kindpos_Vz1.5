"""
KINDpos Guest Receipt Template — v2.0

Hardware: Zywell P80-Serials — 80mm thermal, 42 chars/line
Full GS ! support.

Section order:
  1. Logo (optional)
  2. Venue header
  3. Copy type label
  4. Order info
  5. Items (seat-grouped)
  6. Totals
  7. Payment + tip block
  8. Footer
"""

from typing import List, Dict, Any
from .base_template import BaseTemplate
from .half_placement_utils import has_half_modifiers, get_half_modifiers
from app.core.money import money_round

# ── Order type display mapping (full labels for receipt) ──────────────
ORDER_TYPE_DISPLAY = {
    'c': 'DINE IN', 'dine_in': 'DINE IN',
    'qs': 'QUICK SERVICE', 'quick_service': 'QUICK SERVICE',
    'tg': 'TO GO', 'to_go': 'TO GO', 'togo': 'TO GO', 'takeout': 'TO GO',
    'dl': 'DELIVERY', 'delivery': 'DELIVERY',
}


class GuestReceiptTemplate(BaseTemplate):
    """
    Guest Receipt — financial document for customers.
    Three copy types: Customer, Merchant, Itemized.
    """

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        super().__init__(
            paper_width=paper_width,
            chars_per_line=chars_per_line if chars_per_line is not None else 42,
        )

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)
        venue = context.get('venue', {})
        cpl = self.chars_per_line

        # 1. Logo (optional)
        logo_bytes = venue.get('logo_bytes') or context.get('logo_bytes')
        if logo_bytes:
            commands.append({'type': 'logo', 'data': logo_bytes})
            commands.append({'type': 'feed', 'lines': 1})

        # 2. Venue header
        venue_name = venue.get('name') or context.get('restaurant_name', 'KINDpos')
        commands.append({
            'type': 'text', 'content': venue_name,
            'bold': True, 'double_width': True, 'align': 'center',
        })
        address = venue.get('address') or context.get('address', '')
        if address:
            commands.append({'type': 'text', 'content': address, 'align': 'center', 'font': 'b'})
        phone = venue.get('phone') or context.get('phone', '')
        if phone:
            commands.append({'type': 'text', 'content': phone, 'align': 'center', 'font': 'b'})
        commands.append({'type': 'feed', 'lines': 1})

        # 3. Copy type label
        copy_type = context.get('copy_type', 'customer')
        copy_type_label = copy_type.replace('_', ' ').upper()
        commands.append({
            'type': 'text', 'content': f"** {copy_type_label} COPY **",
            'bold': True, 'align': 'center',
        })
        commands.append({'type': 'feed', 'lines': 1})

        # 4. Order info
        order_type_raw = (context.get('order_type') or 'dine_in').lower().replace('-', '_')
        order_type_label = ORDER_TYPE_DISPLAY.get(order_type_raw, order_type_raw.upper())
        check_number = context.get('check_number') or context.get('ticket_number', 'N/A')

        commands.append({
            'type': 'text',
            'content': f"Check: {check_number} | {order_type_label}",
            'bold': True,
        })
        if context.get('table'):
            commands.append({
                'type': 'text',
                'content': f"Table: {context['table']} | Server: {context.get('server_name', 'N/A')}",
            })
        else:
            commands.append({
                'type': 'text',
                'content': f"Server: {context.get('server_name', 'N/A')}",
            })

        if context.get('customer_name'):
            commands.append({
                'type': 'text', 'content': f"Name: {context['customer_name']}", 'bold': True,
            })

        closed_at = self._format_datetime(context.get('closed_at'))
        opened_at = self._format_datetime(context.get('opened_at'))
        commands.append({
            'type': 'text',
            'content': f"Date: {closed_at if closed_at != 'N/A' else opened_at}",
        })
        commands.append({'type': 'divider'})

        # 5. Items (seat-grouped)
        commands.extend(self._render_items(context))
        commands.append({'type': 'divider'})

        # 6. Totals
        commands.extend(self._render_totals(context))

        # 7. Payment + tip block
        if context.get('payment_method') == 'card':
            last_four = context.get('card_last_four', '****')
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': f"Card: **** **** **** {last_four}"})
            commands.extend(self._render_tip_section(context))

        # 8. Footer
        commands.append({'type': 'feed', 'lines': 2})
        footer_msg = venue.get('footer_message') or context.get('footer_message', 'Thank you! Please come again.')
        for line in self._wrap_text(footer_msg, cpl):
            commands.append({'type': 'text', 'content': line, 'align': 'center'})

        commands.append({'type': 'feed', 'lines': 3})
        commands.append({'type': 'cut', 'partial': True})
        return commands

    # ------------------------------------------------------------------
    # Items — seat-grouped
    # ------------------------------------------------------------------

    def _render_items(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line
        items = context.get('items', [])

        # Group by seat
        seat_groups: Dict[str, List[Dict]] = {}
        for item in items:
            seat = str(item.get('seat', '_default'))
            seat_groups.setdefault(seat, []).append(item)

        show_seats = len(seat_groups) > 1 or '_default' not in seat_groups

        for seat_key, seat_items in seat_groups.items():
            if show_seats:
                cmds.append({
                    'type': 'text', 'content': f"--- Seat {seat_key} ---",
                    'bold': True, 'align': 'center',
                })

            for item in seat_items:
                qty = item.get('qty', 1)
                name = item.get('name', 'Item')
                price = item.get('price', 0.0)
                total = qty * price

                # Item line: qty + name + right-aligned price (BOLD)
                price_str = f"$ {total:.2f}"
                name_w = cpl - len(price_str) - 2
                line = f"{qty} {name[:name_w]:<{name_w}}{price_str}"
                cmds.append({'type': 'text', 'content': line, 'bold': True})

                # Modifiers — half-placement or flat
                item_mods = item.get('modifiers', [])
                if has_half_modifiers(item_mods):
                    cmds.extend(self._render_half_placement_items(item_mods))
                else:
                    for mod in item_mods:
                        mod_text = mod if isinstance(mod, str) else (
                            mod.get('text') or mod.get('name', '')
                        )
                        cmds.append({'type': 'text', 'content': f"   {mod_text}"})

        return cmds

    # ------------------------------------------------------------------
    # Half/Half table (receipt version)
    # ------------------------------------------------------------------

    def _render_half_placement_items(self, modifiers: list) -> list:
        """Render +---+ box for half-placement modifiers with prices."""
        cmds = []
        cpl = self.chars_per_line
        col_w = (cpl - 3) // 2  # 19 for 42-char line
        whole_mods, left_mods, right_mods = get_half_modifiers(modifiers)

        # Whole modifiers above the table
        for wm in whole_mods:
            price = wm['display_price']
            if price:
                cmds.append({'type': 'text', 'content': f"   {wm['name']:<{cpl - 12}} ${price:>6.2f}"})
            else:
                cmds.append({'type': 'text', 'content': f"   {wm['name']}"})

        # +---+---+ box table
        border_line = '+' + '-' * col_w + '+' + '-' * col_w + '+'

        cmds.append({'type': 'text', 'content': border_line})
        hdr_left = '1ST'.center(col_w)
        hdr_right = '2ND'.center(col_w)
        cmds.append({
            'type': 'text',
            'content': f"|{hdr_left}|{hdr_right}|",
            'bold': True,
        })
        cmds.append({'type': 'text', 'content': border_line})

        max_rows = max(len(left_mods), len(right_mods), 1) if (left_mods or right_mods) else 0
        for row in range(max_rows):
            left_text = self._format_half_col(left_mods[row], col_w) if row < len(left_mods) else ' ' * col_w
            right_text = self._format_half_col(right_mods[row], col_w) if row < len(right_mods) else ' ' * col_w
            cmds.append({'type': 'text', 'content': f"|{left_text}|{right_text}|"})

        cmds.append({'type': 'text', 'content': border_line})
        return cmds

    def _format_half_col(self, mod: dict, width: int) -> str:
        """Format a single half-placement modifier entry within a column."""
        name = mod['display_name']
        price = mod['display_price']

        if price:
            price_str = f"${price:.2f}"
            max_name = width - len(price_str) - 2
            if len(name) > max_name:
                name = name[:max_name - 1] + '~'
            return f" {name:<{width - len(price_str) - 1}}{price_str}"
        else:
            if len(name) > width - 1:
                name = name[:width - 2] + '~'
            return f" {name:<{width - 1}}"

    # ------------------------------------------------------------------
    # Totals block
    # ------------------------------------------------------------------

    def _render_totals(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        subtotal = context.get('subtotal', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('SUBTOTAL:', subtotal, cpl)})

        discount_total = context.get('discount_total', 0.0)
        if discount_total > 0:
            cmds.append({'type': 'text', 'content': self._money_line('DISCOUNT:', -discount_total, cpl)})

        for tax in context.get('tax_lines', []):
            label = tax.get('label', 'Sales Tax')
            amt = tax.get('amount', 0.0)
            cmds.append({'type': 'text', 'content': self._money_line(f"{label}:", amt, cpl)})

        total = context.get('total', 0.0)
        cmds.append({
            'type': 'text',
            'content': self._money_line('TOTAL:', total, cpl),
            'bold': True,
        })

        return cmds

    # ------------------------------------------------------------------
    # Tip / Signature block
    # ------------------------------------------------------------------

    def _render_tip_section(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = []
        cpl = self.chars_per_line
        copy_type = context.get('copy_type', 'customer')
        order_type = (context.get('order_type') or '').lower().replace('-', '_')
        venue = context.get('venue', {})

        LABEL_W = 18
        MONEY_FILL = "$____________"
        sig_fill = '_' * (cpl - LABEL_W)

        # Tip suggestions: customer copy + dine-in or bar_tab only
        if copy_type == 'customer' and order_type in ('dine_in', 'bar_tab', 'c'):
            commands.append({'type': 'divider'})
            commands.append({'type': 'text', 'content': 'TIP SUGGESTIONS:', 'bold': True})

            percentages = venue.get('tip_suggestion_percentages') or context.get('tip_suggestion_percentages', [15, 18, 20])
            calc_base = venue.get('tip_calculation_base') or context.get('tip_calculation_base', 'pretax')
            base_amount = context.get('subtotal', 0.0) if calc_base == 'pretax' else context.get('total', 0.0)

            for pct in percentages:
                amount = money_round(base_amount * (pct / 100))
                pct_label = f"  {pct}%"
                commands.append({
                    'type': 'text',
                    'content': f"{pct_label:<{LABEL_W - 4}}${amount:>8.2f}",
                })

            commands.append({'type': 'feed', 'lines': 1})

        # TIP / TOTAL / SIGNATURE fill lines
        commands.append({'type': 'feed', 'lines': 1})
        commands.append({'type': 'text', 'content': f"{'TIP:':<{LABEL_W}}{MONEY_FILL}"})
        commands.append({'type': 'feed', 'lines': 1})
        commands.append({'type': 'text', 'content': f"{'TOTAL:':<{LABEL_W}}{MONEY_FILL}"})
        commands.append({'type': 'feed', 'lines': 1})
        commands.append({'type': 'text', 'content': f"{'SIGNATURE:':<{LABEL_W}}{sig_fill}"})
        commands.append({'type': 'divider'})

        return commands

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _money_line(self, label: str, amount: float, width: int) -> str:
        """Format label + right-aligned ${value:>8.2f} amount."""
        if amount < 0:
            money = f"-${abs(amount):>8.2f}"
        else:
            money = f" ${amount:>8.2f}"
        padding = width - len(label) - len(money)
        if padding < 1:
            padding = 1
        return f"{label}{' ' * padding}{money}"
