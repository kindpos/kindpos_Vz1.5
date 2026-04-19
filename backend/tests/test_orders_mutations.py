"""
Tests for the customer-facing order mutation endpoints in
`api/routes/orders.py`:

  - POST /{id}/merge           combine orders, void sources
  - POST /{id}/discount        manager discount
  - POST /{id}/split-by-seat   split by seat_number onto child orders
  - POST /{id}/split-evenly    compute per-person amount
  - POST /{id}/void            void an order

orders.py sat at 72% with 200 lines uncovered — the merge/split/
discount/void paths. These flows run hundreds of times a night in
a real restaurant; a silent bug in any of them corrupts the audit
trail the invariant gate depends on.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.routes import orders as orders_mod
from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    item_added,
    modifier_applied,
    order_closed,
    order_created,
    payment_confirmed,
    payment_initiated,
)
from app.core.projections import project_order


TEST_DB = Path("./data/test_orders_mutations.db")
TERMINAL = "terminal_mut"


@pytest.fixture(autouse=True)
def _zero_config(monkeypatch):
    monkeypatch.setattr(settings, "tax_rate", 0.0)
    monkeypatch.setattr(settings, "cash_discount_rate", 0.0)


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


# ── helpers ─────────────────────────────────────────────────────────────────

async def _open_order_with_items(
    ledger, *, order_id: str, items: list,
    server_id: str = "emp_A", seats: list = None,
) -> str:
    """Create an open order with items. `items` = [(name, price, qty[, mods])].

    Optional `seats`: list parallel to items — assigns each item a seat_number.
    """
    await ledger.append(order_created(
        terminal_id=TERMINAL,
        order_id=order_id,
        order_type="dine_in",
        guest_count=len(set(seats)) if seats else 1,
        server_id=server_id,
        server_name=f"S_{server_id}",
        correlation_id=order_id,
    ))
    for idx, item in enumerate(items):
        name, price, qty = item[0], item[1], item[2]
        mods = item[3] if len(item) > 3 else []
        seat = (seats or [None] * len(items))[idx]
        iid = f"{order_id}_i{idx}"
        await ledger.append(item_added(
            terminal_id=TERMINAL, order_id=order_id, item_id=iid,
            menu_item_id=f"m{idx}", name=name, price=price, quantity=qty,
            seat_number=seat,
        ))
        for m_idx, mod in enumerate(mods):
            await ledger.append(modifier_applied(
                terminal_id=TERMINAL, order_id=order_id, item_id=iid,
                modifier_id=f"{iid}_mod{m_idx}",
                modifier_name=mod["name"],
                modifier_price=mod.get("price", 0.0),
            ))
    return order_id


# ═══════════════════════════════════════════════════════════════════════════
# MERGE ORDERS
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeOrders:

    @pytest.mark.asyncio
    async def test_merge_copies_items_and_voids_source(self, ledger):
        """Target gains source's items (with new item_ids); source is voided."""
        await _open_order_with_items(ledger, order_id="oT",
                                      items=[("Pizza", 15.00, 1)])
        await _open_order_with_items(ledger, order_id="oS",
                                      items=[("Salad", 8.00, 1)])

        res = await orders_mod.merge_orders(
            "oT",
            orders_mod.MergeOrderRequest(source_ids=["oS"], approved_by="mgr"),
            ledger=ledger,
        )

        # Target now has both items
        assert res.subtotal == pytest.approx(23.00)
        # Source is voided
        src_events = await ledger.get_events_by_correlation("oS")
        src = project_order(src_events)
        assert src.status == "voided"

    @pytest.mark.asyncio
    async def test_merge_preserves_modifiers(self, ledger):
        """Source items' modifier prices come across. Regression: this was
        buggy on split_by_seat — the merge path did it right, but the test
        pins the behavior either way."""
        await _open_order_with_items(ledger, order_id="oTM",
                                      items=[("Target", 5.00, 1)])
        await _open_order_with_items(ledger, order_id="oSM",
                                      items=[("Pizza", 10.00, 1,
                                              [{"name": "Extra cheese", "price": 3.00}])])

        res = await orders_mod.merge_orders(
            "oTM",
            orders_mod.MergeOrderRequest(source_ids=["oSM"], approved_by="mgr"),
            ledger=ledger,
        )
        # $5 + ($10 + $3 mod) = $18
        assert res.subtotal == pytest.approx(18.00)

    @pytest.mark.asyncio
    async def test_merge_multiple_sources(self, ledger):
        await _open_order_with_items(ledger, order_id="oTa", items=[("T", 1.00, 1)])
        await _open_order_with_items(ledger, order_id="oS1", items=[("S1", 2.00, 1)])
        await _open_order_with_items(ledger, order_id="oS2", items=[("S2", 3.00, 1)])

        res = await orders_mod.merge_orders(
            "oTa",
            orders_mod.MergeOrderRequest(
                source_ids=["oS1", "oS2"], approved_by="mgr",
            ),
            ledger=ledger,
        )
        assert res.subtotal == pytest.approx(6.00)

    @pytest.mark.asyncio
    async def test_merge_rejects_self(self, ledger):
        await _open_order_with_items(ledger, order_id="oSelf", items=[("X", 1.00, 1)])
        with pytest.raises(HTTPException) as exc:
            await orders_mod.merge_orders(
                "oSelf",
                orders_mod.MergeOrderRequest(
                    source_ids=["oSelf"], approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_merge_requires_manager_approval(self, ledger):
        await _open_order_with_items(ledger, order_id="oT1", items=[("T", 1.00, 1)])
        await _open_order_with_items(ledger, order_id="oS1x", items=[("S", 2.00, 1)])
        with pytest.raises(HTTPException) as exc:
            await orders_mod.merge_orders(
                "oT1",
                orders_mod.MergeOrderRequest(source_ids=["oS1x"], approved_by=""),
                ledger=ledger,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_merge_rejects_closed_source(self, ledger):
        """Only open orders may be merged; a paid/closed source is rejected."""
        await _open_order_with_items(ledger, order_id="oT2", items=[("T", 1.00, 1)])
        await _open_order_with_items(ledger, order_id="oSc", items=[("S", 2.00, 1)])
        # Close the source
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oSc", payment_id="pSc",
            amount=2.00, method="cash",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="oSc", payment_id="pSc",
            transaction_id="txnSc", amount=2.00, tax=0.0,
        ))
        await ledger.append(order_closed(
            terminal_id=TERMINAL, order_id="oSc", total=2.00,
        ))

        with pytest.raises(HTTPException) as exc:
            await orders_mod.merge_orders(
                "oT2",
                orders_mod.MergeOrderRequest(source_ids=["oSc"], approved_by="mgr"),
                ledger=ledger,
            )
        assert exc.value.status_code == 400
        assert "only open orders" in exc.value.detail

    @pytest.mark.asyncio
    async def test_merge_rejects_source_with_confirmed_payment(self, ledger):
        """A source with a confirmed-but-not-yet-closed payment is also
        off-limits (otherwise merging would lose the payment)."""
        await _open_order_with_items(ledger, order_id="oT3", items=[("T", 1.00, 1)])
        await _open_order_with_items(ledger, order_id="oSp", items=[("S", 10.00, 1)])
        # Confirmed payment, no close — order is "paid"
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oSp", payment_id="pSp",
            amount=10.00, method="cash",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="oSp", payment_id="pSp",
            transaction_id="txnSp", amount=10.00, tax=0.0,
        ))

        with pytest.raises(HTTPException) as exc:
            await orders_mod.merge_orders(
                "oT3",
                orders_mod.MergeOrderRequest(source_ids=["oSp"], approved_by="mgr"),
                ledger=ledger,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_merge_target_must_be_open(self, ledger):
        """Cannot merge into a closed/voided/paid target."""
        await _open_order_with_items(ledger, order_id="oTc", items=[("T", 5.00, 1)])
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oTc", payment_id="p_close",
            amount=5.00, method="cash",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="oTc", payment_id="p_close",
            transaction_id="txnTc", amount=5.00, tax=0.0,
        ))
        await ledger.append(order_closed(
            terminal_id=TERMINAL, order_id="oTc", total=5.00,
        ))
        await _open_order_with_items(ledger, order_id="oSok", items=[("S", 1.00, 1)])

        with pytest.raises(HTTPException) as exc:
            await orders_mod.merge_orders(
                "oTc",
                orders_mod.MergeOrderRequest(source_ids=["oSok"], approved_by="mgr"),
                ledger=ledger,
            )
        assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# APPLY DISCOUNT
# ═══════════════════════════════════════════════════════════════════════════

class TestApplyDiscount:

    @pytest.mark.asyncio
    async def test_discount_reduces_total(self, ledger):
        await _open_order_with_items(ledger, order_id="oD",
                                      items=[("Item", 30.00, 1)])
        res = await orders_mod.apply_discount(
            "oD",
            orders_mod.ApplyDiscountRequest(
                discount_type="10%", amount=3.00, reason="loyalty",
                approved_by="mgr",
            ),
            ledger=ledger,
        )
        assert res.subtotal == pytest.approx(30.00)
        assert res.discount_total == pytest.approx(3.00)
        assert res.total == pytest.approx(27.00)

    @pytest.mark.asyncio
    async def test_cannot_discount_closed_order(self, ledger):
        """Discount on a non-open order is refused."""
        await _open_order_with_items(ledger, order_id="oDc",
                                      items=[("X", 10.00, 1)])
        # Close it
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oDc", payment_id="p",
            amount=10.00, method="cash",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="oDc", payment_id="p",
            transaction_id="txnDc", amount=10.00, tax=0.0,
        ))
        await ledger.append(order_closed(
            terminal_id=TERMINAL, order_id="oDc", total=10.00,
        ))

        with pytest.raises(HTTPException) as exc:
            await orders_mod.apply_discount(
                "oDc",
                orders_mod.ApplyDiscountRequest(
                    discount_type="5%", amount=1.00, reason="late",
                    approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_discount_blocked_while_payment_pending(self, ledger):
        """A pending (initiated-but-not-confirmed) payment locks the
        order out of discounts — otherwise the card reader and the
        projection would disagree about order.total."""
        await _open_order_with_items(ledger, order_id="oDp",
                                      items=[("X", 20.00, 1)])
        # Pending payment, not confirmed
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oDp", payment_id="pPend",
            amount=20.00, method="card",
        ))

        with pytest.raises(HTTPException) as exc:
            await orders_mod.apply_discount(
                "oDp",
                orders_mod.ApplyDiscountRequest(
                    discount_type="comp", amount=2.00, reason="test",
                    approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 400
        assert "pending" in exc.value.detail.lower()


# ═══════════════════════════════════════════════════════════════════════════
# SPLIT BY SEAT
# ═══════════════════════════════════════════════════════════════════════════

class TestSplitBySeat:

    @pytest.mark.asyncio
    async def test_splits_items_into_per_seat_child_orders(self, ledger):
        """One parent with 2 seats → 2 child orders; items move from parent."""
        await _open_order_with_items(
            ledger, order_id="oParent",
            items=[("A", 10.00, 1), ("B", 20.00, 1)],
            seats=[1, 2],
        )
        res = await orders_mod.split_by_seat(
            "oParent",
            orders_mod.SplitBySeatRequest(seats=None),
            ledger=ledger,
        )
        assert res["success"] is True
        assert len(res["child_orders"]) == 2

        # Each child carries the right item subtotal
        per_seat = {c["seat"]: c for c in res["child_orders"]}
        child1 = project_order(await ledger.get_events_by_correlation(per_seat[1]["order_id"]))
        child2 = project_order(await ledger.get_events_by_correlation(per_seat[2]["order_id"]))
        assert child1.subtotal == pytest.approx(10.00)
        assert child2.subtotal == pytest.approx(20.00)

        # Parent lost those items
        parent = project_order(await ledger.get_events_by_correlation("oParent"))
        assert parent.subtotal == pytest.approx(0.00)

    @pytest.mark.asyncio
    async def test_modifiers_carry_over_to_split_children(self, ledger):
        """Regression for the split-by-seat modifier-drop bug we fixed."""
        await _open_order_with_items(
            ledger, order_id="oPmod",
            items=[("Pizza", 15.00, 1, [{"name": "Extra cheese", "price": 2.50}])],
            seats=[3],
        )
        res = await orders_mod.split_by_seat(
            "oPmod",
            orders_mod.SplitBySeatRequest(seats=None),
            ledger=ledger,
        )
        child_id = res["child_orders"][0]["order_id"]
        child = project_order(await ledger.get_events_by_correlation(child_id))
        assert child.subtotal == pytest.approx(17.50)  # $15 + $2.50 modifier

    @pytest.mark.asyncio
    async def test_split_specific_seats_only(self, ledger):
        """`seats=[1]` splits only seat 1, leaves seat 2's items on parent."""
        await _open_order_with_items(
            ledger, order_id="oPselect",
            items=[("A", 5.00, 1), ("B", 8.00, 1)],
            seats=[1, 2],
        )
        res = await orders_mod.split_by_seat(
            "oPselect",
            orders_mod.SplitBySeatRequest(seats=[1]),
            ledger=ledger,
        )
        assert len(res["child_orders"]) == 1
        assert res["child_orders"][0]["seat"] == 1
        # Parent retains seat-2 item
        parent = project_order(await ledger.get_events_by_correlation("oPselect"))
        assert parent.subtotal == pytest.approx(8.00)

    @pytest.mark.asyncio
    async def test_no_seated_items_400s(self, ledger):
        """Nothing to split → 400, not a silent empty response."""
        await _open_order_with_items(
            ledger, order_id="oPns",
            items=[("A", 5.00, 1)],   # no seats assigned
        )
        with pytest.raises(HTTPException) as exc:
            await orders_mod.split_by_seat(
                "oPns",
                orders_mod.SplitBySeatRequest(seats=None),
                ledger=ledger,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_cannot_split_closed_order(self, ledger):
        """Split is an open-order mutation; closed orders are immutable."""
        await _open_order_with_items(
            ledger, order_id="oPc",
            items=[("A", 10.00, 1)],
            seats=[1],
        )
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oPc", payment_id="p",
            amount=10.00, method="cash",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="oPc", payment_id="p",
            transaction_id="txnPc", amount=10.00, tax=0.0,
        ))
        await ledger.append(order_closed(
            terminal_id=TERMINAL, order_id="oPc", total=10.00,
        ))
        with pytest.raises(HTTPException) as exc:
            await orders_mod.split_by_seat(
                "oPc",
                orders_mod.SplitBySeatRequest(seats=None),
                ledger=ledger,
            )
        assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# SPLIT EVENLY
# ═══════════════════════════════════════════════════════════════════════════

class TestSplitEvenly:

    @pytest.mark.asyncio
    async def test_clean_division_three_ways(self, ledger):
        """A $30 order split 3 ways → $10 per person, $10 for the last."""
        await _open_order_with_items(ledger, order_id="oE30",
                                      items=[("X", 30.00, 1)])
        res = await orders_mod.split_evenly(
            "oE30",
            orders_mod.SplitEvenlyRequest(num_ways=3),
            ledger=ledger,
        )
        assert res["per_person"] == pytest.approx(10.00)
        assert res["last_person"] == pytest.approx(10.00)
        assert res["total"] == pytest.approx(30.00)

    @pytest.mark.asyncio
    async def test_remainder_goes_to_last_person(self, ledger):
        """$10 split 3 ways: $3.33 per person, $3.34 for the last (to keep
        the sum exact)."""
        await _open_order_with_items(ledger, order_id="oE10",
                                      items=[("X", 10.00, 1)])
        res = await orders_mod.split_evenly(
            "oE10",
            orders_mod.SplitEvenlyRequest(num_ways=3),
            ledger=ledger,
        )
        assert res["per_person"] == pytest.approx(3.33)
        assert res["last_person"] == pytest.approx(3.34)
        # Identity: (N-1) × per_person + last_person == total
        computed = 2 * res["per_person"] + res["last_person"]
        assert computed == pytest.approx(res["total"])

    @pytest.mark.asyncio
    async def test_cannot_split_voided_order(self, ledger):
        await _open_order_with_items(ledger, order_id="oEv",
                                      items=[("X", 5.00, 1)])
        from app.core.events import order_voided
        await ledger.append(order_voided(
            terminal_id=TERMINAL, order_id="oEv", reason="test",
        ))
        with pytest.raises(HTTPException) as exc:
            await orders_mod.split_evenly(
                "oEv",
                orders_mod.SplitEvenlyRequest(num_ways=2),
                ledger=ledger,
            )
        assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# VOID ORDER
# ═══════════════════════════════════════════════════════════════════════════

class TestVoidOrder:

    @pytest.mark.asyncio
    async def test_void_sets_status_and_records_reason(self, ledger):
        await _open_order_with_items(ledger, order_id="oV",
                                      items=[("X", 10.00, 1)])
        res = await orders_mod.void_order(
            "oV",
            orders_mod.VoidOrderRequest(
                reason="customer changed mind",
                approved_by="mgr_1",
            ),
            ledger=ledger,
        )
        assert res.status == "voided"
        # void_reason isn't on OrderResponse — verify via the projection instead
        order = project_order(await ledger.get_events_by_correlation("oV"))
        assert order.void_reason == "customer changed mind"

    @pytest.mark.asyncio
    async def test_double_void_rejected(self, ledger):
        """Voiding an already-voided order is a 400, not a silent re-emit."""
        await _open_order_with_items(ledger, order_id="oVV",
                                      items=[("X", 10.00, 1)])
        await orders_mod.void_order(
            "oVV",
            orders_mod.VoidOrderRequest(reason="first", approved_by="mgr"),
            ledger=ledger,
        )
        with pytest.raises(HTTPException) as exc:
            await orders_mod.void_order(
                "oVV",
                orders_mod.VoidOrderRequest(reason="second", approved_by="mgr"),
                ledger=ledger,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_void_requires_approver(self, ledger):
        await _open_order_with_items(ledger, order_id="oVa",
                                      items=[("X", 10.00, 1)])
        with pytest.raises(HTTPException) as exc:
            await orders_mod.void_order(
                "oVa",
                orders_mod.VoidOrderRequest(reason="x", approved_by=""),
                ledger=ledger,
            )
        assert exc.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# 86 GUARD on add_item
# ═══════════════════════════════════════════════════════════════════════════

class TestAdd86Guard:
    """add_item refuses to ring up an item the Overseer has 86'd. The
    guard reads MenuItem.is_86ed from the config projection — a frontend
    with a stale menu cache can't sneak a sold-out item onto a check."""

    async def _seed_menu_item(
        self, ledger, *, item_id: str, name: str, price: str,
        is_86ed: bool = False,
    ):
        """Write CREATED, then optionally an 86D event."""
        from app.core.events import EventType, create_event

        await ledger.append(create_event(
            event_type=EventType.MENU_ITEM_CREATED,
            terminal_id="OVERSEER",
            payload={
                "item_id": item_id,
                "name": name,
                "price": price,
                "category_id": "c_food",
            },
        ))
        if is_86ed:
            await ledger.append(create_event(
                event_type=EventType.MENU_ITEM_86D,
                terminal_id="OVERSEER",
                payload={"item_id": item_id},
            ))

    async def _open_order(self, ledger, order_id: str = "o86"):
        """Create a bare open order so add_item has somewhere to land."""
        from app.core.events import order_created
        await ledger.append(order_created(
            terminal_id=TERMINAL,
            order_id=order_id,
            order_type="dine_in",
            guest_count=1,
            correlation_id=order_id,
        ))

    @pytest.mark.asyncio
    async def test_adding_86d_item_returns_409(self, ledger):
        await self._seed_menu_item(ledger, item_id="m86",
                                    name="Burger", price="12.00",
                                    is_86ed=True)
        await self._open_order(ledger)

        with pytest.raises(HTTPException) as exc:
            await orders_mod.add_item(
                "o86",
                orders_mod.AddItemRequest(
                    menu_item_id="m86",
                    name="Burger",
                    price=12.00,
                    quantity=1,
                ),
                http_request=None,
                ledger=ledger,
            )
        assert exc.value.status_code == 409
        assert "86" in exc.value.detail
        # Nothing ended up on the order
        from app.core.projections import project_order
        events = await ledger.get_events_by_correlation("o86")
        order = project_order(events)
        assert order.items == []

    @pytest.mark.asyncio
    async def test_adding_restored_item_succeeds(self, ledger):
        """86 → RESTORE flips is_86ed back off; add_item works again."""
        from app.core.events import EventType, create_event
        await self._seed_menu_item(ledger, item_id="mR",
                                    name="Fries", price="4.00",
                                    is_86ed=True)
        await ledger.append(create_event(
            event_type=EventType.MENU_ITEM_RESTORED,
            terminal_id="OVERSEER",
            payload={"item_id": "mR"},
        ))
        await self._open_order(ledger, order_id="oR")

        res = await orders_mod.add_item(
            "oR",
            orders_mod.AddItemRequest(
                menu_item_id="mR",
                name="Fries",
                price=4.00,
                quantity=1,
            ),
            http_request=None,
            ledger=ledger,
        )
        assert res.subtotal == pytest.approx(4.00)

    @pytest.mark.asyncio
    async def test_ad_hoc_item_not_in_menu_still_added(self, ledger):
        """An item whose menu_item_id isn't in the config projection
        (e.g. a manual `$0.50` correction line) sails through — the
        guard only blocks items the Overseer explicitly marked 86'd."""
        await self._open_order(ledger, order_id="oAdHoc")
        res = await orders_mod.add_item(
            "oAdHoc",
            orders_mod.AddItemRequest(
                menu_item_id="m_not_in_config",
                name="Manual line",
                price=0.50,
                quantity=1,
            ),
            http_request=None,
            ledger=ledger,
        )
        assert res.subtotal == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_available_item_still_added_normally(self, ledger):
        """Control: an item that exists in config but isn't 86'd adds as
        before. Pinning so the guard doesn't become an over-aggressive
        roadblock if the menu projection wobbles."""
        await self._seed_menu_item(ledger, item_id="mOK",
                                    name="Pizza", price="15.00",
                                    is_86ed=False)
        await self._open_order(ledger, order_id="oOK")
        res = await orders_mod.add_item(
            "oOK",
            orders_mod.AddItemRequest(
                menu_item_id="mOK",
                name="Pizza",
                price=15.00,
                quantity=1,
            ),
            http_request=None,
            ledger=ledger,
        )
        assert res.subtotal == pytest.approx(15.00)
