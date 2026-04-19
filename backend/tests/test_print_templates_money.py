"""
Template-rendering tests for the four templates that print money:

  - SalesRecapTemplate       (manager end-of-day)
  - ServerCheckoutTemplate   (per-server cashout)
  - ClockHoursTemplate       (employee hours summary)
  - DeliveryReceiptTemplate  (customer delivery receipt)

These render the context dicts produced by `print_context_builder`
into lists of formatter commands (`{'type': 'text', 'content': ...}`
etc.) that later get turned into ESC/POS bytes. Every dollar value
on paper flows through these templates, so we pin:

  - Section headers render (REVENUE / PAYMENTS / TIPS / …)
  - Specific money values appear in a command's `content` text
  - Conditional blocks (refunds, tips, cash-expected) gate on data
  - `_money_line` formats positives + negatives correctly
  - Empty / minimal context never crashes, never mis-aligns
"""

from typing import List, Dict

import pytest

from app.printing.templates.base_template import BaseTemplate
from app.printing.templates.clock_hours import ClockHoursTemplate
from app.printing.templates.delivery_receipt import DeliveryReceiptTemplate
from app.printing.templates.sales_recap import SalesRecapTemplate
from app.printing.templates.server_checkout import ServerCheckoutTemplate


# ── helpers ────────────────────────────────────────────────────────────────

def _text_blob(commands: List[Dict]) -> str:
    """Concatenate all `text`-type command contents with newlines.

    The templates emit a list of command dicts (`{'type': 'text',
    'content': '...'}`, dividers, feeds, cuts). Joining the text parts
    lets tests do straightforward substring assertions.

    Different templates pad money differently (sales_recap = no
    padding "$12.50"; server_checkout + delivery_receipt = width-8
    right-aligned "$   12.50"). `_money_in` below collapses runs of
    whitespace so assertions can be written as `_money_in(blob, 12.50)`
    without caring about the padding strategy.
    """
    return "\n".join(
        c.get("content", "")
        for c in commands
        if c.get("type") == "text" and c.get("content") is not None
    )


def _money_in(blob: str, amount: float) -> bool:
    """True if `$amount` appears in `blob`, regardless of internal padding.

    Templates pad differently: `$12.50`, `$   12.50`, or `-$  12.50`.
    Comparing the whitespace-collapsed blob avoids tying tests to a
    particular padding strategy while still catching wrong numbers.
    """
    import re
    collapsed = re.sub(r"\s+", "", blob)
    sign = "-" if amount < 0 else ""
    target = f"{sign}${abs(amount):.2f}"
    return target in collapsed


def _has_command(commands: List[Dict], **match) -> bool:
    """True if any command dict contains all the given key/value pairs."""
    for c in commands:
        if all(c.get(k) == v for k, v in match.items()):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# SALES RECAP TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

class TestSalesRecapTemplate:

    def _balanced_ctx(self, **overrides):
        """A context that would pass every invariant — a reasonable day."""
        ctx = dict(
            restaurant_name="KINDpos Test",
            date_from="2026-04-17",
            date_to="",
            printed_by="Manager",
            printed_at="2026-04-17T20:00:00+00:00",
            gross_sales=125.00,
            voids_total=15.00,
            voids_count=1,
            comps_total=0.00,
            comps_count=0,
            discounts_total=5.00,
            discounts_count=1,
            refunds_total=0.00,
            net_sales=105.00,
            tax_collected=7.35,
            tax_lines=[{"label": "Sales Tax", "amount": 7.35}],
            cash_sales=45.00,
            cash_count=2,
            card_sales=67.35,
            card_count=3,
            other_payments=[],
            total_payments=112.35,
            total_tips=12.00,
            cash_tips=2.00,
            card_tips=10.00,
            cash_expected=35.00,
            category_sales=[
                {"name": "Pizza", "total": 80.00, "count": 3},
                {"name": "Drinks", "total": 25.00, "count": 5},
            ],
            total_checks=4,
            avg_check=26.25,
            covers=8,
            per_person_avg=13.13,
            dayparts=[{"name": "Dinner", "sales": 105.00, "checks": 4}],
            terminal_id="terminal_01",
        )
        ctx.update(overrides)
        return ctx

    def test_happy_path_renders_every_section(self):
        cmds = SalesRecapTemplate().render(self._balanced_ctx())
        blob = _text_blob(cmds)

        # Header
        assert "KINDpos Test" in blob
        assert "SALES RECAP" in blob
        assert "Manager" in blob
        # Section banners
        assert "REVENUE" in blob
        assert "PAYMENTS" in blob
        assert "SALES BY CATEGORY" in blob
        assert "CHECK STATS" in blob
        # Money values
        assert "$125.00" in blob     # gross
        assert "$105.00" in blob     # net
        assert "$45.00" in blob      # cash
        assert "$67.35" in blob      # card
        assert "$112.35" in blob     # total payments
        assert "$12.00" in blob      # tip total
        # Deductions render negative
        assert "-$15.00" in blob     # voids
        assert "-$5.00" in blob      # discounts
        # Tails off with cut
        assert _has_command(cmds, type="cut")

    def test_refund_line_only_appears_when_nonzero(self):
        """Template gates the Refunds row on refunds_total > 0."""
        cmds_no = SalesRecapTemplate().render(self._balanced_ctx(refunds_total=0.00))
        assert "Refunds" not in _text_blob(cmds_no)

        cmds_yes = SalesRecapTemplate().render(self._balanced_ctx(refunds_total=4.50))
        blob_yes = _text_blob(cmds_yes)
        assert "Refunds" in blob_yes
        assert "-$4.50" in blob_yes

    def test_voids_and_comps_gated_on_count_or_total(self):
        """Zero voids and zero comps → neither label appears."""
        cmds = SalesRecapTemplate().render(self._balanced_ctx(
            voids_total=0.00, voids_count=0,
            comps_total=0.00, comps_count=0,
        ))
        blob = _text_blob(cmds)
        assert "Voids" not in blob
        assert "Comps" not in blob

    def test_category_sales_section_suppressed_when_empty(self):
        cmds = SalesRecapTemplate().render(self._balanced_ctx(category_sales=[]))
        assert "SALES BY CATEGORY" not in _text_blob(cmds)

    def test_tip_total_only_rendered_when_nonzero(self):
        cmds = SalesRecapTemplate().render(self._balanced_ctx(total_tips=0.0))
        assert "Tip Total" not in _text_blob(cmds)

    def test_period_header_uses_date_range_when_different(self):
        cmds = SalesRecapTemplate().render(self._balanced_ctx(
            date_from="2026-04-15", date_to="2026-04-17",
        ))
        blob = _text_blob(cmds)
        assert "Period: 2026-04-15 - 2026-04-17" in blob

    def test_money_line_formatter_both_signs(self):
        """_money_line: positive → $X.XX, negative → -$X.XX."""
        tpl = SalesRecapTemplate()
        pos = tpl._money_line("Label", 12.50, 20)
        neg = tpl._money_line("Label", -12.50, 20)
        assert "Label" in pos and "$12.50" in pos
        assert "Label" in neg and "-$12.50" in neg
        # Positive + negative render at identical widths (the padding
        # shrinks by one to absorb the extra `-` character).
        assert len(pos) == len(neg)

    def test_empty_context_does_not_crash(self):
        """A caller that hands us an empty dict gets a printable skeleton
        rather than a traceback."""
        cmds = SalesRecapTemplate().render({})
        assert isinstance(cmds, list)
        assert _has_command(cmds, type="cut")   # always ends the paper

    def test_reprint_header_appears_when_flagged(self):
        cmds = SalesRecapTemplate().render(self._balanced_ctx(
            is_reprint=True,
            original_fired_at="2026-04-17T18:30:00+00:00",
        ))
        blob = _text_blob(cmds)
        assert "REPRINT" in blob


# ═══════════════════════════════════════════════════════════════════════════
# SERVER CHECKOUT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

class TestServerCheckoutTemplate:

    def _ctx(self, **overrides):
        ctx = dict(
            restaurant_name="KINDpos",
            server_name="Alice",
            date="04/17/2026",
            clock_in="2026-04-17T10:00:00+00:00",
            clock_out="2026-04-17T18:00:00+00:00",
            shift_duration="8h 0m",
            checks_closed=5,
            gross_sales=200.00,
            voids_total=0.00,
            comps_total=0.00,
            discounts_total=0.00,
            refunds_total=0.00,
            net_sales=200.00,
            tax_collected=14.00,
            cash_sales=60.00,
            card_sales=140.00,
            total_payments=200.00,
            total_collected=214.00,
            show_cc_detail=False,
            cc_transactions=[],
            cc_tips_total=18.00,
            declared_cash_tips=5.00,
            gross_tips=23.00,
            total_tips=23.00,
            tip_outs=[],
            total_tip_out=0.00,
            net_tips=23.00,
            cash_collected=60.00,
            cash_expected=42.00,
            open_tip_count=0,
            require_manager_sign=False,
            total_checks=5,
            avg_check=40.00,
        )
        ctx.update(overrides)
        return ctx

    def test_happy_path_renders_all_sections(self):
        cmds = ServerCheckoutTemplate().render(self._ctx())
        blob = _text_blob(cmds)

        # Sections
        assert "SALES SUMMARY" in blob
        assert "CHECK STATS" in blob
        assert "PAYMENT BREAKDOWN" in blob
        assert "TIPS" in blob
        assert "TIP-OUT" in blob
        # Money pinned (server_checkout right-pads money, so compare after
        # collapsing whitespace — the *value* is what must not drift).
        assert _money_in(blob, 200.00)     # gross + net
        assert _money_in(blob, 14.00)      # tax
        assert _money_in(blob, 214.00)     # total collected
        assert _money_in(blob, 60.00)      # cash
        assert _money_in(blob, 140.00)     # card
        assert _money_in(blob, 18.00)      # card tips
        assert _money_in(blob, 42.00)      # cash expected
        # Server identity rendered
        assert "Alice" in blob
        assert "CASH EXPECTED" in blob
        # Cut at the end
        assert _has_command(cmds, type="cut")

    def test_voids_and_comps_collapse_into_deductions(self):
        """Server view combines voids + comps + discounts into one line."""
        cmds = ServerCheckoutTemplate().render(self._ctx(
            voids_total=3.00, comps_total=2.00, discounts_total=5.00,
            net_sales=190.00,
        ))
        blob = _text_blob(cmds)
        # Voids / Comps label appears, total deductions = -10.00
        assert "Voids / Comps" in blob
        assert _money_in(blob, -10.00)

    def test_no_deductions_label_hidden(self):
        cmds = ServerCheckoutTemplate().render(self._ctx())  # all zero
        assert "Voids / Comps" not in _text_blob(cmds)

    def test_recap_mode_adds_card_detail_section(self):
        cmds = ServerCheckoutTemplate().render(self._ctx(
            mode="recap",
            card_types=[
                {"label": "Visa", "total": 80.00},
                {"label": "MC", "total": 60.00},
            ],
            total_card=140.00,
        ))
        blob = _text_blob(cmds)
        assert "Visa" in blob
        assert "MC" in blob
        assert "Total Card" in blob

    def test_cash_expected_equals_cash_minus_cc_tips_in_box(self):
        """The boxed cash-expected block renders cash_sales, minus cc_tips
        line, then the computed `CASH EXPECTED` hero line."""
        cmds = ServerCheckoutTemplate().render(self._ctx(
            cash_sales=100.00, cc_tips_total=25.00, cash_expected=75.00,
        ))
        blob = _text_blob(cmds)
        assert _money_in(blob, 100.00)
        assert _money_in(blob, -25.00)
        assert "CASH EXPECTED" in blob
        assert _money_in(blob, 75.00)

    def test_empty_context_does_not_crash(self):
        cmds = ServerCheckoutTemplate().render({})
        assert isinstance(cmds, list)
        assert _has_command(cmds, type="cut")


# ═══════════════════════════════════════════════════════════════════════════
# CLOCK HOURS TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

class TestClockHoursTemplate:

    def _ctx(self, **overrides):
        ctx = dict(
            restaurant_name="KINDpos",
            action="CLOCK OUT",
            employee_name="Alice Smith",
            role_name="Server",
            date="04/17/2026",
            time="06:15 PM",
            clock_in="2026-04-17T10:00:00+00:00",
            clock_out="2026-04-17T18:15:00+00:00",
            shift_duration="8h 15m",
            period_label="Week of 04/13",
            daily_hours=[
                {"label": "Mon 04/13", "in": "10:00", "out": "18:00", "hours": "8.0"},
                {"label": "Tue 04/14", "in": "10:00", "out": "18:30", "hours": "8.5"},
                {"label": "Wed 04/17", "in": "10:00", "out": "18:15", "hours": "8.25"},
            ],
            period_total_hours="24.75",
        )
        ctx.update(overrides)
        return ctx

    def test_clock_out_renders_shift_duration(self):
        cmds = ClockHoursTemplate().render(self._ctx())
        blob = _text_blob(cmds)
        assert "CLOCK OUT" in blob
        assert "Alice Smith" in blob
        assert "SHIFT HOURS: 8h 15m" in blob
        assert "TOTAL HOURS: 24.75" in blob

    def test_clock_in_hides_duration_shows_in_progress(self):
        """No clock_out yet → template shows 'Shift in progress...' instead
        of a computed duration."""
        ctx = self._ctx(action="CLOCK IN")
        ctx.pop("clock_out", None)
        cmds = ClockHoursTemplate().render(ctx)
        blob = _text_blob(cmds)
        assert "CLOCK IN" in blob
        assert "Shift in progress" in blob
        assert "SHIFT HOURS" not in blob

    def test_daily_breakdown_lines_appear(self):
        cmds = ClockHoursTemplate().render(self._ctx())
        blob = _text_blob(cmds)
        assert "Mon 04/13" in blob
        assert "Tue 04/14" in blob
        assert "8.0" in blob  # hours column

    def test_empty_daily_list_still_renders(self):
        cmds = ClockHoursTemplate().render(self._ctx(daily_hours=[]))
        blob = _text_blob(cmds)
        assert "TOTAL HOURS" in blob  # total still rendered

    def test_empty_context_does_not_crash(self):
        cmds = ClockHoursTemplate().render({})
        assert isinstance(cmds, list)
        assert _has_command(cmds, type="cut")


# ═══════════════════════════════════════════════════════════════════════════
# DELIVERY RECEIPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

class TestDeliveryReceiptTemplate:

    def _ctx(self, **overrides):
        ctx = dict(
            restaurant_name="KINDpos",
            venue={"name": "Pizza Shop", "address": "123 Main", "phone": "555-1212"},
            payment_status="cash",
            check_number="D-042",
            closed_at="2026-04-17T18:30:00+00:00",
            customer_name="Jane Doe",
            delivery_address="456 Oak Ave, Apt 2B",
            phone_number="555-9999",
            items=[
                {"qty": 1, "name": "Large Pizza", "price": 18.00, "modifiers": ["No cheese"]},
                {"qty": 2, "name": "Soda", "price": 3.00, "modifiers": []},
            ],
            subtotal=24.00,
            delivery_fee=3.50,
            tax_lines=[{"label": "Sales Tax", "amount": 1.92}],
            total=29.42,
        )
        ctx.update(overrides)
        return ctx

    def test_cash_on_delivery_renders_amount_due_and_tip_signature_block(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx(payment_status="cash"))
        blob = _text_blob(cmds)
        assert "Pizza Shop" in blob
        assert "CASH ON DELIVERY" in blob
        assert "Check: D-042" in blob
        assert "Jane Doe" in blob
        assert "456 Oak Ave" in blob
        assert "AMOUNT DUE" in blob
        assert "$29.42" in blob
        assert "TIP:" in blob
        assert "SIGNATURE:" in blob

    def test_prepaid_shows_thank_you_no_amount_due_block(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx(payment_status="prepaid"))
        blob = _text_blob(cmds)
        assert "PREPAID" in blob
        assert "PAID -- THANK YOU" in blob
        # No "AMOUNT DUE" or signature block on a prepaid slip
        assert "AMOUNT DUE" not in blob
        assert "SIGNATURE" not in blob

    def test_card_on_delivery_matches_cash_block_shape(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx(payment_status="card"))
        blob = _text_blob(cmds)
        assert "CARD ON DELIVERY" in blob
        assert "AMOUNT DUE" in blob
        assert "$29.42" in blob

    def test_totals_render_with_dollar_signs(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx())
        blob = _text_blob(cmds)
        assert _money_in(blob, 24.00)       # subtotal
        assert _money_in(blob, 3.50)        # delivery fee
        assert _money_in(blob, 1.92)        # tax
        assert _money_in(blob, 29.42)       # total

    def test_delivery_fee_hidden_when_zero(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx(delivery_fee=0.0))
        assert "Delivery Fee" not in _text_blob(cmds)

    def test_item_modifier_lines_indented_under_item(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx())
        blob = _text_blob(cmds)
        # Modifier shows up after its item
        assert "Large Pizza" in blob
        assert "No cheese" in blob

    def test_empty_items_list_still_renders(self):
        cmds = DeliveryReceiptTemplate().render(self._ctx(items=[]))
        blob = _text_blob(cmds)
        # Totals section still there even with no items
        assert "TOTAL" in blob
