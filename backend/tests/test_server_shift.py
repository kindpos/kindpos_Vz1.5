"""
Tests for `api/routes/server_shift.py` — the server landing page's
data source. Four endpoints scoped to a single server's current shift:

  - GET /server/shift/sales-by-category  — Pareto chart data
  - GET /server/shift/table-stats        — guest / table / turn-time math
  - GET /server/shift/checkout-status    — open checks + unadjusted tips
  - PATCH /server/shift/tipout           — stub echoing back the amount

The file sat at 23% coverage — zero tests on the math a server uses
to decide whether they're ready to cash out. These tests pin each
route against the canonical event pipeline.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from app.api.routes.server_shift import (
    TipOutRequest,
    checkout_status,
    patch_tipout,
    sales_by_category,
    table_stats,
)
from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    create_event,
    item_added,
    order_closed,
    order_created,
    order_voided,
    payment_confirmed,
    payment_initiated,
    tip_adjusted,
)


TEST_DB = Path("./data/test_server_shift.db")
TERMINAL = "terminal_shift"


@pytest.fixture(autouse=True)
def _zero_config(monkeypatch):
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


# ── helpers ─────────────────────────────────────────────────────────────────

async def _open_order(
    ledger, *, order_id: str, server_id: str = "emp_A",
    guest_count: int = 1, items: list = None,
):
    """Create an order + items. Items: list of (name, price, qty, category)."""
    await ledger.append(order_created(
        terminal_id=TERMINAL,
        order_id=order_id,
        order_type="dine_in",
        guest_count=guest_count,
        server_id=server_id,
        server_name=f"S_{server_id}",
        correlation_id=order_id,
    ))
    for idx, item in enumerate(items or []):
        name, price, qty, cat = item
        await ledger.append(item_added(
            terminal_id=TERMINAL,
            order_id=order_id,
            item_id=f"{order_id}_it_{idx}",
            menu_item_id=f"m_{idx}",
            name=name,
            price=price,
            quantity=qty,
            category=cat,
        ))
    return order_id


async def _pay(
    ledger, *, order_id: str, amount: float, method: str = "cash",
    suffix: str = "0",
):
    pid = f"{order_id}_p{suffix}"
    await ledger.append(payment_initiated(
        terminal_id=TERMINAL, order_id=order_id, payment_id=pid,
        amount=amount, method=method,
    ))
    await ledger.append(payment_confirmed(
        terminal_id=TERMINAL, order_id=order_id, payment_id=pid,
        transaction_id=f"txn_{pid}", amount=amount, tax=0.0,
    ))
    return pid


async def _close(ledger, order_id: str, total: float):
    await ledger.append(order_closed(
        terminal_id=TERMINAL, order_id=order_id, total=total,
    ))


async def _void(ledger, order_id: str):
    await ledger.append(order_voided(
        terminal_id=TERMINAL, order_id=order_id, reason="test",
    ))


# ═══════════════════════════════════════════════════════════════════════════
# SALES BY CATEGORY
# ═══════════════════════════════════════════════════════════════════════════

class TestSalesByCategory:
    """Pareto chart data — categories ranked by revenue, cash/card split."""

    @pytest.mark.asyncio
    async def test_cash_only_order_all_goes_to_cash(self, ledger):
        await _open_order(ledger, order_id="o1", items=[("Marg", 20.00, 1, "PIZZA")])
        await _pay(ledger, order_id="o1", amount=20.00, method="cash")
        await _close(ledger, "o1", 20.00)

        res = await sales_by_category(server_id="emp_A", ledger=ledger)

        assert len(res) == 1
        pizza = res[0]
        assert pizza["category"] == "PIZZA"
        assert pizza["cash"] == pytest.approx(20.00)
        assert pizza["card"] == pytest.approx(0.00)

    @pytest.mark.asyncio
    async def test_card_only_order_all_goes_to_card(self, ledger):
        await _open_order(ledger, order_id="o2", items=[("Soda", 3.00, 2, "DRINKS")])
        await _pay(ledger, order_id="o2", amount=6.00, method="card")
        await _close(ledger, "o2", 6.00)

        res = await sales_by_category(server_id="emp_A", ledger=ledger)
        drinks = next(c for c in res if c["category"] == "DRINKS")
        assert drinks["cash"] == pytest.approx(0.00)
        assert drinks["card"] == pytest.approx(6.00)

    @pytest.mark.asyncio
    async def test_mixed_tender_splits_fifty_fifty(self, ledger):
        """Split-tender orders aren't traceable to per-item method, so
        the server-shift endpoint splits each item's revenue 50/50."""
        await _open_order(ledger, order_id="o3", items=[("Sub", 12.00, 1, "SUBS")])
        await _pay(ledger, order_id="o3", amount=6.00, method="cash", suffix="A")
        await _pay(ledger, order_id="o3", amount=6.00, method="card", suffix="B")
        await _close(ledger, "o3", 12.00)

        res = await sales_by_category(server_id="emp_A", ledger=ledger)
        subs = next(c for c in res if c["category"] == "SUBS")
        assert subs["cash"] == pytest.approx(6.00)
        assert subs["card"] == pytest.approx(6.00)

    @pytest.mark.asyncio
    async def test_voided_orders_excluded(self, ledger):
        await _open_order(ledger, order_id="o_live",
                          items=[("Wings", 10.00, 1, "APPS")])
        await _pay(ledger, order_id="o_live", amount=10.00, method="cash")
        await _close(ledger, "o_live", 10.00)

        await _open_order(ledger, order_id="o_void",
                          items=[("VoidWings", 100.00, 1, "APPS")])
        await _void(ledger, "o_void")

        res = await sales_by_category(server_id="emp_A", ledger=ledger)
        apps = next(c for c in res if c["category"] == "APPS")
        # Only the live $10 counts — the $100 voided doesn't.
        assert apps["cash"] + apps["card"] == pytest.approx(10.00)

    @pytest.mark.asyncio
    async def test_uncategorized_items_bucketed_as_other(self, ledger):
        """Items with no category land in 'OTHER', uppercased."""
        await _open_order(ledger, order_id="o_unc",
                          items=[("Mystery", 5.00, 1, None)])
        await _pay(ledger, order_id="o_unc", amount=5.00, method="cash")
        await _close(ledger, "o_unc", 5.00)

        res = await sales_by_category(server_id="emp_A", ledger=ledger)
        other = next(c for c in res if c["category"] == "OTHER")
        assert other["cash"] == pytest.approx(5.00)

    @pytest.mark.asyncio
    async def test_sorted_desc_by_total(self, ledger):
        """Bigger categories come first in the response."""
        await _open_order(ledger, order_id="os1", items=[
            ("Pizza", 20.00, 1, "PIZZA"),
            ("Wings", 8.00, 1, "APPS"),
            ("Soda", 4.00, 1, "DRINKS"),
        ])
        await _pay(ledger, order_id="os1", amount=32.00, method="card")
        await _close(ledger, "os1", 32.00)

        res = await sales_by_category(server_id="emp_A", ledger=ledger)
        assert [c["category"] for c in res] == ["PIZZA", "APPS", "DRINKS"]

    @pytest.mark.asyncio
    async def test_cross_server_isolation(self, ledger):
        """Other servers' categories never leak into this one's breakdown."""
        await _open_order(ledger, order_id="oA",
                          server_id="emp_A",
                          items=[("P", 10.00, 1, "PIZZA")])
        await _pay(ledger, order_id="oA", amount=10.00, method="cash")
        await _close(ledger, "oA", 10.00)

        await _open_order(ledger, order_id="oB",
                          server_id="emp_B",
                          items=[("D", 100.00, 1, "DRINKS")])
        await _pay(ledger, order_id="oB", amount=100.00, method="cash")
        await _close(ledger, "oB", 100.00)

        res = await sales_by_category(server_id="emp_A", ledger=ledger)
        assert [c["category"] for c in res] == ["PIZZA"]
        assert res[0]["cash"] + res[0]["card"] == pytest.approx(10.00)


# ═══════════════════════════════════════════════════════════════════════════
# TABLE STATS
# ═══════════════════════════════════════════════════════════════════════════

class TestTableStats:

    @pytest.mark.asyncio
    async def test_guest_and_table_count(self, ledger):
        await _open_order(ledger, order_id="t1", guest_count=2,
                          items=[("X", 10.00, 1, "APPS")])
        await _pay(ledger, order_id="t1", amount=10.00, method="cash")
        await _close(ledger, "t1", 10.00)

        await _open_order(ledger, order_id="t2", guest_count=4,
                          items=[("Y", 40.00, 1, "PIZZA")])
        await _pay(ledger, order_id="t2", amount=40.00, method="card")
        await _close(ledger, "t2", 40.00)

        res = await table_stats(server_id="emp_A", ledger=ledger)
        assert res["guestCount"] == 6
        assert res["tableCount"] == 2
        assert res["checkAvg"] == pytest.approx(25.00)   # 50 / 2

    @pytest.mark.asyncio
    async def test_voided_orders_dont_count(self, ledger):
        await _open_order(ledger, order_id="tL", guest_count=2,
                          items=[("X", 20.00, 1, "APPS")])
        await _pay(ledger, order_id="tL", amount=20.00, method="cash")
        await _close(ledger, "tL", 20.00)

        await _open_order(ledger, order_id="tV", guest_count=8,
                          items=[("Y", 500.00, 1, "APPS")])
        await _void(ledger, "tV")

        res = await table_stats(server_id="emp_A", ledger=ledger)
        assert res["guestCount"] == 2
        assert res["tableCount"] == 1
        assert res["checkAvg"] == pytest.approx(20.00)

    @pytest.mark.asyncio
    async def test_party_size_buckets_cap_at_4(self, ledger):
        """Party sizes ≥4 all bucket into `size=4` (the "4+" bucket)."""
        for gc in [1, 2, 4, 6, 10]:
            oid = f"p_{gc}"
            await _open_order(ledger, order_id=oid, guest_count=gc,
                              items=[("X", 10.00, 1, "PIZZA")])
            await _pay(ledger, order_id=oid, amount=10.00, method="cash")
            await _close(ledger, oid, 10.00)

        res = await table_stats(server_id="emp_A", ledger=ledger)
        sizes = {b["size"]: b for b in res["byPartySize"]}
        assert sizes[1]["tableCount"] == 1
        assert sizes[2]["tableCount"] == 1
        # 4, 6, and 10 all bucket into size=4
        assert sizes[4]["tableCount"] == 3

    @pytest.mark.asyncio
    async def test_empty_shift_returns_zeros(self, ledger):
        res = await table_stats(server_id="emp_nobody", ledger=ledger)
        assert res["guestCount"] == 0
        assert res["tableCount"] == 0
        assert res["checkAvg"] == pytest.approx(0.0)
        assert res["byPartySize"] == []

    @pytest.mark.asyncio
    async def test_check_avg_deducts_discounts(self, ledger):
        """Check avg is based on `subtotal − discounts` (net of discounts)."""
        await _open_order(ledger, order_id="td", guest_count=2,
                          items=[("X", 30.00, 1, "PIZZA")])
        await ledger.append(create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL, correlation_id="td",
            payload={"order_id": "td", "discount_type": "10",
                     "amount": 6.00, "reason": "test"},
        ))
        await _pay(ledger, order_id="td", amount=24.00, method="cash")
        await _close(ledger, "td", 24.00)

        res = await table_stats(server_id="emp_A", ledger=ledger)
        assert res["checkAvg"] == pytest.approx(24.00)   # 30 − 6


# ═══════════════════════════════════════════════════════════════════════════
# CHECKOUT STATUS
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckoutStatus:
    """The readiness gate the server sees before pressing CHECKOUT."""

    @pytest.mark.asyncio
    async def test_open_check_counted(self, ledger):
        await _open_order(ledger, order_id="oo",
                          items=[("X", 10.00, 1, "APPS")])
        # No payment, no close → status stays "open"
        res = await checkout_status(server_id="emp_A", ledger=ledger)
        assert res["openChecks"] == 1
        assert res["unadjustedTips"] == 0

    @pytest.mark.asyncio
    async def test_closed_cash_order_has_no_unadjusted_tips(self, ledger):
        """Cash orders never have unadjusted tips — those only exist on card."""
        await _open_order(ledger, order_id="oc",
                          items=[("X", 10.00, 1, "APPS")])
        await _pay(ledger, order_id="oc", amount=10.00, method="cash")
        await _close(ledger, "oc", 10.00)

        res = await checkout_status(server_id="emp_A", ledger=ledger)
        assert res["openChecks"] == 0
        assert res["unadjustedTips"] == 0

    @pytest.mark.asyncio
    async def test_card_payment_without_tip_adjust_is_unadjusted(self, ledger):
        """A confirmed card payment with no matching TIP_ADJUSTED event
        counts as a blocker on the server's cashout."""
        await _open_order(ledger, order_id="ocd",
                          items=[("X", 20.00, 1, "PIZZA")])
        await _pay(ledger, order_id="ocd", amount=20.00, method="card")
        await _close(ledger, "ocd", 20.00)

        res = await checkout_status(server_id="emp_A", ledger=ledger)
        assert res["unadjustedTips"] == 1

    @pytest.mark.asyncio
    async def test_tip_adjusted_to_zero_still_counts_as_adjusted(self, ledger):
        """The 'Zero All' button emits TIP_ADJUSTED with tip=0 — an explicit
        decision. That must clear the unadjusted flag."""
        await _open_order(ledger, order_id="ocz",
                          items=[("X", 20.00, 1, "PIZZA")])
        pid = await _pay(ledger, order_id="ocz", amount=20.00, method="card")
        await ledger.append(tip_adjusted(
            terminal_id=TERMINAL, order_id="ocz",
            payment_id=pid, tip_amount=0.00,
        ))
        await _close(ledger, "ocz", 20.00)

        res = await checkout_status(server_id="emp_A", ledger=ledger)
        assert res["unadjustedTips"] == 0

    @pytest.mark.asyncio
    async def test_other_servers_orders_ignored(self, ledger):
        """An open check on a different server doesn't block this server."""
        await _open_order(ledger, order_id="oB", server_id="emp_B",
                          items=[("X", 5.00, 1, "APPS")])
        # leave emp_B's order open

        res = await checkout_status(server_id="emp_A", ledger=ledger)
        assert res["openChecks"] == 0
        assert res["unadjustedTips"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# PATCH TIPOUT
# ═══════════════════════════════════════════════════════════════════════════

class TestPatchTipout:
    """Stub endpoint — echoes the amount back. Pinned so a future
    real implementation can't silently change the response shape the
    frontend depends on."""

    @pytest.mark.asyncio
    async def test_echo(self, ledger):
        res = await patch_tipout(
            TipOutRequest(amount=12.50),
            server_id="emp_A",
            ledger=ledger,
        )
        assert res["success"] is True
        assert res["server_id"] == "emp_A"
        assert res["tipout"] == pytest.approx(12.50)
