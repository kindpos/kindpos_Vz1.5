"""
KINDpos Driver Ticket Template — v2.0

Hardware: Epson TM-U220 — 9-pin dot matrix, 76mm paper, 33 chars/line
Triggered automatically on DL orders, prints after kitchen ticket.

Section order:
  1. Header (check number, DL, time, promise slot)
  2. Customer name
  3. Address block (LARGE_BOLD word-wrapped)
  4. Delivery instructions
  5. Order list (no prices)
  6. Payment status + total due
  7. Footer
"""

from typing import List, Dict, Any
from .base_template import BaseTemplate

# ── Sizing constants (TM-U220 @ 33 cpl) ──────────────────────────────
KITCHEN_CPL = 33
ADDR_MAX    = KITCHEN_CPL // 2  # 16 — max chars at 2x wide


class DriverTicketTemplate(BaseTemplate):
    """Driver manifest printed on the kitchen dot-matrix printer."""

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        super().__init__(
            paper_width=paper_width,
            chars_per_line=chars_per_line if chars_per_line is not None else KITCHEN_CPL,
        )

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)

        # 1. Header
        commands.extend(self._render_header(context))

        # 2. Customer name (WIDE_BOLD — unmissable)
        customer_name = context.get('customer_name', 'Guest')
        commands.append({
            'type': 'text', 'content': customer_name[:ADDR_MAX],
            'bold': True, 'double_width': True, 'align': 'center',
        })
        commands.append({'type': 'feed', 'lines': 1})

        # 3. Address block (LARGE_BOLD word-wrapped)
        address = context.get('delivery_address', '')
        if address:
            commands.extend(self._render_large_address(address))
            commands.append({'type': 'feed', 'lines': 1})

        # Phone
        phone = context.get('phone_number', '')
        if phone:
            commands.append({'type': 'text', 'content': f"Phone: {phone}", 'bold': True})

        # 4. Delivery instructions
        notes = context.get('delivery_notes') or context.get('delivery_instructions', '')
        if notes:
            commands.append({'type': 'divider'})
            commands.append({'type': 'text', 'content': 'DELIVERY NOTES:', 'bold': True})
            for line in self._wrap_text(notes, self.chars_per_line):
                commands.append({'type': 'text', 'content': line})

        commands.append({'type': 'divider'})

        # 5. Order list (no prices)
        for item in context.get('items', []):
            qty = item.get('qty', item.get('quantity', 1))
            name = item.get('name', 'Item')
            commands.append({'type': 'text', 'content': f"{qty}x {name}", 'bold': True})
            for mod in item.get('modifiers', []):
                mod_text = mod if isinstance(mod, str) else (
                    mod.get('text') or mod.get('name', '')
                )
                commands.append({'type': 'text', 'content': f"  - {mod_text}"})

        # 6. Payment status + total due
        commands.extend(self._render_payment_status(context))

        # 7. Footer
        commands.append({'type': 'feed', 'lines': 5})
        commands.append({'type': 'cut', 'partial': False})
        return commands

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _render_header(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []

        # Check number (LARGE_BOLD)
        check = ctx.get('check_number') or ctx.get('ticket_number', 'N/A')
        cmds.append({
            'type': 'text', 'content': str(check),
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })

        # DL (LARGE_BOLD)
        cmds.append({
            'type': 'text', 'content': 'DL',
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })

        # Time (WIDE)
        fired_at = ctx.get('fired_at') or ctx.get('ordered_at')
        if fired_at:
            cmds.append({
                'type': 'text', 'content': self._format_time(fired_at),
                'double_width': True, 'align': 'center',
            })

        # Promise slot
        promise_time = ctx.get('promise_time') or ctx.get('estimated_delivery_time', '')
        if promise_time:
            cmds.append({
                'type': 'text', 'content': f"Promise: {promise_time}",
                'bold': True, 'align': 'center',
            })

        # Reset before divider
        cmds.append({
            'type': 'text', 'content': '',
            'bold': False, 'double_width': False, 'double_height': False,
        })
        cmds.append({'type': 'divider'})
        return cmds

    # ------------------------------------------------------------------
    # Address rendering — LARGE_BOLD word-wrap to ADDR_MAX
    # ------------------------------------------------------------------

    def _render_large_address(self, address: str) -> List[Dict]:
        """Word-wrap address into LARGE_BOLD lines (16 chars max at 2x)."""
        cmds: List[Dict] = []
        # Split on commas or newlines first, then word-wrap each part
        parts = address.replace('\n', ', ').split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            for line in self._large_wrap(part):
                cmds.append({
                    'type': 'text', 'content': line,
                    'bold': True, 'double_width': True, 'double_height': True,
                    'align': 'center',
                })
        return cmds

    def _large_wrap(self, text: str) -> List[str]:
        """Word-wrap text to ADDR_MAX characters per line."""
        words = text.split()
        lines: List[str] = []
        line = ''
        for word in words:
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= ADDR_MAX:
                line += ' ' + word
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    # ------------------------------------------------------------------
    # Payment status block
    # ------------------------------------------------------------------

    def _render_payment_status(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []

        status_raw = (ctx.get('payment_status') or 'unknown').upper().replace('_', ' ').replace('-', ' ')
        total = ctx.get('order_total', ctx.get('total', 0.0))

        # Normalize to spec labels
        if 'PREPAID' in status_raw or 'PRE PAID' in status_raw:
            status_label = 'PREPAID'
        elif 'CARD' in status_raw:
            status_label = 'CARD ON DELIVERY'
        else:
            status_label = 'CASH ON DELIVERY'

        cmds.append({'type': 'divider', 'char': '='})
        cmds.append({
            'type': 'text', 'content': status_label,
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })
        cmds.append({
            'type': 'text', 'content': f"TOTAL DUE: ${total:.2f}",
            'bold': True, 'align': 'center',
        })
        cmds.append({'type': 'divider', 'char': '='})
        return cmds
