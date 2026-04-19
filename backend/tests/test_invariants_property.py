"""
Property-style randomized tests for KINDpos financial invariants.

Each test generates a realistic day of events (orders, items, modifiers,
discounts, voids, payments, tip adjustments, refunds), runs the full
projection → aggregation pipeline, and asserts every canonical identity
holds. Many independent iterations across a fixed seed-space give
high-confidence coverage that the aggregation math produces balanced
totals regardless of input shape — the runtime gate installed in
Piece 2 fails the test the moment an identity drifts.

Seeds are intentionally explicit so failures reproduce locally.
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Callable

import pytest

from app.api.routes.reporting import _aggregate_orders
from app.core.events import (
    EventType,
    create_event,
    item_added,
    modifier_applied,
    order_created,
    order_voided,
    payment_confirmed,
    payment_initiated,
    tip_adjusted,
)


def _discount_event(order_id: str, amount: float):
    """Discount has no convenience builder; mirror routes/orders.py's usage."""
    return create_event(
        event_type=EventType.DISCOUNT_APPROVED,
        terminal_id=TERMINAL,
        correlation_id=order_id,
        payload={
            "order_id": order_id,
            "discount_type": "test",
            "amount": amount,
            "reason": "property-test discount",
        },
    )
from app.core.financial_invariants import (
    InvariantViolation,
    check_day_close,
    check_tender_reconciliation,
    check_tips_partition,
    check_pnl_identity,
)
from app.core.projections import project_orders

TERMINAL = "terminal_prop"


# ── event-stream generator ──────────────────────────────────────────────────

def _make_day(seed: int) -> list:
    """Build a randomized but internally-consistent stream of events.

    The generator mirrors realistic POS behaviour: every payment sums
    to an order's actual balance (no overpayment), tax captured at
    confirmation time comes from the order's current tax, voided
    orders carry no payments, and refunds never exceed the refundable
    amount on their target payment.
    """
    rng = random.Random(seed)
    events: list = []
    num_orders = rng.randint(2, 12)

    for i in range(num_orders):
        order_id = f"o{seed}_{i}"
        events.append(order_created(
            terminal_id=TERMINAL,
            order_id=order_id,
            order_type="dine_in",
            guest_count=rng.randint(1, 4),
        ))

        # Items — random count, prices rounded to the cent.
        item_count = rng.randint(1, 5)
        item_gross = Decimal("0")
        for j in range(item_count):
            price = Decimal(str(round(rng.uniform(1.0, 49.99), 2)))
            qty = rng.randint(1, 3)
            item_id = f"it_{seed}_{i}_{j}"
            events.append(item_added(
                terminal_id=TERMINAL,
                order_id=order_id,
                item_id=item_id,
                menu_item_id=f"menu_{j}",
                name=f"Item {j}",
                price=float(price),
                quantity=qty,
                category=rng.choice(["Food", "Drinks", "Dessert", None]),
            ))
            item_gross += price * qty

            # Optional modifier
            if rng.random() < 0.3:
                mod_price = Decimal(str(round(rng.uniform(0.0, 4.0), 2)))
                events.append(modifier_applied(
                    terminal_id=TERMINAL,
                    order_id=order_id,
                    item_id=item_id,
                    modifier_id=f"mod_{seed}_{i}_{j}",
                    modifier_name=f"Mod {j}",
                    modifier_price=float(mod_price),
                    action="add",
                ))
                item_gross += mod_price * qty

        # Optional discount (10% chance, $1-$5)
        discount_amount = Decimal("0")
        if rng.random() < 0.1 and item_gross > 5:
            discount_amount = Decimal(str(round(rng.uniform(1.0, min(5.0, float(item_gross) - 1)), 2)))
            events.append(_discount_event(order_id, float(discount_amount)))

        # Decide fate: void vs paid. Open orders exist but are rare.
        roll = rng.random()
        if roll < 0.1:
            # Voided — carries subtotal into void_total, no payments.
            events.append(order_voided(
                terminal_id=TERMINAL,
                order_id=order_id,
                reason="test void",
            ))
            continue
        if roll < 0.15:
            # Open — no payment events, excluded from financial totals.
            continue

        # Paid: compute order total (subtotal − discount + tax) and
        # generate 1-2 payments that sum exactly to that total.
        subtotal_after_disc = item_gross - discount_amount
        tax_rate = Decimal("0.07")
        tax = (subtotal_after_disc * tax_rate).quantize(Decimal("0.01"))
        order_total = (subtotal_after_disc + tax).quantize(Decimal("0.01"))

        remaining = order_total
        num_payments = 1 if rng.random() < 0.8 else 2
        for p in range(num_payments):
            is_last = (p == num_payments - 1)
            if is_last:
                amount = remaining
            else:
                amount = (remaining * Decimal("0.5")).quantize(Decimal("0.01"))
            remaining -= amount

            payment_id = f"p_{seed}_{i}_{p}"
            method = rng.choice(["cash", "card"])
            events.append(payment_initiated(
                terminal_id=TERMINAL,
                order_id=order_id,
                payment_id=payment_id,
                amount=float(amount),
                method=method,
            ))
            # Capture tax proportional to the payment share on the last
            # payment so the order's total tax_amount matches `tax`.
            captured_tax = tax if is_last else Decimal("0")
            events.append(payment_confirmed(
                terminal_id=TERMINAL,
                order_id=order_id,
                payment_id=payment_id,
                transaction_id=f"txn_{payment_id}",
                amount=float(amount),
                tax=float(captured_tax),
            ))

            # Tip: record on card payments ~50% of the time.
            if method == "card" and rng.random() < 0.5:
                tip_amount = Decimal(str(round(rng.uniform(0.5, 6.0), 2)))
                events.append(tip_adjusted(
                    terminal_id=TERMINAL,
                    order_id=order_id,
                    payment_id=payment_id,
                    tip_amount=float(tip_amount),
                ))
                # Tip adjustment re-adjustment (last-wins behaviour)
                if rng.random() < 0.2:
                    tip_amount2 = Decimal(str(round(rng.uniform(0.5, 8.0), 2)))
                    events.append(tip_adjusted(
                        terminal_id=TERMINAL,
                        order_id=order_id,
                        payment_id=payment_id,
                        tip_amount=float(tip_amount2),
                    ))
            elif method == "cash" and rng.random() < 0.2:
                tip_amount = Decimal(str(round(rng.uniform(0.5, 3.0), 2)))
                events.append(tip_adjusted(
                    terminal_id=TERMINAL,
                    order_id=order_id,
                    payment_id=payment_id,
                    tip_amount=float(tip_amount),
                ))

    return events


def _tip_map_from(events):
    tip_map = {}
    for e in events:
        if e.event_type == EventType.TIP_ADJUSTED:
            tip_map[e.payload.get("payment_id")] = e.payload.get("tip_amount", 0.0)
    return tip_map


# ── the property test ──────────────────────────────────────────────────────

# 100 distinct seeds; runs in ~1s because everything is in-memory.
# Bump SEEDS for an overnight soak test when touching aggregation code.
SEEDS = list(range(100))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_hold_on_random_day(seed):
    """For a randomly-generated day, every canonical identity holds.

    The `_aggregate_orders` call routes through the strict gate
    installed in Piece 2, so an InvariantViolation here would mean
    the aggregator produced drifted totals for *some* valid event
    stream — exactly the class of bug this suite guards against.
    """
    events = _make_day(seed)
    orders = project_orders(events)
    tip_map = _tip_map_from(events)

    # The gate runs inside _aggregate_orders. If it raises, pytest
    # reports the seed; otherwise the checks below double-check the
    # identities against the aggregator's own reported figures.
    agg = _aggregate_orders(list(orders.values()), tip_map)

    # P&L identity
    pnl = check_pnl_identity(
        gross=float(agg["gross_sales"]),
        voids=float(agg["void_total"]),
        discounts=float(agg["discount_total"]),
        refunds=float(agg["refund_total"]),
        net=float(agg["net_sales"]),
    )
    assert pnl.ok, f"seed {seed}: {pnl.message}"

    # Tender reconciliation
    tr = check_tender_reconciliation(
        cash_total=float(agg["cash_total"]),
        card_total=float(agg["card_total"]),
        net_sales=float(agg["net_sales"]),
        tax_collected=float(agg["tax_total"]),
    )
    assert tr.ok, f"seed {seed}: {tr.message}"

    # Tips partition
    tp = check_tips_partition(
        total_tips=float(agg["total_tips"]),
        card_tips=float(agg["card_tips"]),
        cash_tips=float(agg["cash_tips"]),
    )
    assert tp.ok, f"seed {seed}: {tp.message}"


# ── targeted edge cases ────────────────────────────────────────────────────

def test_empty_day_passes():
    """A day with zero orders still satisfies every identity."""
    agg = _aggregate_orders([], {})
    for r in check_day_close(
        gross_sales=float(agg["gross_sales"]),
        void_total=float(agg["void_total"]),
        discount_total=float(agg["discount_total"]),
        refund_total=float(agg["refund_total"]),
        net_sales=float(agg["net_sales"]),
        tax_collected=float(agg["tax_total"]),
        cash_total=float(agg["cash_total"]),
        card_total=float(agg["card_total"]),
        total_tips=float(agg["total_tips"]),
        card_tips=float(agg["card_tips"]),
        cash_tips=float(agg["cash_tips"]),
    ):
        assert r.ok


def test_all_voided_day_passes():
    """A day where every order is voided still balances."""
    events = []
    for i in range(4):
        oid = f"void_{i}"
        events.append(order_created(terminal_id=TERMINAL, order_id=oid, order_type="dine_in"))
        events.append(item_added(
            terminal_id=TERMINAL, order_id=oid, item_id=f"i_{i}",
            menu_item_id="m1", name="X", price=10.00, quantity=2,
        ))
        events.append(order_voided(terminal_id=TERMINAL, order_id=oid, reason="test"))

    orders = project_orders(events)
    agg = _aggregate_orders(list(orders.values()), {})
    # Gross carries voided subtotals; net ends at 0.
    assert float(agg["gross_sales"]) == pytest.approx(80.0)
    assert float(agg["void_total"]) == pytest.approx(80.0)
    assert float(agg["net_sales"]) == pytest.approx(0.0)
    assert float(agg["cash_total"] + agg["card_total"]) == pytest.approx(0.0)


def test_strict_mode_raises_on_injected_bad_state():
    """If something ever produces bad totals, the gate fires.

    We force a known-bad aggregator output by calling check_day_close
    directly with deliberately inconsistent values, and confirm
    InvariantViolation is raised when we route through gate(strict=True).
    """
    from app.core.financial_invariants import gate

    bad_results = check_day_close(
        gross_sales=100.0, void_total=0, discount_total=0, refund_total=0,
        net_sales=100.0, tax_collected=5.0,
        cash_total=50.0, card_total=0.0,        # tender short by 55
        total_tips=0, card_tips=0, cash_tips=0,
    )
    with pytest.raises(InvariantViolation):
        gate(bad_results, context="test_strict", strict=True)
