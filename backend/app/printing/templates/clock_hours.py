"""
KINDpos Clock Hours Template — Thermal Print Spec v1.0

Printed on clock-in or clock-out to give the employee a summary of:
  1. Current shift (if clocking out)
  2. Pay-period hours (weekly, Mon–Sun)
"""

from typing import List, Dict, Any
from .base_template import BaseTemplate


class ClockHoursTemplate(BaseTemplate):

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)

        commands.extend(self._render_header(context))
        commands.extend(self._render_shift(context))
        commands.extend(self._render_pay_period(context))

        commands.append({'type': 'feed', 'lines': 5})
        commands.append({'type': 'cut', 'partial': False})
        return commands

    # ------------------------------------------------------------------
    # 1. Header
    # ------------------------------------------------------------------

    def _render_header(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []

        cmds.append({'type': 'text', 'content': ctx.get('restaurant_name', 'KINDpos'), 'bold': True, 'align': 'center', 'double_width': True, 'double_height': True})

        action = ctx.get('action', 'CLOCK OUT')
        cmds.append({'type': 'text', 'content': action, 'bold': True, 'align': 'center', 'double_width': True, 'double_height': True})
        cmds.append({'type': 'feed', 'lines': 1})

        cmds.append({'type': 'text', 'content': f"Employee: {ctx.get('employee_name', 'N/A')}", 'bold': True})
        cmds.append({'type': 'text', 'content': f"Role: {ctx.get('role_name', 'N/A')}"})
        cmds.append({'type': 'text', 'content': f"Date: {ctx.get('date', 'N/A')}"})
        cmds.append({'type': 'text', 'content': f"Time: {ctx.get('time', 'N/A')}"})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 2. Current Shift
    # ------------------------------------------------------------------

    def _render_shift(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  THIS SHIFT  ', 'bold': True, 'reverse': True, 'align': 'center'})

        clock_in = self._format_time(ctx.get('clock_in'))
        clock_out = self._format_time(ctx.get('clock_out'))

        if clock_out and clock_out != 'N/A':
            cmds.append({'type': 'text', 'content': f"In:  {clock_in}"})
            cmds.append({'type': 'text', 'content': f"Out: {clock_out}"})
            cmds.append({'type': 'feed', 'lines': 1})
            duration = ctx.get('shift_duration', '0h 0m')
            cmds.append({'type': 'text', 'content': f"SHIFT HOURS: {duration}", 'bold': True, 'double_width': True, 'align': 'center'})
        else:
            cmds.append({'type': 'text', 'content': f"Clocked in: {clock_in}"})
            cmds.append({'type': 'text', 'content': 'Shift in progress...', 'align': 'center'})

        cmds.append({'type': 'divider', 'char': '='})
        return cmds

    # ------------------------------------------------------------------
    # 3. Pay Period Hours
    # ------------------------------------------------------------------

    def _render_pay_period(self, ctx: Dict) -> List[Dict]:
        cmds: List[Dict] = []
        cpl = self.chars_per_line

        cmds.append({'type': 'text', 'content': '  PAY PERIOD  ', 'bold': True, 'reverse': True, 'align': 'center'})

        period_label = ctx.get('period_label', 'This Week')
        cmds.append({'type': 'text', 'content': period_label, 'align': 'center'})
        cmds.append({'type': 'feed', 'lines': 1})

        # Daily breakdown
        daily = ctx.get('daily_hours', [])
        if daily:
            hdr = f"{'Day':<12}{'In':>8}{'Out':>8}{'Hours':>8}"
            cmds.append({'type': 'text', 'content': hdr[:cpl], 'bold': True})
            cmds.append({'type': 'divider'})

            for day in daily:
                label = day.get('label', '')
                time_in = day.get('in', '--')
                time_out = day.get('out', '--')
                hours = day.get('hours', '')
                line = f"{label:<12}{time_in:>8}{time_out:>8}{hours:>8}"
                cmds.append({'type': 'text', 'content': line[:cpl]})

        cmds.append({'type': 'divider'})

        total = ctx.get('period_total_hours', '0.0')
        cmds.append({'type': 'text', 'content': f"TOTAL HOURS: {total}", 'bold': True, 'double_width': True, 'align': 'center'})

        cmds.append({'type': 'feed', 'lines': 1})
        return cmds
