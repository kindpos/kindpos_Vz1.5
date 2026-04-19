"""
KINDpos Delivery Receipt Template — v2.0

Hardware: Zywell P80-Serials — 80mm thermal, 42 chars/line
Triggered automatically on DL orders, prints simultaneously with driver ticket.

Section order:
  1. Venue header (same as guest receipt)
  2. Payment status (LARGE_BOLD centered)
  3. Order info (check, date)
  4. Delivery address block
  5. Items with prices
  6. Totals (subtotal, delivery fee, tax, total)
  7. Payment section (varies by status)
  8. Footer
"""

from typing import List, Dict, Any
from .base_template import BaseTemplate


class DeliveryReceiptTemplate(BaseTemplate):
    """Customer-facing delivery receipt printed on receipt printer."""

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        super().__init__(
            paper_width=paper_width,
            chars_per_line=chars_per_line if chars_per_line is not None else 42,
        )

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)
        venue = context.get('venue', {})
        cpl = self.chars_per_line

        # 1. Venue header
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

        # 2. Payment status (LARGE_BOLD centered — unmissable)
        status_raw = (context.get('payment_status') or 'unknown').upper().replace('_', ' ').replace('-', ' ')
        if 'PREPAID' in status_raw or 'PRE PAID' in status_raw:
            status_label = 'PREPAID'
        elif 'CARD' in status_raw:
            status_label = 'CARD ON DELIVERY'
        else:
            status_label = 'CASH ON DELIVERY'

        commands.append({
            'type': 'text', 'content': status_label,
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })
        commands.append({'type': 'feed', 'lines': 1})

        # 3. Order info
        check = context.get('check_number') or context.get('ticket_number', 'N/A')
        commands.append({
            'type': 'text', 'content': f"Check: {check} | DELIVERY",
            'bold': True,
        })
        closed_at = self._format_datetime(context.get('closed_at'))
        opened_at = self._format_datetime(context.get('opened_at'))
        commands.append({
            'type': 'text',
            'content': f"Date: {closed_at if closed_at != 'N/A' else opened_at}",
        })
        commands.append({'type': 'divider'})

        # 4. Delivery address block
        customer_name = context.get('customer_name', '')
        if customer_name:
            commands.append({'type': 'text', 'content': customer_name, 'bold': True})
        delivery_addr = context.get('delivery_address', '')
        if delivery_addr:
            for line in self._wrap_text(delivery_addr, cpl):
                commands.append({'type': 'text', 'content': line})
        delivery_phone = context.get('phone_number', '')
        if delivery_phone:
            commands.append({'type': 'text', 'content': f"Phone: {delivery_phone}"})
        commands.append({'type': 'divider'})

        # 5. Items with prices
        for item in context.get('items', []):
            qty = item.get('qty', item.get('quantity', 1))
            name = item.get('name', 'Item')
            price = item.get('price', 0.0)
            total = qty * price

            price_str = f"$ {total:.2f}"
            name_w = cpl - len(price_str) - 2
            line = f"{qty} {name[:name_w]:<{name_w}}{price_str}"
            commands.append({'type': 'text', 'content': line, 'bold': True})

            for mod in item.get('modifiers', []):
                mod_text = mod if isinstance(mod, str) else (
                    mod.get('text') or mod.get('name', '')
                )
                commands.append({'type': 'text', 'content': f"   {mod_text}"})

        commands.append({'type': 'divider'})

        # 6. Totals
        subtotal = context.get('subtotal', 0.0)
        commands.append({'type': 'text', 'content': self._money_line('SUBTOTAL:', subtotal, cpl)})

        delivery_fee = context.get('delivery_fee', 0.0)
        if delivery_fee > 0:
            commands.append({'type': 'text', 'content': self._money_line('Delivery Fee:', delivery_fee, cpl)})

        for tax in context.get('tax_lines', []):
            label = tax.get('label', 'Sales Tax')
            amt = tax.get('amount', 0.0)
            commands.append({'type': 'text', 'content': self._money_line(f"{label}:", amt, cpl)})

        order_total = context.get('total', context.get('order_total', 0.0))
        commands.append({
            'type': 'text',
            'content': self._money_line('TOTAL:', order_total, cpl),
            'bold': True,
        })

        # 7. Payment section (varies by status)
        commands.extend(self._render_payment_section(status_label, order_total))

        # 8. Footer
        commands.append({'type': 'feed', 'lines': 1})
        footer_msg = venue.get('footer_message') or context.get('footer_message', 'Thank you! Please come again.')
        for line in self._wrap_text(footer_msg, cpl):
            commands.append({'type': 'text', 'content': line, 'align': 'center'})

        commands.append({'type': 'feed', 'lines': 3})
        commands.append({'type': 'cut', 'partial': True})
        return commands

    # ------------------------------------------------------------------
    # Payment section by status
    # ------------------------------------------------------------------

    def _render_payment_section(self, status_label: str, total: float) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        if status_label == 'PREPAID':
            commands = []
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({
                'type': 'text', 'content': 'PAID -- THANK YOU',
                'bold': True, 'align': 'center',
            })
            return commands

        # CASH ON DELIVERY or CARD ON DELIVERY
        LABEL_W = 18
        MONEY_FILL = "$____________"
        sig_fill = '_' * (cpl - LABEL_W)

        cmds.append({'type': 'feed', 'lines': 1})
        cmds.append({
            'type': 'text', 'content': 'AMOUNT DUE',
            'bold': True, 'align': 'center',
        })
        cmds.append({
            'type': 'text', 'content': f"${total:.2f}",
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })

        cmds.append({'type': 'divider'})
        cmds.append({'type': 'text', 'content': f"{'TIP:':<{LABEL_W}}{MONEY_FILL}"})
        cmds.append({'type': 'feed', 'lines': 1})
        cmds.append({'type': 'text', 'content': f"{'TOTAL:':<{LABEL_W}}{MONEY_FILL}"})
        cmds.append({'type': 'feed', 'lines': 1})
        cmds.append({'type': 'text', 'content': f"{'SIGNATURE:':<{LABEL_W}}{sig_fill}"})
        cmds.append({'type': 'divider'})

        return cmds

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _money_line(self, label: str, amount: float, width: int) -> str:
        if amount < 0:
            money = f"-${abs(amount):>8.2f}"
        else:
            money = f" ${amount:>8.2f}"
        padding = width - len(label) - len(money)
        if padding < 1:
            padding = 1
        return f"{label}{' ' * padding}{money}"
