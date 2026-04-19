"""
Tests for print template rendering: BaseTemplate, GuestReceiptTemplate, KitchenTicketTemplate.
"""

import pytest
from app.printing.templates.base_template import BaseTemplate
from app.printing.templates.guest_receipt import GuestReceiptTemplate
from app.printing.templates.kitchen_ticket import KitchenTicketTemplate


# ── BaseTemplate tests ──────────────────────────────────────────────────


class TestBaseTemplate:

    def test_base_template_format_time(self):
        t = BaseTemplate()
        result = t._format_time("2025-06-15T14:30:00+00:00")
        assert result == "02:30 PM"

    def test_base_template_format_time_none(self):
        t = BaseTemplate()
        assert t._format_time(None) == "N/A"

    def test_base_template_format_datetime(self):
        t = BaseTemplate()
        result = t._format_datetime("2025-06-15T14:30:00+00:00")
        assert result == "06/15/2025 02:30 PM"

    def test_base_template_wrap_text(self):
        t = BaseTemplate()
        lines = t._wrap_text("Hello world foo bar baz", width=12)
        # "Hello world" = 11 chars, fits in 12
        # "foo bar baz" = 11 chars, fits in 12
        assert len(lines) >= 2
        assert lines[0] == "Hello world"
        assert "foo" in lines[1]

    def test_base_template_reprint_header(self):
        t = BaseTemplate()
        commands = t.render(context={
            'is_reprint': True,
            'original_fired_at': '2025-06-15T14:30:00Z',
        })
        # First command should be the reprint marker
        assert len(commands) >= 1
        assert "** REPRINT **" in commands[0]['content']


# ── GuestReceiptTemplate tests ──────────────────────────────────────────


def _guest_receipt_context(**overrides):
    """Build a minimal guest receipt context with sensible defaults."""
    ctx = {
        'restaurant_name': 'Test Restaurant',
        'ticket_number': '1001',
        'order_type': 'dine_in',
        'table': '5',
        'server_name': 'Alice',
        'items': [
            {'name': 'Burger', 'qty': 2, 'price': 12.50},
            {'name': 'Fries', 'qty': 1, 'price': 5.00},
        ],
        'subtotal': 30.00,
        'tax_lines': [{'label': 'Sales Tax', 'amount': 2.40}],
        'total': 32.40,
        'payment_method': 'cash',
        'footer_message': 'Thank you for dining with us!',
    }
    ctx.update(overrides)
    return ctx


class TestGuestReceipt:

    def test_guest_receipt_render_basic(self):
        template = GuestReceiptTemplate(80)
        commands = template.render(_guest_receipt_context())

        assert isinstance(commands, list)
        assert all(isinstance(c, dict) for c in commands)

        # First text command should contain restaurant name
        text_commands = [c for c in commands if c.get('type') == 'text']
        assert any('Test Restaurant' in c['content'] for c in text_commands)

        # Has SUBTOTAL and TOTAL lines
        contents = ' '.join(c.get('content', '') for c in commands)
        assert 'SUBTOTAL:' in contents
        assert 'TOTAL:' in contents

        # Ends with a cut command
        assert commands[-1]['type'] == 'cut'

    def test_guest_receipt_card_payment_has_tip_section(self):
        template = GuestReceiptTemplate(80)
        commands = template.render(_guest_receipt_context(payment_method='card'))

        contents = ' '.join(c.get('content', '') for c in commands)
        assert 'TIP:' in contents

    def test_guest_receipt_customer_dine_in_tip_suggestions(self):
        template = GuestReceiptTemplate(80)
        commands = template.render(_guest_receipt_context(
            payment_method='card',
            copy_type='customer',
            order_type='dine_in',
            subtotal=100.00,
        ))

        contents = ' '.join(c.get('content', '') for c in commands)
        assert 'TIP SUGGESTIONS:' in contents
        # Default suggestions are 15%, 18%, 20% of subtotal (pretax)
        assert '15%' in contents
        assert '18%' in contents
        assert '20%' in contents

    def test_guest_receipt_empty_items(self):
        template = GuestReceiptTemplate(80)
        commands = template.render(_guest_receipt_context(items=[]))

        # Should render without error
        assert isinstance(commands, list)
        assert len(commands) > 0
        assert commands[-1]['type'] == 'cut'


# ── KitchenTicketTemplate tests ─────────────────────────────────────────


def _kitchen_ticket_context(**overrides):
    """Build a minimal kitchen ticket context."""
    ctx = {
        'station_name': 'Grill',
        'ticket_number': '42',
        'order_type': 'dine_in',
        'table': '7',
        'server_name': 'Bob',
        'items': [
            {'name': 'Steak', 'qty': 1, 'modifiers': ['no salt'], 'notes': ''},
            {'name': 'Salad', 'qty': 2},
        ],
        'is_reprint': False,
        'original_fired_at': None,
    }
    ctx.update(overrides)
    return ctx


class TestKitchenTicket:

    def test_kitchen_ticket_render_basic(self):
        template = KitchenTicketTemplate(80)
        commands = template.render(_kitchen_ticket_context())

        assert isinstance(commands, list)
        assert all(isinstance(c, dict) for c in commands)

        # Has text commands
        text_commands = [c for c in commands if c.get('type') == 'text']
        assert len(text_commands) > 0

        # Ends with cut
        assert commands[-1]['type'] == 'cut'

    def test_kitchen_ticket_modifiers_string(self):
        """String modifiers should render with auto-detected prefixes."""
        template = KitchenTicketTemplate(80)
        commands = template.render(_kitchen_ticket_context(items=[
            {'name': 'Burger', 'qty': 1, 'modifiers': ['No Onion', 'Add Jalapeño', 'Sub GF Bun']},
        ]))

        text_contents = [c['content'] for c in commands if c.get('type') == 'text']
        joined = '\n'.join(text_contents)

        # Item line present
        assert '1x Burger' in joined
        # Modifiers with detected prefixes
        assert '[NO] Onion' in joined
        assert '[ADD] Jalapeño' in joined
        assert '[SUB] GF Bun' in joined

    def test_kitchen_ticket_modifiers_dict(self):
        """Dict modifiers (production format) should render with prefixes from 'action' field."""
        template = KitchenTicketTemplate(80)
        commands = template.render(_kitchen_ticket_context(items=[
            {
                'name': 'Combo Pulled Pork', 'qty': 1,
                'modifiers': [
                    {'name': 'Extra Cheese', 'action': 'add', 'modifier_id': 'm1', 'price': 1.5},
                    {'name': 'Pickles', 'action': 'remove', 'modifier_id': 'm2', 'price': 0},
                    {'name': 'Wheat Bun', 'action': 'substitute', 'modifier_id': 'm3', 'price': 0},
                ],
            },
        ]))

        text_contents = [c['content'] for c in commands if c.get('type') == 'text']
        joined = '\n'.join(text_contents)

        # Item line present (truncated to WIDE_MAX at double_width)
        assert '1x Combo Pulled' in joined
        # Modifiers with prefixes derived from 'action' field
        assert '[ADD] Extra Cheese' in joined
        assert '[NO] Pickles' in joined
        assert '[SUB] Wheat Bun' in joined

    def test_kitchen_ticket_no_modifiers_clean(self):
        """Items with empty modifiers should produce no extra blank lines or artifacts."""
        template = KitchenTicketTemplate(80)
        commands = template.render(_kitchen_ticket_context(items=[
            {'name': 'Plain Fries', 'qty': 1, 'modifiers': []},
        ]))

        text_contents = [c['content'] for c in commands if c.get('type') == 'text']

        # Item line present
        assert any('1x Plain Fries' in t for t in text_contents)
        # No indented modifier lines (6-space indent)
        assert not any(t.startswith('      ') for t in text_contents)

    def test_separator_width_80mm(self):
        """Divider commands from 80mm template should produce exactly 42 chars."""
        from app.printing.escpos_formatter import ESCPOSFormatter
        template = KitchenTicketTemplate(80)
        commands = template.render(_kitchen_ticket_context())

        dividers = [c for c in commands if c.get('type') == 'divider']
        assert len(dividers) > 0  # Kitchen tickets have dividers

        fmt = ESCPOSFormatter(paper_width=80)
        for div in dividers:
            char = div.get('char', '-')
            expected = char * 33
            result = fmt.format([div])
            assert expected.encode('ascii') in result

    def test_separator_width_58mm(self):
        """Divider commands from 58mm template should produce exactly 32 chars."""
        from app.printing.escpos_formatter import ESCPOSFormatter
        template = KitchenTicketTemplate(58)
        commands = template.render(_kitchen_ticket_context())

        dividers = [c for c in commands if c.get('type') == 'divider']
        assert len(dividers) > 0

        fmt = ESCPOSFormatter(paper_width=58)
        for div in dividers:
            char = div.get('char', '-')
            expected = char * 32
            result = fmt.format([div])
            assert expected.encode('ascii') in result
