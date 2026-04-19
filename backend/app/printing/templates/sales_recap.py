"""
KINDpos Sales Recap Template — Thermal Print Spec v1.0

Manager-only report: "How did we do today?"
Prints a full-day (or shift) sales summary on thermal receipt paper.

Sections (top to bottom):
  1. Header          — Restaurant, date range, printed-at timestamp
  2. Revenue Summary — Gross, voids, comps, discounts, net, tax
  3. Payment Breakdown — Cash vs card totals, transaction counts
  4. Category Sales  — Per-category net sales breakdown
  5. Check Stats     — Count, average check, covers
  6. Daypart Summary — Breakdown by time period (if data provided)
  7. Footer          — Terminal ID, generated timestamp
"""

from typing import List, Dict, Any
from .base_template import BaseTemplate


class SalesRecapTemplate(BaseTemplate):

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)

        commands.extend(self._render_header(context))
        commands.extend(self._render_revenue_summary(context))
        commands.extend(self._render_payment_breakdown(context))
        commands.extend(self._render_category_sales(context))
        commands.extend(self._render_check_stats(context))
        commands.extend(self._render_daypart_summary(context))
        commands.extend(self._render_footer(context))

        commands.append({'type': 'feed', 'lines': 5})
        commands.append({'type': 'cut', 'partial': False})
        return commands

    # ------------------------------------------------------------------
    # 1. Header
    # ------------------------------------------------------------------

    def _render_header(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []

        cmds.append({'type': 'text', 'content': ctx.get('restaurant_name', 'KINDpos'), 'bold': True, 'align': 'center', 'double_width': True, 'double_height': True})
        cmds.append({'type': 'text', 'content': 'SALES RECAP', 'bold': True, 'align': 'center', 'double_width': True, 'double_height': True})
        cmds.append({'type': 'feed', 'lines': 1})

        # Date or date range
        date_from = ctx.get('date_from', ctx.get('date', ''))
        date_to = ctx.get('date_to', '')
        if date_to and date_to != date_from:
            cmds.append({'type': 'text', 'content': f"Period: {date_from} - {date_to}", 'align': 'center'})
        else:
            cmds.append({'type': 'text', 'content': f"Date: {date_from}", 'align': 'center'})

        printed_by = ctx.get('printed_by', '')
        if printed_by:
            cmds.append({'type': 'text', 'content': f"Printed by: {printed_by}"})

        printed_at = self._format_datetime(ctx.get('printed_at'))
        if printed_at != 'N/A':
            cmds.append({'type': 'text', 'content': f"Printed: {printed_at}"})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 2. Revenue Summary
    # ------------------------------------------------------------------

    def _render_revenue_summary(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  REVENUE  ', 'bold': True, 'reverse': True, 'align': 'center'})

        gross_sales = ctx.get('gross_sales', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Gross Sales', gross_sales, cpl), 'bold': True})

        # Deductions
        voids_total = ctx.get('voids_total', 0.0)
        voids_count = ctx.get('voids_count', 0)
        if voids_total > 0 or voids_count > 0:
            label = f"Voids ({voids_count})" if voids_count else "Voids"
            cmds.append({'type': 'text', 'content': self._money_line(label, -voids_total, cpl)})

        comps_total = ctx.get('comps_total', 0.0)
        comps_count = ctx.get('comps_count', 0)
        if comps_total > 0 or comps_count > 0:
            label = f"Comps ({comps_count})" if comps_count else "Comps"
            cmds.append({'type': 'text', 'content': self._money_line(label, -comps_total, cpl)})

        discounts_total = ctx.get('discounts_total', 0.0)
        discounts_count = ctx.get('discounts_count', 0)
        if discounts_total > 0 or discounts_count > 0:
            label = f"Discounts ({discounts_count})" if discounts_count else "Discounts"
            cmds.append({'type': 'text', 'content': self._money_line(label, -discounts_total, cpl)})

        refunds_total = ctx.get('refunds_total', 0.0)
        if refunds_total > 0:
            cmds.append({'type': 'text', 'content': self._money_line('Refunds', -refunds_total, cpl)})

        cmds.append({'type': 'divider'})

        net_sales = ctx.get('net_sales', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('NET SALES', net_sales, cpl), 'bold': True, 'double_height': True})

        tax_collected = ctx.get('tax_collected', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Tax Collected', tax_collected, cpl)})

        # Per tax line detail if provided
        for tax in ctx.get('tax_lines', []):
            label = tax.get('label', 'Tax')
            amt = tax.get('amount', 0.0)
            cmds.append({'type': 'text', 'content': self._money_line(f"  {label}", amt, cpl)})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 3. Payment Breakdown
    # ------------------------------------------------------------------

    def _render_payment_breakdown(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  PAYMENTS  ', 'bold': True, 'reverse': True, 'align': 'center'})

        cash_sales = ctx.get('cash_sales', 0.0)
        cash_count = ctx.get('cash_count', 0)
        card_sales = ctx.get('card_sales', 0.0)
        card_count = ctx.get('card_count', 0)

        cmds.append({'type': 'text', 'content': self._money_line(f"Cash ({cash_count})", cash_sales, cpl)})
        cmds.append({'type': 'text', 'content': self._money_line(f"Card ({card_count})", card_sales, cpl)})

        # Other payment types if present
        for other in ctx.get('other_payments', []):
            label = other.get('label', 'Other')
            count = other.get('count', 0)
            total = other.get('total', 0.0)
            cmds.append({'type': 'text', 'content': self._money_line(f"{label} ({count})", total, cpl)})

        total_payments = ctx.get('total_payments', cash_sales + card_sales)
        cmds.append({'type': 'divider'})
        cmds.append({'type': 'text', 'content': self._money_line('Total Payments', total_payments, cpl), 'bold': True})

        # Cash expected = cash sales − card tips (card tips paid from drawer)
        cash_expected = ctx.get('cash_expected', cash_sales - ctx.get('card_tips', 0.0))
        cmds.append({'type': 'text', 'content': self._money_line('Cash Expected', cash_expected, cpl)})

        # Tip total
        total_tips = ctx.get('total_tips', 0.0)
        if total_tips > 0:
            cmds.append({'type': 'feed', 'lines': 1})
            cmds.append({'type': 'text', 'content': self._money_line('Tip Total', total_tips, cpl), 'bold': True})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 4. Category Sales
    # ------------------------------------------------------------------

    def _render_category_sales(self, ctx: Dict) -> List[Dict]:
        categories = ctx.get('category_sales', [])
        if not categories:
            return []

        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  SALES BY CATEGORY  ', 'bold': True, 'reverse': True, 'align': 'center'})

        for cat in categories:
            name = cat.get('name', 'Unknown')
            total = cat.get('total', 0.0)
            count = cat.get('count', 0)
            label = f"{name} ({count})" if count else name
            cmds.append({'type': 'text', 'content': self._money_line(label, total, cpl)})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 5. Check Stats
    # ------------------------------------------------------------------

    def _render_check_stats(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  CHECK STATS  ', 'bold': True, 'reverse': True, 'align': 'center'})

        total_checks = ctx.get('total_checks', 0)
        cmds.append({'type': 'text', 'content': f"{'Total Checks:':<{cpl - 10}}{total_checks:>10}"})

        avg_check = ctx.get('avg_check', 0.0)
        cmds.append({'type': 'text', 'content': self._money_line('Average Check', avg_check, cpl)})

        covers = ctx.get('covers', 0)
        if covers > 0:
            cmds.append({'type': 'text', 'content': f"{'Covers (Guests):':<{cpl - 10}}{covers:>10}"})
            ppa = ctx.get('per_person_avg', 0.0)
            if ppa > 0:
                cmds.append({'type': 'text', 'content': self._money_line('Per Person Avg', ppa, cpl)})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 6. Daypart Summary (optional)
    # ------------------------------------------------------------------

    def _render_daypart_summary(self, ctx: Dict) -> List[Dict]:
        dayparts = ctx.get('dayparts', [])
        if not dayparts:
            return []

        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  DAYPART BREAKDOWN  ', 'bold': True, 'reverse': True, 'align': 'center'})

        for dp in dayparts:
            name = dp.get('name', '')
            sales = dp.get('sales', 0.0)
            checks = dp.get('checks', 0)
            label = f"{name} ({checks} chk)" if checks else name
            cmds.append({'type': 'text', 'content': self._money_line(label, sales, cpl)})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 7. Footer
    # ------------------------------------------------------------------

    def _render_footer(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []

        terminal_id = ctx.get('terminal_id', '')
        if terminal_id:
            cmds.append({'type': 'text', 'content': f"Terminal: {terminal_id}", 'font': 'b', 'align': 'center'})

        cmds.append({'type': 'text', 'content': '** MANAGER REPORT — CONFIDENTIAL **', 'font': 'b', 'align': 'center'})

        return cmds

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _money_line(self, label: str, amount: float, width: int) -> str:
        """Format a label + dollar amount right-aligned to fill the line width."""
        if amount < 0:
            money = f"-${abs(amount):.2f}"
        else:
            money = f"${amount:.2f}"
        padding = width - len(label) - len(money) - 1
        if padding < 1:
            padding = 1
        return f"{label}{' ' * padding}{money}"