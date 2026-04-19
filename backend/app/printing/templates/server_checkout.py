"""
KINDpos Server Checkout / Daily Sales Recap Template — v2.0

Hardware: Zywell P80-Serials — 80mm thermal, 42 chars/line
Mode flag: context['mode'] = 'server' or 'recap'

Sections (top to bottom):
  1. Header
  2. Sales Summary
  3. Check Stats
  4. Payment Breakdown
  5. Tips
  6. Tip-Out
  7. Server Summary Table (recap mode only)
  8. Cash Expected Block
"""

from typing import List, Dict, Any
from .base_template import BaseTemplate


class ServerCheckoutTemplate(BaseTemplate):

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        super().__init__(
            paper_width=paper_width,
            chars_per_line=chars_per_line if chars_per_line is not None else 42,
        )

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)
        mode = context.get('mode', 'server')

        commands.extend(self._render_header(context, mode))
        commands.extend(self._render_sales_summary(context))
        commands.extend(self._render_check_stats(context))
        commands.extend(self._render_payment_breakdown(context, mode))
        commands.extend(self._render_tips(context))
        commands.extend(self._render_tip_out(context))

        if mode == 'recap':
            commands.extend(self._render_server_summary(context))

        commands.extend(self._render_cash_expected(context))

        commands.append({'type': 'feed', 'lines': 5})
        commands.append({'type': 'cut', 'partial': False})
        return commands

    # ------------------------------------------------------------------
    # 1. Header
    # ------------------------------------------------------------------

    def _render_header(self, ctx: Dict, mode: str) -> List[Dict]:
        cmds: List[Dict] = []
        venue = ctx.get('venue', {})
        venue_name = venue.get('name') or ctx.get('restaurant_name', 'KINDpos')

        cmds.append({
            'type': 'text', 'content': venue_name,
            'bold': True, 'align': 'center',
        })

        title = 'SERVER CHECKOUT' if mode == 'server' else 'DAILY SALES RECAP'
        cmds.append({
            'type': 'text', 'content': title,
            'font': 'b', 'align': 'center',
        })

        # Date + shift times
        date = ctx.get('date', 'N/A')
        clock_in = self._format_time(ctx.get('clock_in'))
        clock_out = self._format_time(ctx.get('clock_out'))
        if clock_in != 'N/A' and clock_out != 'N/A':
            cmds.append({
                'type': 'text', 'content': f"{date}  {clock_in} - {clock_out}",
                'font': 'b', 'align': 'center',
            })
        else:
            cmds.append({
                'type': 'text', 'content': date,
                'font': 'b', 'align': 'center',
            })

        cmds.append({'type': 'feed', 'lines': 1})

        # Server name — server mode only, LARGE_BOLD (unmissable)
        if mode == 'server':
            server_name = ctx.get('server_name', 'N/A')
            cmds.append({
                'type': 'text', 'content': server_name,
                'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
            })

        terminal_id = ctx.get('terminal_id', '')
        if terminal_id:
            cmds.append({
                'type': 'text', 'content': f"Terminal: {terminal_id}",
                'font': 'b', 'align': 'center',
            })

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 2. Sales Summary
    # ------------------------------------------------------------------

    def _render_sales_summary(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': 'SALES SUMMARY', 'bold': True})

        gross_sales = ctx.get('gross_sales', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Gross Sales', gross_sales, cpl)})

        # Voids / Comps combined
        voids_total = ctx.get('voids_total', 0.0)
        comps_total = ctx.get('comps_total', 0.0)
        discounts_total = ctx.get('discounts_total', 0.0)
        deductions = voids_total + comps_total + discounts_total
        if deductions > 0:
            cmds.append({'type': 'text', 'content': self._money_line('Voids / Comps', -deductions, cpl)})

        cmds.append({'type': 'divider'})

        net_sales = ctx.get('net_sales', 0.0)
        cmds.append({
            'type': 'text',
            'content': self._money_line('Net Sales', net_sales, cpl),
            'bold': True,
        })

        tax_collected = ctx.get('tax_collected', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Tax', tax_collected, cpl)})

        total_collected = ctx.get('total_collected', net_sales + tax_collected)
        cmds.append({
            'type': 'text',
            'content': self._money_line('Total Collected', total_collected, cpl),
            'bold': True,
        })

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 3. Check Stats
    # ------------------------------------------------------------------

    def _render_check_stats(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': 'CHECK STATS', 'bold': True})

        total_checks = ctx.get('total_checks', ctx.get('checks_closed', 0))
        cmds.append({'type': 'text', 'content': f"{'Checks':<{cpl - 10}}{total_checks:>10}"})

        avg_check = ctx.get('avg_check', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Avg Check', avg_check, cpl)})

        covers = ctx.get('covers', 0)
        if covers > 0:
            cmds.append({'type': 'text', 'content': f"{'Covers':<{cpl - 10}}{covers:>10}"})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 4. Payment Breakdown
    # ------------------------------------------------------------------

    def _render_payment_breakdown(self, ctx: Dict, mode: str) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': 'PAYMENT BREAKDOWN', 'bold': True})

        cash_sales = ctx.get('cash_sales', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Cash', cash_sales, cpl)})

        if mode == 'recap':
            # Detailed card breakdown by type
            cmds.append({'type': 'divider'})
            card_types = ctx.get('card_types', [])
            for ct in card_types:
                label = ct.get('label', 'Card')
                total = ct.get('total', 0.0)
                cmds.append({'type': 'text', 'content': self._money_line(label, total, cpl)})
            cmds.append({'type': 'divider'})

            total_card = ctx.get('total_card', ctx.get('card_sales', 0.0))
            cmds.append({
                'type': 'text',
                'content': self._money_line('Total Card', total_card, cpl),
                'bold': True,
            })
            cmds.append({'type': 'divider'})

            total_payments = ctx.get('total_payments', cash_sales + total_card)
            cmds.append({
                'type': 'text',
                'content': self._money_line('TOTAL', total_payments, cpl),
                'bold': True,
            })
        else:
            # Server mode — cash + card + total
            card_sales = ctx.get('card_sales', 0.0)
            cmds.append({'type': 'text', 'content': self._money_line('Card', card_sales, cpl)})
            cmds.append({'type': 'divider'})
            total_payments = ctx.get('total_payments', cash_sales + card_sales)
            cmds.append({
                'type': 'text',
                'content': self._money_line('TOTAL', total_payments, cpl),
                'bold': True,
            })

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 5. Tips
    # ------------------------------------------------------------------

    def _render_tips(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': 'TIPS', 'bold': True})

        cc_tips = ctx.get('cc_tips_total', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Card Tips', cc_tips, cpl)})
        cmds.append({'type': 'divider'})

        total_tips = ctx.get('total_tips', ctx.get('gross_tips', cc_tips))
        cmds.append({
            'type': 'text',
            'content': self._money_line('Total Tips', total_tips, cpl),
            'bold': True,
        })

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 6. Tip-Out
    # ------------------------------------------------------------------

    def _render_tip_out(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line
        venue = ctx.get('venue', {})
        tip_outs = ctx.get('tip_outs', [])
        tipout_rules = venue.get('tipout_rules', [])

        cmds.append({'type': 'text', 'content': 'TIP-OUT', 'bold': True})

        if tip_outs:
            # Pre-calculated tip-out entries from context
            for to in tip_outs:
                role = to.get('role', '')
                rate = to.get('rate', 0.0)
                base = to.get('base', '')
                amount = to.get('amount', 0.0)

                # Format: role  rate% of base  $amount
                rate_pct = f"{int(rate * 100)}%" if rate else ''
                base_label = base.replace('net_', '').replace('_', ' ').title() if base else ''
                desc = f"{rate_pct} of {base_label}" if rate_pct and base_label else ''

                label = f"{role:<14}{desc}"
                cmds.append({'type': 'text', 'content': self._money_line(label, amount, cpl)})
        elif tipout_rules:
            # Calculate from rules
            for rule in tipout_rules:
                role = rule.get('role', '')
                rate = rule.get('rate', 0.0)
                base_key = rule.get('base', 'net_sales')
                base_amount = ctx.get(base_key, 0.0)
                amount = base_amount * rate

                rate_pct = f"{int(rate * 100)}%"
                base_label = base_key.replace('net_', '').replace('_', ' ').title()
                desc = f"{rate_pct} of {base_label}"

                label = f"{role:<14}{desc}"
                cmds.append({'type': 'text', 'content': self._money_line(label, amount, cpl)})

        total_tip_out = ctx.get('total_tip_out', 0.0)
        cmds.append({'type': 'divider'})
        cmds.append({
            'type': 'text',
            'content': self._money_line('Total Tip-Out', total_tip_out, cpl),
            'bold': True,
        })

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 7. Server Summary Table (recap mode only)
    # ------------------------------------------------------------------

    def _render_server_summary(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line
        servers = ctx.get('server_summary', [])

        if not servers:
            return cmds

        cmds.append({'type': 'text', 'content': 'SERVER SUMMARY', 'bold': True})

        # Column header
        hdr = f"{'SERVER':<14}{'NET SALES':>10}{'TIPS':>9}{'CASH':>9}"
        cmds.append({'type': 'text', 'content': hdr[:cpl], 'bold': True})
        cmds.append({'type': 'divider'})

        for srv in servers:
            name = srv.get('name', '')[:13]
            net = srv.get('net_sales', 0.0)
            tips = srv.get('tips', 0.0)
            cash = srv.get('cash', 0.0)
            line = f"{name:<14}${net:>8.2f}  ${tips:>6.2f}  ${cash:>6.2f}"
            cmds.append({'type': 'text', 'content': line[:cpl], 'font': 'b'})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 8. Cash Expected Block
    # ------------------------------------------------------------------

    def _render_cash_expected(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cash_sales = ctx.get('cash_sales', 0.0)
        cc_tips = ctx.get('cc_tips_total', 0.0)
        cash_expected = ctx.get('cash_expected', cash_sales - cc_tips)

        # Calculation box
        box_border = '+' + '-' * (cpl - 2) + '+'
        cmds.append({'type': 'text', 'content': box_border})

        # Box rows: | LABEL                     $amount  |
        inner_w = cpl - 4  # inside | + space ... space + |
        cash_line = self._money_line('CASH SALES', cash_sales, inner_w)
        tips_line = self._money_line('CC TIPS:', -cc_tips, inner_w)
        cmds.append({'type': 'text', 'content': f"| {cash_line} |"})
        cmds.append({'type': 'text', 'content': f"| {tips_line} |"})

        cmds.append({'type': 'text', 'content': box_border})

        # === divider
        cmds.append({'type': 'divider', 'char': '='})

        # CASH EXPECTED label (centered)
        cmds.append({
            'type': 'text', 'content': 'CASH EXPECTED',
            'bold': True, 'align': 'center',
        })

        # Amount — LARGE_BOLD (2x2 + bold)
        if cash_expected < 0:
            amount_str = f"-${abs(cash_expected):.2f}"
        else:
            amount_str = f"${cash_expected:.2f}"
        cmds.append({
            'type': 'text', 'content': amount_str,
            'bold': True, 'double_width': True, 'double_height': True, 'align': 'center',
        })

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _money_line(self, label: str, amount: float, width: int) -> str:
        """Format label + right-aligned dollar amount: {sign}${value:>8.2f}"""
        if amount < 0:
            money = f"-${abs(amount):>8.2f}"
        else:
            money = f" ${amount:>8.2f}"
        padding = width - len(label) - len(money)
        if padding < 1:
            padding = 1
        return f"{label}{' ' * padding}{money}"
