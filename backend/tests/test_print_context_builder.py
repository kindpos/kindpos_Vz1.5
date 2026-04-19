"""
Receipt-context tests for `services.print_context_builder`.

The module renders every printed receipt's context: Server Checkout,
Sales Recap, and guest receipts. We fixed two silent bugs in it this
session (voids_total mis-populated from refund_total on the server
checkout; voids never accumulated on the sales recap) while it sat
at 6% line coverage. These tests pin the monetary keys in the
returned dicts — plus the canonical identities — so a future
refactor has to *acknowledge* any change to what operators see
printed on paper.

Conventions:
- Every test builds its own tiny event ledger through `real` event
  factories and `project_orders`, the same path production uses.
- `_zero_config` monkeypatches strip tax and cash dual-pricing so
  the expected values are clean integers unless a test explicitly
  opts in by patching settings.
- Every context assertion also re-checks the P&L identity — the
  receipt-level proof that Gross − Voids − Discounts − Refunds = Net.
"""

from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    cash_refund_due,
    create_event,
    item_added,
    order_closed,
    order_created,
    order_voided,
    payment_confirmed,
    payment_initiated,
    tip_adjusted,
    user_logged_in,
    user_logged_out,
)
from app.core.financial_invariants import (
    check_pnl_identity,
    check_tender_reconciliation,
    check_tips_partition,
)
from app.services.print_context_builder import PrintContextBuilder

TEST_DB = Path("./data/test_print_context_builder.db")
TERMINAL = "terminal_pctx"


@pytest.fixture(autouse=True)
def _zero_config(monkeypatch):
    """Strip tax and cash discount so expected values are easy to read."""
    monkeypatch.setattr(settings, "tax_rate", 0.0)
    monkeypatch.setattr(settings, "cash_discount_rate", 0.0)
    monkeypatch.setattr(settings, "tipout_percent", 0.0)


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


# ── helpers: small wrappers so the ledger setup reads like prose ───────────

async def _make_order(
    ledger,
    *,
    order_id: str,
    server_id: str = "emp_1",
    items: list = None,
):
    """Create an order + items. Returns order_id."""
    await ledger.append(order_created(
        terminal_id=TERMINAL,
        order_id=order_id,
        order_type="dine_in",
        guest_count=1,
        server_id=server_id,
        server_name=f"Server {server_id}",
        correlation_id=order_id,
    ))
    for idx, (name, price, qty) in enumerate(items or []):
        await ledger.append(item_added(
            terminal_id=TERMINAL,
            order_id=order_id,
            item_id=f"{order_id}_it_{idx}",
            menu_item_id=f"m_{idx}",
            name=name,
            price=price,
            quantity=qty,
        ))
    return order_id


async def _pay_and_close(
    ledger,
    *,
    order_id: str,
    amount: float,
    method: str = "cash",
    tip: float = 0.0,
    tax: float = 0.0,
    txn_suffix: str = "00",
):
    """Pay + confirm + optional tip + close — full happy-path in three lines."""
    payment_id = f"{order_id}_p_{txn_suffix}"
    await ledger.append(payment_initiated(
        terminal_id=TERMINAL,
        order_id=order_id,
        payment_id=payment_id,
        amount=amount,
        method=method,
    ))
    await ledger.append(payment_confirmed(
        terminal_id=TERMINAL,
        order_id=order_id,
        payment_id=payment_id,
        transaction_id=f"txn_{txn_suffix}{order_id[-4:]}",
        amount=amount,
        tax=tax,
    ))
    if tip > 0:
        await ledger.append(tip_adjusted(
            terminal_id=TERMINAL,
            order_id=order_id,
            payment_id=payment_id,
            tip_amount=tip,
        ))
    await ledger.append(order_closed(
        terminal_id=TERMINAL,
        order_id=order_id,
        total=amount,
    ))
    return payment_id


async def _void(ledger, order_id: str, reason: str = "test void"):
    await ledger.append(order_voided(
        terminal_id=TERMINAL,
        order_id=order_id,
        reason=reason,
    ))


async def _discount(ledger, order_id: str, amount: float):
    await ledger.append(create_event(
        event_type=EventType.DISCOUNT_APPROVED,
        terminal_id=TERMINAL,
        correlation_id=order_id,
        payload={
            "order_id": order_id,
            "discount_type": "test",
            "amount": amount,
            "reason": "test",
        },
    ))


async def _refund(ledger, order_id: str, payment_id: str, amount: float):
    await ledger.append(cash_refund_due(
        terminal_id=TERMINAL,
        order_id=order_id,
        payment_id=payment_id,
        amount=amount,
        reason="test refund",
    ))


# ═══════════════════════════════════════════════════════════════════════════
# SALES RECAP CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

class TestSalesRecapContext:
    """The sales recap is the store-wide end-of-day print. Every money
    field it emits is what the operator sees on the paper."""

    @pytest.mark.asyncio
    async def test_happy_path_cash_and_card(self, ledger):
        # Two orders: one paid cash, one paid card.
        await _make_order(ledger, order_id="o1", items=[("Burger", 10.00, 1)])
        await _pay_and_close(ledger, order_id="o1", amount=10.00, method="cash")

        await _make_order(ledger, order_id="o2", items=[("Pizza", 15.00, 1)])
        await _pay_and_close(
            ledger, order_id="o2", amount=15.00, method="card",
            tip=2.50, txn_suffix="1",
        )

        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(
            printed_by="Manager",
        )

        # Money fields — pinned to exact cents so any drift surfaces.
        assert ctx["gross_sales"] == pytest.approx(25.00)
        assert ctx["voids_total"] == pytest.approx(0.00)
        assert ctx["voids_count"] == 0
        assert ctx["refunds_total"] == pytest.approx(0.00)
        assert ctx["discounts_total"] == pytest.approx(0.00)
        assert ctx["net_sales"] == pytest.approx(25.00)
        assert ctx["cash_sales"] == pytest.approx(10.00)
        assert ctx["cash_count"] == 1
        assert ctx["card_sales"] == pytest.approx(15.00)
        assert ctx["card_count"] == 1
        assert ctx["total_payments"] == pytest.approx(25.00)
        assert ctx["card_tips"] == pytest.approx(2.50)
        assert ctx["cash_tips"] == pytest.approx(0.00)
        assert ctx["total_tips"] == pytest.approx(2.50)
        assert ctx["cash_expected"] == pytest.approx(7.50)  # 10 − 2.50
        assert ctx["total_checks"] == 2
        assert ctx["avg_check"] == pytest.approx(12.50)

        # Invariants — the very identities the runtime gate polices.
        assert check_pnl_identity(
            ctx["gross_sales"], ctx["voids_total"], ctx["discounts_total"],
            ctx["refunds_total"], ctx["net_sales"],
        ).ok
        assert check_tender_reconciliation(
            ctx["cash_sales"], ctx["card_sales"],
            ctx["net_sales"], ctx["tax_collected"],
        ).ok
        assert check_tips_partition(
            ctx["total_tips"], ctx["card_tips"], ctx["cash_tips"],
        ).ok

    @pytest.mark.asyncio
    async def test_voided_orders_roll_into_voids_line(self, ledger):
        """Regression: `voids_total` used to stay at 0 regardless of actual
        voids. The recap now rolls voided subtotals into both gross and
        voids so Gross − Voids − … = Net still holds."""
        await _make_order(ledger, order_id="o_live", items=[("Drink", 5.00, 1)])
        await _pay_and_close(ledger, order_id="o_live", amount=5.00, method="cash")

        await _make_order(ledger, order_id="o_void", items=[("Entrée", 20.00, 1)])
        await _void(ledger, order_id="o_void")

        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(printed_by="M")

        assert ctx["voids_total"] == pytest.approx(20.00)
        assert ctx["voids_count"] == 1
        assert ctx["gross_sales"] == pytest.approx(25.00)  # includes voided $20
        assert ctx["net_sales"] == pytest.approx(5.00)
        # The invariant proves the P&L identity on the receipt itself.
        assert check_pnl_identity(
            ctx["gross_sales"], ctx["voids_total"], ctx["discounts_total"],
            ctx["refunds_total"], ctx["net_sales"],
        ).ok

    @pytest.mark.asyncio
    async def test_discount_and_refund_are_separate(self, ledger):
        """Refunds and discounts must not collide in one bucket — a past
        bug routed refunds into the voids line on the server checkout."""
        await _make_order(ledger, order_id="o_disc", items=[("Item", 30.00, 1)])
        await _discount(ledger, order_id="o_disc", amount=5.00)
        await _pay_and_close(ledger, order_id="o_disc", amount=25.00, method="cash")

        await _make_order(ledger, order_id="o_ref", items=[("Item", 40.00, 1)])
        pid = await _pay_and_close(
            ledger, order_id="o_ref", amount=40.00, method="card", txn_suffix="R",
        )
        await _refund(ledger, order_id="o_ref", payment_id=pid, amount=10.00)

        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(printed_by="M")

        assert ctx["discounts_total"] == pytest.approx(5.00)
        assert ctx["discounts_count"] == 1
        assert ctx["refunds_total"] == pytest.approx(10.00)
        assert ctx["voids_total"] == pytest.approx(0.00)
        # Net after deductions: gross 70 − 0 voids − 5 disc − 10 refund = 55
        assert ctx["net_sales"] == pytest.approx(55.00)

    @pytest.mark.asyncio
    async def test_category_sales_are_grouped(self, ledger):
        """The `category_sales` list drives the category breakdown panel."""
        oid = await _make_order(ledger, order_id="o_cat", items=[])
        # Seed items with distinct categories so we can assert grouping
        for idx, (cat, price) in enumerate([("Pizza", 12.00), ("Drinks", 3.00), ("Pizza", 12.00)]):
            await ledger.append(item_added(
                terminal_id=TERMINAL,
                order_id=oid,
                item_id=f"{oid}_it_{idx}",
                menu_item_id=f"m_{idx}",
                name=f"Item {idx}",
                price=price,
                quantity=1,
                category=cat,
            ))
        await _pay_and_close(ledger, order_id=oid, amount=27.00, method="cash")

        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(printed_by="M")

        cats = {c["name"]: c for c in ctx["category_sales"]}
        assert cats["Pizza"]["total"] == pytest.approx(24.00)
        assert cats["Pizza"]["count"] == 2
        assert cats["Drinks"]["total"] == pytest.approx(3.00)
        # Sorted descending by total
        assert ctx["category_sales"][0]["name"] == "Pizza"

    @pytest.mark.asyncio
    async def test_cash_expected_uses_canonical_formula(self, ledger):
        """Cash Expected = Cash Sales − Card Tips — the fix from SALES_CALC_AUDIT."""
        await _make_order(ledger, order_id="o_cash", items=[("X", 20.00, 1)])
        await _pay_and_close(ledger, order_id="o_cash", amount=20.00, method="cash")

        await _make_order(ledger, order_id="o_card", items=[("Y", 50.00, 1)])
        await _pay_and_close(
            ledger, order_id="o_card", amount=50.00, method="card",
            tip=8.00, txn_suffix="CT",
        )

        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(printed_by="M")

        # Drawer should hold cash sales minus the card tips we owe servers.
        assert ctx["cash_expected"] == pytest.approx(12.00)  # 20 − 8

    @pytest.mark.asyncio
    async def test_empty_day_does_not_explode(self, ledger):
        """Zero orders still produces a valid printable context."""
        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(printed_by="M")
        assert ctx["total_checks"] == 0
        assert ctx["gross_sales"] == pytest.approx(0.00)
        assert ctx["net_sales"] == pytest.approx(0.00)
        assert ctx["avg_check"] == pytest.approx(0.00)
        assert ctx["cash_expected"] == pytest.approx(0.00)

    @pytest.mark.asyncio
    async def test_split_tender_order(self, ledger):
        """One order paid by multiple payments: cash + card. Each payment's
        amount lands in the right bucket; tips only on the card leg count
        toward card_tips."""
        await _make_order(ledger, order_id="o_split", items=[("Feast", 60.00, 1)])
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="o_split", payment_id="pA",
            amount=25.00, method="cash",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="o_split", payment_id="pA",
            transaction_id="txnA", amount=25.00, tax=0.0,
        ))
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="o_split", payment_id="pB",
            amount=35.00, method="card",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="o_split", payment_id="pB",
            transaction_id="txnB", amount=35.00, tax=0.0,
        ))
        await ledger.append(tip_adjusted(
            terminal_id=TERMINAL, order_id="o_split", payment_id="pB",
            tip_amount=5.00,
        ))
        await ledger.append(order_closed(
            terminal_id=TERMINAL, order_id="o_split", total=60.00,
        ))

        ctx = await PrintContextBuilder(ledger).build_sales_recap_context(printed_by="M")

        assert ctx["cash_sales"] == pytest.approx(25.00)
        assert ctx["card_sales"] == pytest.approx(35.00)
        assert ctx["total_payments"] == pytest.approx(60.00)
        assert ctx["card_tips"] == pytest.approx(5.00)
        assert ctx["cash_tips"] == pytest.approx(0.00)
        assert ctx["total_tips"] == pytest.approx(5.00)


# ═══════════════════════════════════════════════════════════════════════════
# SERVER CHECKOUT CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

class TestServerCheckoutContext:
    """Per-server receipt printed at shift end. Filtered to `server_id`.
    Voids owned by this server must flow into the voids line, and
    refunds must live in `refunds_total` (not mis-routed into voids)."""

    @pytest.mark.asyncio
    async def test_happy_path_one_server(self, ledger):
        await ledger.append(user_logged_in(
            terminal_id=TERMINAL, employee_id="emp_A", employee_name="Alice",
        ))
        await _make_order(ledger, order_id="oA_1", server_id="emp_A",
                          items=[("Burger", 12.00, 1)])
        await _pay_and_close(ledger, order_id="oA_1", amount=12.00, method="cash")

        await _make_order(ledger, order_id="oA_2", server_id="emp_A",
                          items=[("Pasta", 18.00, 1)])
        await _pay_and_close(
            ledger, order_id="oA_2", amount=18.00, method="card",
            tip=3.00, txn_suffix="CC",
        )

        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_A", server_name="Alice",
        )

        assert ctx["server_name"] == "Alice"
        assert ctx["checks_closed"] == 2
        assert ctx["gross_sales"] == pytest.approx(30.00)
        assert ctx["voids_total"] == pytest.approx(0.00)
        assert ctx["net_sales"] == pytest.approx(30.00)
        assert ctx["cash_sales"] == pytest.approx(12.00)
        assert ctx["card_sales"] == pytest.approx(18.00)
        assert ctx["cc_tips_total"] == pytest.approx(3.00)
        assert len(ctx["cc_transactions"]) == 1

    @pytest.mark.asyncio
    async def test_refunds_go_to_refunds_total_not_voids(self, ledger):
        """Refund was being mis-routed into `voids_total` for months. This
        test pins the correct fields so that regression can't return."""
        await _make_order(ledger, order_id="oA_ref", server_id="emp_A",
                          items=[("X", 40.00, 1)])
        pid = await _pay_and_close(
            ledger, order_id="oA_ref", amount=40.00, method="card",
            txn_suffix="R",
        )
        await _refund(ledger, order_id="oA_ref", payment_id=pid, amount=10.00)

        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_A", server_name="Alice",
        )

        assert ctx["refunds_total"] == pytest.approx(10.00)
        assert ctx["voids_total"] == pytest.approx(0.00)
        # Net: gross 40 − 0 voids − 0 disc − 10 refund = 30
        assert ctx["net_sales"] == pytest.approx(30.00)

    @pytest.mark.asyncio
    async def test_voided_orders_owned_by_server_flow_into_voids(self, ledger):
        """A server's voided checks land in *their* receipt's voids line."""
        await _make_order(ledger, order_id="oA_live", server_id="emp_A",
                          items=[("Item", 15.00, 1)])
        await _pay_and_close(ledger, order_id="oA_live", amount=15.00, method="cash")

        await _make_order(ledger, order_id="oA_void", server_id="emp_A",
                          items=[("Dish", 25.00, 1)])
        await _void(ledger, order_id="oA_void")

        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_A", server_name="Alice",
        )

        assert ctx["voids_total"] == pytest.approx(25.00)
        assert ctx["gross_sales"] == pytest.approx(40.00)  # includes voided
        assert ctx["net_sales"] == pytest.approx(15.00)
        assert check_pnl_identity(
            ctx["gross_sales"], ctx["voids_total"], ctx["discounts_total"],
            ctx["refunds_total"], ctx["net_sales"],
        ).ok

    @pytest.mark.asyncio
    async def test_other_server_orders_excluded(self, ledger):
        """Filtering by server_id is strict — another server's sales don't
        leak into Alice's checkout."""
        await _make_order(ledger, order_id="oA", server_id="emp_A",
                          items=[("X", 10.00, 1)])
        await _pay_and_close(ledger, order_id="oA", amount=10.00, method="cash")

        await _make_order(ledger, order_id="oB", server_id="emp_B",
                          items=[("Y", 100.00, 1)])
        await _pay_and_close(ledger, order_id="oB", amount=100.00, method="card", txn_suffix="B")

        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_A", server_name="Alice",
        )

        assert ctx["checks_closed"] == 1
        assert ctx["gross_sales"] == pytest.approx(10.00)
        assert ctx["cash_sales"] == pytest.approx(10.00)
        assert ctx["card_sales"] == pytest.approx(0.00)

    @pytest.mark.asyncio
    async def test_declared_cash_tips_flow_into_gross_tips(self, ledger):
        """Server declares cash tips; gross_tips = cc tips + declared cash tips."""
        await _make_order(ledger, order_id="oA_t", server_id="emp_A",
                          items=[("X", 20.00, 1)])
        await _pay_and_close(
            ledger, order_id="oA_t", amount=20.00, method="card",
            tip=2.00, txn_suffix="T",
        )

        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_A", server_name="Alice",
            declared_cash_tips=5.00,
        )

        assert ctx["cc_tips_total"] == pytest.approx(2.00)
        assert ctx["declared_cash_tips"] == pytest.approx(5.00)
        assert ctx["gross_tips"] == pytest.approx(7.00)  # 2 + 5

    @pytest.mark.asyncio
    async def test_clock_times_populate_shift_duration(self, ledger):
        """CLOCK_IN / CLOCK_OUT events for this server produce a shift duration."""
        await ledger.append(user_logged_in(
            terminal_id=TERMINAL, employee_id="emp_A", employee_name="Alice",
        ))
        # Seed a single closed order so the receipt actually has totals
        await _make_order(ledger, order_id="oA_c", server_id="emp_A",
                          items=[("X", 10.00, 1)])
        await _pay_and_close(ledger, order_id="oA_c", amount=10.00, method="cash")
        await ledger.append(user_logged_out(
            terminal_id=TERMINAL, employee_id="emp_A", employee_name="Alice",
        ))

        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_A", server_name="Alice",
        )

        assert ctx["clock_in"] is not None
        assert ctx["clock_out"] is not None
        # Duration renders as "Xh Ym"
        assert ctx["shift_duration"] != ""
        assert "h" in ctx["shift_duration"] and "m" in ctx["shift_duration"]

    @pytest.mark.asyncio
    async def test_empty_server_day_is_safe(self, ledger):
        """Server with no closed orders still produces a valid receipt context."""
        ctx = await PrintContextBuilder(ledger).build_server_checkout_context(
            server_id="emp_nobody", server_name="Nobody",
        )
        assert ctx["checks_closed"] == 0
        assert ctx["gross_sales"] == pytest.approx(0.00)
        assert ctx["net_sales"] == pytest.approx(0.00)
        assert ctx["cc_transactions"] == []
