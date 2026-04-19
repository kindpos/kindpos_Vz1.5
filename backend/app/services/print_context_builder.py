import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from ..core.event_ledger import EventLedger
from ..core.projections import project_order, project_orders
from ..core.events import EventType
from decimal import Decimal
from ..core.money import money_round

_ZERO = Decimal('0')
from ..config import settings

logger = logging.getLogger("kindpos.printing.context_builder")


# ── Ticket number helper ───────────────────────────────────────────────────────
async def _get_ticket_number(ledger: EventLedger, order_id: str) -> str:
    try:
        boundary    = await ledger.get_last_day_close_sequence()
        events      = await ledger.get_events_since(boundary, limit=50000)
        created_ids = [
            e.correlation_id for e in events
            if e.event_type == EventType.ORDER_CREATED
        ]
        try:
            position = created_ids.index(order_id) + 1
        except ValueError:
            position = len(created_ids) + 1
        return f"C-{position:03d}"
    except Exception as e:
        logger.warning(f"Could not derive ticket number for {order_id}: {e}")
        return "C-???"


ORDER_TYPE_LABELS = {
    "dine_in":       "DINE IN",
    "to_go":         "TO GO",
    "bar_tab":       "BAR TAB",
    "delivery":      "DELIVERY",
    "staff":         "STAFF MEAL",
    "quick_service": "QUICK SERVICE",
}


class PrintContextBuilder:
    def __init__(self, ledger: EventLedger):
        self.ledger = ledger

    # ─────────────────────────────────────────────────────────────────────────
    #  GUEST RECEIPT
    # ─────────────────────────────────────────────────────────────────────────

    async def build_receipt_context(
        self,
        order_id: str,
        copy_type: str = "customer",
        is_reprint: bool = False,
    ) -> Dict[str, Any]:

        events = await self.ledger.get_events_by_correlation(order_id)
        if not events:
            raise ValueError(f"Order {order_id} not found in ledger")

        order         = project_order(events)
        ticket_number = await _get_ticket_number(self.ledger, order_id)
        order_type    = getattr(order, "order_type", "quick_service")

        # ── Timestamps ────────────────────────────────────────────────────────
        created_at = getattr(order, "created_at", None)
        opened_at  = created_at.isoformat() if created_at else None
        closed_at  = None
        for e in reversed(events):
            if e.event_type == EventType.ORDER_CLOSED:
                closed_at = e.timestamp.isoformat()
                break

        # ── Payment info ──────────────────────────────────────────────────────
        payment_method = "cash"
        card_last_four = None
        tip_amount     = 0.0

        for p in (order.payments or []):
            if p.status == "confirmed":
                payment_method = p.method
                tip_amount    += getattr(p, "tip_amount", 0.0)
                if p.method == "card" and p.transaction_id:
                    card_last_four = p.transaction_id[-4:]

        # ── Items ─────────────────────────────────────────────────────────────
        items = []
        for item in (order.items or []):
            mods = []
            for m in (item.modifiers or []):
                mods.append(m.get("name", str(m)) if isinstance(m, dict) else str(m))
            items.append({
                "qty":       item.quantity,
                "name":      item.name,
                "price":     money_round(item.price),
                "subtotal":  money_round(item.subtotal),
                "modifiers": mods,
                "notes":     getattr(item, "notes", None),
            })

        # ── Tax lines — template iterates a list ──────────────────────────────
        tax_lines = [{"label": "Tax", "amount": money_round(order.tax or 0)}]

        return {
            "order_id":                   order_id,
            "ticket_number":              ticket_number,
            "copy_type":                  copy_type,
            "is_reprint":                 is_reprint,
            "order_type":                 order_type,
            "opened_at":                  opened_at,
            "closed_at":                  closed_at,
            "table":                      getattr(order, "table", None),
            "server_name":                getattr(order, "server_name", None),
            "customer_name":              getattr(order, "customer_name", None),
            "items":                      items,
            "subtotal":                   money_round(order.subtotal or 0),
            "discount_total":             money_round(order.discount_total or 0),
            "tax_lines":                  tax_lines,
            "total":                      money_round(order.total or 0),
            "tip_amount":                 tip_amount,
            "payment_method":             payment_method,
            "card_last_four":             card_last_four,
            "tip_suggestion_percentages": [15, 18, 20],
            "tip_calculation_base":       "pretax",
            # Restaurant — from config eventually
            "restaurant_name":  "KINDpos Demo",
            "address":          "",
            "phone":            "",
            "footer_message":   "Thank you!",
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  KITCHEN TICKET
    # ─────────────────────────────────────────────────────────────────────────

    async def build_kitchen_context(
        self,
        order_id: str,
        station_name: str = "General",
        is_reprint: bool = False,
        original_fired_at: Optional[str] = None,
        station_categories: Optional[list[str]] = None,
    ) -> Dict[str, Any]:

        events = await self.ledger.get_events_by_correlation(order_id)
        if not events:
            raise ValueError(f"Order {order_id} not found in ledger")

        order         = project_order(events)
        ticket_number = await _get_ticket_number(self.ledger, order_id)
        order_type    = getattr(order, "order_type", "quick_service")
        fired_at      = datetime.now(timezone.utc).strftime("%I:%M %p")

        # ── Items ─────────────────────────────────────────────────────────────
        all_items = []
        seats = set()
        for item in (order.items or []):
            seat = getattr(item, "seat_number", None)
            if seat:
                seats.add(seat)
            mods = []
            for m in (item.modifiers or []):
                mods.append(m if isinstance(m, dict) else str(m))
            notes = getattr(item, "notes", None)
            all_items.append({
                "qty":                  item.quantity,
                "name":                 item.name,
                "kitchen_text":         item.name,
                "modifiers":            mods,
                "special_instructions": notes or "",
                "allergy":              "",
                "category":             getattr(item, "category", None),
                "seat_number":          seat,
            })

        # ── Station filtering ─────────────────────────────────────────────────
        # When station_categories is provided, split items into this station's
        # items vs companion items (going to other stations).
        if station_categories is not None:
            cat_set = set(station_categories)
            items = [it for it in all_items if it.get("category") in cat_set]
            companion_items = [it for it in all_items if it.get("category") not in cat_set]
        else:
            items = all_items
            companion_items = []

        return {
            "order_id":           order_id,
            "ticket_number":      ticket_number,
            "check_number":       ticket_number,
            "ticket_type":        "REPRINT" if is_reprint else "ORIGINAL",
            "ticket_index":       1,
            "ticket_total":       1,
            "order_type":         order_type,
            "order_type_display": ORDER_TYPE_LABELS.get(order_type, order_type.upper()),
            "table":              getattr(order, "table", None),
            "customer_name":      getattr(order, "customer_name", None),
            "server":             getattr(order, "server_name", None),
            "server_name":        getattr(order, "server_name", None),
            "seats":              sorted(seats) if seats else None,
            "fired_at":           fired_at,
            "original_fired_at":  original_fired_at,
            "items":              items,
            "companion_items":    companion_items,
            "station_name":       station_name,
            "terminal_id":        settings.terminal_id,
            "supports_red":       False,
            "rush":               False,
            "vip":                False,
            "warnings_86":        [],
        }

    async def build_server_checkout_context(
            self,
            server_id: str,
            server_name: str,
            *,
            declared_cash_tips: float = None,
            tip_out_overrides: dict = None,
            is_reprint: bool = False,
    ) -> Dict[str, Any]:
        """
        Build context for ServerCheckoutTemplate.

        Aggregates all orders closed by this server since the last DAY_CLOSED
        boundary event. Designed to be called at end-of-shift cashout.

        Args:
            server_id:          Employee ID of the server being checked out.
            server_name:        Display name for the receipt header.
            declared_cash_tips: Cash tips declared by the server (None = not yet declared).
            tip_out_overrides:  Dict of {role: override_amount} if manager adjusted.
            is_reprint:         Whether this is a reprint of a previous checkout.
        """
        boundary = await self.ledger.get_last_day_close_sequence()
        all_events = await self.ledger.get_events_since(boundary, limit=50000)

        # ── Filter to this server's orders ────────────────────────────────────
        # Use projections (current state after transfers) to find this server's orders
        all_orders = project_orders(all_events)
        server_orders = [
            o for o in all_orders.values()
            if o.server_id == server_id and o.status == "closed"
        ]

        # ── Aggregate across closed orders ────────────────────────────────────
        checks_closed = 0
        gross_sales = _ZERO
        voids_total = _ZERO
        comps_total = _ZERO
        discounts_total = _ZERO
        refunds_total = _ZERO
        tax_collected = _ZERO
        cash_sales = _ZERO
        card_sales = _ZERO
        cc_transactions = []
        open_tip_count = 0

        # Voided orders belonging to this server also flow into the
        # receipt so the Voids line reflects reality rather than $0.
        voided_orders = [
            o for o in all_orders.values()
            if o.server_id == server_id and o.status == "voided"
        ]
        for vo in voided_orders:
            voids_total += Decimal(str(vo.subtotal or 0))

        for order in server_orders:

            checks_closed += 1

            order_subtotal = Decimal(str(order.subtotal or 0))
            order_tax = Decimal(str(order.tax or 0))
            gross_sales += order_subtotal
            tax_collected += order_tax

            # Use projection totals for consistent deduction model.
            # Refunds on closed orders belong in refunds_total, not voids —
            # previously this line mis-routed refunds into voids_total,
            # inflating the Voids line on the receipt while the Voids
            # count stayed at zero and actual refunds were invisible.
            discounts_total += Decimal(str(order.discount_total or 0))
            refunds_total += Decimal(str(order.refund_total or 0))

            # ── Payment details ───────────────────────────────────────────────
            for p in (order.payments or []):
                if p.status != "confirmed":
                    continue
                amount = Decimal(str(getattr(p, "amount", 0) or 0))
                tip = money_round(getattr(p, "tip_amount", 0) or 0)

                if p.method == "cash":
                    cash_sales += amount
                elif p.method == "card":
                    card_sales += amount
                    last4 = None
                    if p.transaction_id:
                        last4 = p.transaction_id[-4:]

                    # Determine ticket number for CC detail line
                    ticket_num = await _get_ticket_number(self.ledger, order.order_id)

                    tip_open = getattr(p, "tip_open", False) or (tip == 0.0)
                    if tip_open:
                        open_tip_count += 1

                    cc_transactions.append({
                        "check_number": ticket_num,
                        "card_last_four": last4 or "****",
                        "total": money_round(amount),
                        "tip": tip,
                        "tip_open": tip_open,
                    })

        # Include refunds in the deduction chain so Net matches the
        # canonical identity. Gross already includes voided subtotals
        # above; subtract them once here.
        gross_sales += voids_total
        net_sales = money_round(gross_sales - voids_total - comps_total - discounts_total - refunds_total)
        cc_tips_total = sum(t["tip"] for t in cc_transactions)
        gross_tips = cc_tips_total + (declared_cash_tips or 0.0)

        # ── Clock in/out (from CLOCK_IN / CLOCK_OUT events) ───────────────────
        clock_in = None
        clock_out = None
        for e in all_events:
            payload = e.payload or {}
            eid = payload.get("employee_id") or payload.get("server_id")
            if eid != server_id:
                continue
            if e.event_type == EventType.USER_LOGGED_IN:
                clock_in = e.timestamp.isoformat() if e.timestamp else None
            elif e.event_type == EventType.USER_LOGGED_OUT:
                clock_out = e.timestamp.isoformat() if e.timestamp else None

        # Shift duration
        shift_duration = ""
        if clock_in and clock_out:
            try:
                dt_in = datetime.fromisoformat(clock_in.replace("Z", "+00:00"))
                dt_out = datetime.fromisoformat(clock_out.replace("Z", "+00:00"))
                delta = dt_out - dt_in
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes = remainder // 60
                shift_duration = f"{hours}h {minutes}m"
            except Exception:
                shift_duration = ""

        # ── Tip-out calculation ───────────────────────────────────────────────
        # Tip-out presets come from config; overrides from manager at cashout
        tip_out_presets = getattr(settings, "tip_out_presets", [])
        tip_outs = []
        total_tip_out = 0.0

        for preset in tip_out_presets:
            role = preset.get("role", "")
            pct = preset.get("percentage", 0.0)
            basis = preset.get("basis", "net_sales")

            # Determine the base amount for this tip-out
            if basis == "net_sales":
                base_amount = net_sales
            elif basis == "alcohol" or basis == "alcohol_sales":
                base_amount = money_round(preset.get("base_override", 0))
                # Deferred: derive alcohol sales from category data when available
            elif basis == "food" or basis == "food_sales":
                base_amount = money_round(preset.get("base_override", 0))
                # Deferred: derive food sales from category data when available
            else:
                base_amount = net_sales

            calculated = money_round(base_amount * (pct / 100))

            # Apply manager override if present
            adjusted = False
            not_staffed = preset.get("not_staffed", False)
            if tip_out_overrides and role in tip_out_overrides:
                override_val = tip_out_overrides[role]
                if override_val is None:
                    not_staffed = True
                    calculated = 0.0
                else:
                    adjusted = (override_val != calculated)
                    calculated = money_round(override_val)

            tip_outs.append({
                "role": role,
                "basis_description": f"{pct}% {basis.replace('_', ' ')}",
                "amount": calculated,
                "adjusted": adjusted,
                "not_staffed": not_staffed,
            })
            total_tip_out += calculated

        net_tips = gross_tips - total_tip_out

        # ── Tip pool (if server is in one) ────────────────────────────────────
        tip_pool = None
        # Deferred: check staff config for pool membership
        # If server is in a pool, set:
        # tip_pool = {
        #     "name": "BAR POOL",
        #     "tips_collected": <sum of tips this server collected>,
        # }

        # ── Cash collected = cash sales total (cash tendered) ─────────────────
        cash_collected = cash_sales

        today = datetime.now(timezone.utc).strftime("%m/%d/%Y")

        return {
            "is_reprint": is_reprint,
            "restaurant_name": getattr(settings, "restaurant_name", "KINDpos"),
            "server_name": server_name,
            "date": today,
            "clock_in": clock_in,
            "clock_out": clock_out,
            "shift_duration": shift_duration,
            "checks_closed": checks_closed,
            "gross_sales": money_round(gross_sales),
            "voids_total": money_round(voids_total),
            "comps_total": money_round(comps_total),
            "discounts_total": money_round(discounts_total),
            "refunds_total": money_round(refunds_total),
            "net_sales": money_round(net_sales),
            "tax_collected": money_round(tax_collected),
            "cash_sales": money_round(cash_sales),
            "card_sales": money_round(card_sales),
            "show_cc_detail": getattr(settings, "show_cc_detail", True),
            "cc_transactions": cc_transactions,
            "cc_tips_total": money_round(cc_tips_total),
            "declared_cash_tips": declared_cash_tips,
            "gross_tips": money_round(gross_tips),
            "tip_pool": tip_pool,
            "tip_outs": tip_outs,
            "total_tip_out": money_round(total_tip_out),
            "net_tips": money_round(net_tips),
            "cash_collected": money_round(cash_sales),
            "cc_tips_payout": getattr(settings, "cc_tips_payout", "cash"),
            "open_tip_count": open_tip_count,
            "require_manager_sign": getattr(settings, "require_manager_sign", True),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  SALES RECAP CONTEXT
    # ─────────────────────────────────────────────────────────────────────────

    async def build_sales_recap_context(
            self,
            *,
            printed_by: str = "",
            is_reprint: bool = False,
    ) -> Dict[str, Any]:
        """
        Build context for SalesRecapTemplate.

        Aggregates ALL orders since the last DAY_CLOSED boundary.
        This is a manager-only report showing the full day's performance.

        Args:
            printed_by: Name of the manager printing the report.
            is_reprint: Whether this is a reprint.
        """
        boundary = await self.ledger.get_last_day_close_sequence()
        all_events = await self.ledger.get_events_since(boundary, limit=50000)

        # ── Collect all order IDs created today ────────────────────────────────
        order_ids = []
        for e in all_events:
            if e.event_type == EventType.ORDER_CREATED:
                order_ids.append(e.correlation_id)

        # ── Aggregate across all orders ───────────────────────────────────────
        total_checks = 0
        gross_sales = _ZERO
        voids_total = _ZERO
        voids_count = 0
        comps_total = _ZERO
        comps_count = 0
        discounts_total = _ZERO
        discounts_count = 0
        refunds_total = _ZERO
        tax_collected = _ZERO
        cash_sales = _ZERO
        cash_count = 0
        card_sales = _ZERO
        card_count = 0
        total_tips = _ZERO
        cash_tips = _ZERO
        card_tips = _ZERO
        covers = 0
        category_totals = {}  # {category_name: {"total": float, "count": int}}

        for order_id in order_ids:
            order_events = await self.ledger.get_events_by_correlation(order_id)
            if not order_events:
                continue

            order = project_order(order_events)

            # Voided orders roll into the voids total so the printed
            # Sales Recap shows the day's actual void count and amount.
            # Previously voids_total stayed at 0 and the receipt under-
            # reported activity. Voided subtotals also roll into gross
            # so Gross − Voids − Discounts − Refunds = Net matches the
            # API's aggregation.
            if order.status == "voided":
                void_sub = Decimal(str(order.subtotal or 0))
                voids_total += void_sub
                voids_count += 1
                gross_sales += void_sub
                continue

            # Only count closed orders for the rest of the aggregation
            is_closed = any(
                e.event_type == EventType.ORDER_CLOSED for e in order_events
            )
            if not is_closed:
                continue

            total_checks += 1
            order_subtotal = Decimal(str(order.subtotal or 0))
            order_tax = Decimal(str(order.tax or 0))
            gross_sales += order_subtotal
            tax_collected += order_tax

            # Covers (seats/guests)
            seats = set()
            for item in (order.items or []):
                seat = getattr(item, "seat_number", None)
                if seat:
                    seats.add(seat)
                # Category aggregation
                cat = getattr(item, "category", None) or "Uncategorized"
                item_total = Decimal(str(item.quantity * item.price))
                if cat not in category_totals:
                    category_totals[cat] = {"total": _ZERO, "count": 0}
                category_totals[cat]["total"] += item_total
                category_totals[cat]["count"] += item.quantity

            covers += max(len(seats), 1)  # At least 1 guest per check

            # Use projection totals for consistent deduction model
            order_disc = Decimal(str(order.discount_total or 0))
            discounts_total += order_disc
            if order_disc > 0:
                discounts_count += 1
            refunds_total += Decimal(str(order.refund_total or 0))

            # Payments
            for p in (order.payments or []):
                if p.status != "confirmed":
                    continue
                amount = Decimal(str(getattr(p, "amount", 0) or 0))
                tip = Decimal(str(getattr(p, "tip_amount", 0) or 0))
                total_tips += tip

                if p.method == "cash":
                    cash_sales += amount
                    cash_count += 1
                    cash_tips += tip
                elif p.method == "card":
                    card_sales += amount
                    card_count += 1
                    card_tips += tip

        net_sales = money_round(gross_sales - voids_total - discounts_total - refunds_total)
        total_payments = money_round(cash_sales + card_sales)
        avg_check = money_round(net_sales / total_checks) if total_checks > 0 else 0.0
        per_person_avg = money_round(net_sales / covers) if covers > 0 else 0.0

        # ── Category sales (sorted by total descending) ───────────────────────
        category_sales = sorted(
            [
                {"name": name, "total": money_round(data["total"]), "count": data["count"]}
                for name, data in category_totals.items()
            ],
            key=lambda c: c["total"],
            reverse=True,
        )

        # ── Tax lines ─────────────────────────────────────────────────────────
        tax_lines = [{"label": "Tax", "amount": money_round(tax_collected)}]

        # ── Daypart breakdown ─────────────────────────────────────────────────
        # Deferred: daypart bucketing once order timestamps are available
        # dayparts = [
        #     {"name": "Breakfast (6a-11a)", "sales": 0.0, "checks": 0},
        #     {"name": "Lunch (11a-3p)",     "sales": 0.0, "checks": 0},
        #     {"name": "Dinner (3p-10p)",    "sales": 0.0, "checks": 0},
        #     {"name": "Late Night (10p+)",  "sales": 0.0, "checks": 0},
        # ]
        dayparts = []

        today = datetime.now(timezone.utc).strftime("%m/%d/%Y")

        return {
            "is_reprint": is_reprint,
            "restaurant_name": getattr(settings, "restaurant_name", "KINDpos"),
            "date": today,
            "date_from": today,
            "date_to": "",
            "printed_by": printed_by,
            "printed_at": datetime.now(timezone.utc).isoformat(),
            "gross_sales": money_round(gross_sales),
            "voids_total": money_round(voids_total),
            "voids_count": voids_count,
            "comps_total": money_round(comps_total),
            "comps_count": comps_count,
            "discounts_total": money_round(discounts_total),
            "discounts_count": discounts_count,
            "refunds_total": money_round(refunds_total),
            "net_sales": money_round(net_sales),
            "tax_collected": money_round(tax_collected),
            "tax_lines": tax_lines,
            "cash_sales": money_round(cash_sales),
            "cash_count": cash_count,
            "card_sales": money_round(card_sales),
            "card_count": card_count,
            "other_payments": [],
            "total_payments": money_round(total_payments),
            "total_tips": money_round(total_tips),
            "cash_tips": money_round(cash_tips),
            "card_tips": money_round(card_tips),
            "cash_expected": money_round(cash_sales - card_tips),
            "category_sales": category_sales,
            "total_checks": total_checks,
            "avg_check": avg_check,
            "covers": covers,
            "per_person_avg": per_person_avg,
            "dayparts": dayparts,
            "terminal_id": settings.terminal_id,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  CLOCK HOURS SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    async def build_clock_hours_context(
            self,
            employee_id: str,
            employee_name: str,
            role_name: str = "",
            action: str = "CLOCK IN",
    ) -> Dict[str, Any]:
        """
        Build context for ClockHoursTemplate.

        Calculates this-shift duration and weekly pay-period hours
        from USER_LOGGED_IN / USER_LOGGED_OUT events.
        """
        now = datetime.now(timezone.utc)

        # ── Determine pay-period window (Mon 00:00 → now) ────────────────────
        days_since_monday = now.weekday()  # 0=Mon
        period_start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Fetch all clock events within the pay period
        login_events = await self.ledger.get_events_by_type(
            EventType.USER_LOGGED_IN, since=period_start, limit=5000
        )
        logout_events = await self.ledger.get_events_by_type(
            EventType.USER_LOGGED_OUT, since=period_start, limit=5000
        )

        # Filter to this employee
        logins = sorted(
            [e for e in login_events if (e.payload or {}).get("employee_id") == employee_id],
            key=lambda e: e.timestamp,
        )
        logouts = sorted(
            [e for e in logout_events if (e.payload or {}).get("employee_id") == employee_id],
            key=lambda e: e.timestamp,
        )

        # ── Pair logins with logouts into shifts ─────────────────────────────
        shifts: List[Dict[str, Any]] = []
        logout_idx = 0
        for login_ev in logins:
            t_in = login_ev.timestamp
            t_out = None
            # Find the next logout after this login
            while logout_idx < len(logouts):
                if logouts[logout_idx].timestamp > t_in:
                    t_out = logouts[logout_idx].timestamp
                    logout_idx += 1
                    break
                logout_idx += 1
            shifts.append({"in": t_in, "out": t_out})

        # ── Current shift (the most recent for this employee) ────────────────
        current_shift_in = None
        current_shift_out = None
        current_duration = ""
        if shifts:
            last = shifts[-1]
            current_shift_in = last["in"].isoformat()
            if last["out"]:
                current_shift_out = last["out"].isoformat()
                delta = last["out"] - last["in"]
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m = rem // 60
                current_duration = f"{h}h {m}m"

        # ── Daily breakdown ──────────────────────────────────────────────────
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        daily_hours: List[Dict[str, str]] = []
        total_seconds = 0

        for d in range(7):
            day_date = period_start + timedelta(days=d)
            if day_date > now:
                break
            day_end = day_date + timedelta(days=1)
            label = f"{day_names[d]} {day_date.strftime('%m/%d')}"

            # Find shifts overlapping this day
            day_shifts = [
                s for s in shifts
                if s["in"] < day_end and s["in"] >= day_date
            ]

            if not day_shifts:
                daily_hours.append({"label": label, "in": "--", "out": "--", "hours": "--"})
                continue

            day_total_secs = 0
            first_in = None
            last_out = None
            for s in day_shifts:
                t_in = s["in"]
                t_out = s["out"] or now  # still clocked in → use now
                if first_in is None:
                    first_in = t_in
                last_out = t_out
                secs = (t_out - t_in).total_seconds()
                day_total_secs += secs
                total_seconds += secs

            hrs = day_total_secs / 3600
            in_str = first_in.strftime("%I:%M%p") if first_in else "--"
            out_str = last_out.strftime("%I:%M%p") if last_out and day_shifts[-1]["out"] else "NOW"
            daily_hours.append({
                "label": label,
                "in": in_str,
                "out": out_str,
                "hours": f"{hrs:.1f}h",
            })

        total_hours = total_seconds / 3600
        period_end_date = period_start + timedelta(days=6)
        period_label = f"{period_start.strftime('%m/%d')} - {period_end_date.strftime('%m/%d')}"

        return {
            "restaurant_name": getattr(settings, "restaurant_name", "KINDpos"),
            "employee_name": employee_name,
            "role_name": role_name,
            "action": action,
            "date": now.strftime("%m/%d/%Y"),
            "time": now.strftime("%I:%M %p"),
            "clock_in": current_shift_in,
            "clock_out": current_shift_out,
            "shift_duration": current_duration,
            "period_label": period_label,
            "daily_hours": daily_hours,
            "period_total_hours": f"{total_hours:.1f}",
        }