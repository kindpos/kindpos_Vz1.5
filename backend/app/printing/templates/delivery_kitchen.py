from typing import List, Dict, Any
from .base_template import BaseTemplate

class DeliveryKitchenTicketTemplate(BaseTemplate):
    """
    Template for Delivery Kitchen Tickets.
    Operational priorities: Delivery banner, bag seal instructions, address verification.
    """

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)

        # 1. Delivery Banner (Spec 4.5)
        divider = "-" * self.chars_per_line
        commands.append({'type': 'text', 'content': divider})
        commands.append({'type': 'text', 'content': "** DELIVERY **", 'bold': True, 'double_width': True, 'align': 'center'})
        commands.append({'type': 'text', 'content': divider})
        commands.append({'type': 'feed', 'lines': 1})

        # 2. Header Info
        commands.append({'type': 'text', 'content': f"TICKET: {context.get('ticket_number', 'N/A')}", 'bold': True})
        fired_at = self._format_time(context.get('fired_at'))
        commands.append({'type': 'text', 'content': f"Fired: {fired_at}"})
        commands.append({'type': 'divider'})

        # 3. Bag & Seal Instruction Block (Spec 1.3)
        if context.get('bag_seal_required'):
            commands.append({'type': 'text', 'content': "================================", 'align': 'center'})
            commands.append({'type': 'text', 'content': "BAG & SEAL REQUIRED", 'bold': True, 'align': 'center'})
            commands.append({'type': 'text', 'content': "================================", 'align': 'center'})
            commands.append({'type': 'feed', 'lines': 1})

        # 4. Items
        for item in context.get('items', []):
            commands.append({'type': 'text', 'content': f"{item['name']}", 'bold': True})
            for mod in item.get('modifiers', []):
                commands.append({'type': 'text', 'content': f"  - {mod}"})
            
            spec_inst = item.get('special_instructions', '')
            if spec_inst:
                # Reuse the same style as KitchenTicketTemplate for consistency
                commands.append({'type': 'text', 'content': "  ----------------", 'bold': True})
                wrapped = self._wrap_text(spec_inst, self.chars_per_line - 4)
                for line in wrapped:
                    commands.append({'type': 'text', 'content': f"  {line}", 'bold': True})
                commands.append({'type': 'text', 'content': "  ----------------", 'bold': True})
            
            commands.append({'type': 'feed', 'lines': 1})

        # 5. Delivery Address for Verification (Spec 1.3)
        commands.append({'type': 'divider'})
        commands.append({'type': 'text', 'content': "VERIFY ADDRESS:", 'bold': True})
        addr = context.get('delivery_address', 'No Address Provided')
        for line in self._wrap_text(addr, self.chars_per_line):
            commands.append({'type': 'text', 'content': line})

        commands.append({'type': 'feed', 'lines': 2})
        commands.append({'type': 'cut', 'partial': False})
        return commands
