from typing import List, Dict, Any
from .base_template import BaseTemplate

class DriverReceiptTemplate(BaseTemplate):
    """
    Template for Driver Receipts.
    Audience: The driver. This is a manifest.
    Priority: Customer name, address, phone, payment status.
    """

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)

        # 1. Header (Spec 1.4)
        commands.append({'type': 'text', 'content': context.get('restaurant_name', 'KINDpos'), 'bold': True, 'align': 'center'})
        commands.append({'type': 'text', 'content': f"Phone: {context.get('restaurant_phone', 'N/A')}", 'align': 'center'})
        commands.append({'type': 'divider'})
        
        commands.append({'type': 'text', 'content': "** DRIVER MANIFEST **", 'bold': True, 'align': 'center'})
        commands.append({'type': 'text', 'content': f"TICKET: {context.get('ticket_number', 'N/A')}", 'bold': True, 'align': 'center'})
        commands.append({'type': 'feed', 'lines': 1})

        # 2. Customer Info (Spec 1.4)
        commands.append({'type': 'text', 'content': "CUSTOMER:", 'bold': True})
        commands.append({'type': 'text', 'content': context.get('customer_name', 'Guest'), 'bold': True})
        
        addr = context.get('delivery_address', 'No Address Provided')
        for line in self._wrap_text(addr, self.chars_per_line):
            commands.append({'type': 'text', 'content': line, 'bold': True})
            
        commands.append({'type': 'text', 'content': f"Phone: {context.get('phone_number', 'N/A')}", 'bold': True})
        
        notes = context.get('delivery_notes', '')
        if notes:
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': "DELIVERY NOTES:", 'bold': True})
            for line in self._wrap_text(notes, self.chars_per_line):
                commands.append({'type': 'text', 'content': line, 'bold': True})
        
        commands.append({'type': 'divider'})

        # 3. Ticket Summary
        commands.append({'type': 'text', 'content': "TICKET SUMMARY:", 'bold': True})
        for item in context.get('items', []):
            qty = item.get('qty', 1)
            name = item.get('name', 'Item')
            commands.append({'type': 'text', 'content': f"{qty} x {name}", 'bold': True})
            for mod in item.get('modifiers', []):
                commands.append({'type': 'text', 'content': f"  - {mod}"})
        
        commands.append({'type': 'divider'})

        # 4. Payment Status (Spec 1.4)
        status = context.get('payment_status', 'N/A').upper().replace('_', ' ')
        total = context.get('order_total', 0.0)
        
        commands.append({'type': 'text', 'content': f"PAYMENT: {status}", 'bold': True, 'double_width': True})
        
        if 'PRE-PAID' in status or 'PRE_PAID' in status:
            commands.append({'type': 'text', 'content': f"AMOUNT PAID: ${total:.2f}"})
        else:
            commands.append({'type': 'text', 'content': f"COLLECT CASH: ${total:.2f}", 'bold': True, 'double_width': True})
            
        est_time = context.get('estimated_delivery_time', '')
        if est_time:
            commands.append({'type': 'text', 'content': f"EST. DELIVERY: {est_time}"})

        commands.append({'type': 'feed', 'lines': 3})
        commands.append({'type': 'cut', 'partial': False})
        return commands
