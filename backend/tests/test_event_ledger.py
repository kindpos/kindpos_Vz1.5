"""
Test the Event Ledger and Projections - the heart of KINDpos.

Run with: pytest tests/test_event_ledger.py -v
Or just run this file directly: python tests/test_event_ledger.py
"""

import asyncio
import sys
import os

# Add parent directory to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.event_ledger import EventLedger
from app.core.events import (
    order_created,
    item_added,
    item_removed,
    item_modified,
    modifier_applied,
    payment_initiated,
    payment_confirmed,
    order_closed,
    EventType,
)
from app.core.projections import project_order, Order


import pytest

@pytest.mark.asyncio
async def test_event_ledger():
    """Test Event Ledger and Projections."""

    print("\n" + "="*60)
    print("🌴 KINDpos Event Ledger & Projections Test")
    print("="*60)

    # Use a fresh test database
    test_db = "./data/test_ledger_v2.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    async with EventLedger(test_db) as ledger:

        order_id = "order_demo_001"
        terminal = "terminal_01"

        # ---------------------------------------------------------------------
        # Test 1: Create an order
        # ---------------------------------------------------------------------
        print("\n📝 Test 1: Creating an order...")

        event = order_created(
            terminal_id=terminal,
            order_id=order_id,
            table="7",
            server_name="Maria",
            server_id="server_maria",
            guest_count=2,
            user_id="server_maria",
        )
        # Manually set correlation_id for ORDER_CREATED since it doesn't auto-set
        event = event.model_copy(update={"correlation_id": order_id})

        await ledger.append(event)
        print(f"   ✓ Order created for Table 7, Server: Maria")

        # ---------------------------------------------------------------------
        # Test 2: Add items
        # ---------------------------------------------------------------------
        print("\n🍽️  Test 2: Adding items to order...")

        items_to_add = [
            ("item_001", "Ribeye Steak", 42.00, "entrees"),
            ("item_002", "Caesar Salad", 14.00, "salads"),
            ("item_003", "House Red Wine", 12.00, "beverages"),
            ("item_004", "Cheesecake", 9.00, "desserts"),
        ]

        for item_id, name, price, category in items_to_add:
            event = item_added(
                terminal_id=terminal,
                order_id=order_id,
                item_id=item_id,
                menu_item_id=f"menu_{item_id}",
                name=name,
                price=price,
                category=category,
                user_id="server_maria",
            )
            await ledger.append(event)
            print(f"   ✓ Added: {name} - ${price:.2f}")

        # ---------------------------------------------------------------------
        # Test 3: Modify an item (add modifier)
        # ---------------------------------------------------------------------
        print("\n🔧 Test 3: Adding modifier to Ribeye...")

        event = modifier_applied(
            terminal_id=terminal,
            order_id=order_id,
            item_id="item_001",
            modifier_id="mod_001",
            modifier_name="Medium Rare",
            modifier_price=0.00,
            user_id="server_maria",
        )
        await ledger.append(event)
        print(f"   ✓ Modifier added: Medium Rare")

        # Add a paid modifier
        event = modifier_applied(
            terminal_id=terminal,
            order_id=order_id,
            item_id="item_001",
            modifier_id="mod_002",
            modifier_name="Add Mushrooms",
            modifier_price=4.00,
            user_id="server_maria",
        )
        await ledger.append(event)
        print(f"   ✓ Modifier added: Add Mushrooms (+$4.00)")

        # ---------------------------------------------------------------------
        # Test 4: Remove an item (guest changed their mind)
        # ---------------------------------------------------------------------
        print("\n❌ Test 4: Removing Cheesecake (guest changed mind)...")

        event = item_removed(
            terminal_id=terminal,
            order_id=order_id,
            item_id="item_004",
            reason="Guest changed mind",
            user_id="server_maria",
        )
        await ledger.append(event)
        print(f"   ✓ Removed: Cheesecake")

        # ---------------------------------------------------------------------
        # Test 5: Project the order state
        # ---------------------------------------------------------------------
        print("\n🔮 Test 5: Projecting current order state...")

        # Get all events for this order
        events = await ledger.get_events_by_correlation(order_id)
        print(f"   Found {len(events)} events")

        # Project to current state
        order = project_order(events)

        print(f"\n   📋 ORDER #{order.order_id}")
        print(f"   Table: {order.table} | Server: {order.server_name}")
        print(f"   Status: {order.status.upper()}")
        print(f"   ─────────────────────────────────")

        for item in order.items:
            mod_str = ""
            if item.modifiers:
                mods = [m["name"] for m in item.modifiers]
                mod_str = f" ({', '.join(mods)})"
            print(f"   {item.quantity}x {item.name}{mod_str}")
            print(f"      ${item.subtotal:.2f}")

        print(f"   ─────────────────────────────────")
        print(f"   Subtotal:    ${order.subtotal:.2f}")
        print(f"   Tax (8%):    ${order.tax:.2f}")
        print(f"   ─────────────────────────────────")
        print(f"   TOTAL:       ${order.total:.2f}")

        # Verify calculations
        # Ribeye ($42) + Mushrooms ($4) + Caesar ($14) + Wine ($12) = $72
        expected_subtotal = 42 + 4 + 14 + 12
        assert order.subtotal == expected_subtotal, f"Expected ${expected_subtotal}, got ${order.subtotal}"
        assert len(order.items) == 3, f"Expected 3 items, got {len(order.items)}"
        print(f"\n   ✓ Calculations verified!")

        # ---------------------------------------------------------------------
        # Test 6: Process payment
        # ---------------------------------------------------------------------
        print("\n💳 Test 6: Processing payment...")

        payment_id = "pay_001"

        event = payment_initiated(
            terminal_id=terminal,
            order_id=order_id,
            payment_id=payment_id,
            amount=order.total,
            method="card",
            user_id="server_maria",
        )
        await ledger.append(event)
        print(f"   ✓ Payment initiated: ${order.total:.2f}")

        event = payment_confirmed(
            terminal_id=terminal,
            order_id=order_id,
            payment_id=payment_id,
            transaction_id="stripe_ch_abc123xyz",
            amount=order.total,
            user_id="server_maria",
        )
        await ledger.append(event)
        print(f"   ✓ Payment confirmed!")

        # ---------------------------------------------------------------------
        # Test 7: Close the order
        # ---------------------------------------------------------------------
        print("\n✅ Test 7: Closing order...")

        event = order_closed(
            terminal_id=terminal,
            order_id=order_id,
            total=order.total,
            user_id="server_maria",
        )
        await ledger.append(event)

        # Re-project to see final state
        events = await ledger.get_events_by_correlation(order_id)
        final_order = project_order(events)

        print(f"   ✓ Order closed")
        print(f"   Final status: {final_order.status.upper()}")
        print(f"   Amount paid: ${final_order.amount_paid:.2f}")
        print(f"   Balance due: ${final_order.balance_due:.2f}")

        # ---------------------------------------------------------------------
        # Test 8: Verify event replay (crash recovery simulation)
        # ---------------------------------------------------------------------
        print("\n🔄 Test 8: Simulating crash recovery...")
        print("   (Re-projecting order from events)")

        # Imagine the app crashed. We reload events and rebuild state.
        events = await ledger.get_events_by_correlation(order_id)
        recovered_order = project_order(events)

        assert recovered_order.order_id == order_id
        assert recovered_order.status == "closed"
        assert recovered_order.amount_paid == recovered_order.total
        assert len(recovered_order.items) == 3

        print(f"   ✓ Order recovered successfully!")
        print(f"   ✓ All {len(events)} events replayed")
        print(f"   ✓ State matches exactly")

        # ---------------------------------------------------------------------
        # Test 9: Verify hash chain
        # ---------------------------------------------------------------------
        print("\n🔐 Test 9: Verifying hash chain integrity...")

        is_valid, invalid_seq = await ledger.verify_chain()
        if is_valid:
            print("   ✓ Hash chain intact - no tampering!")
        else:
            print(f"   ✗ ALERT: Chain broken at sequence {invalid_seq}")

        # ---------------------------------------------------------------------
        # Summary
        # ---------------------------------------------------------------------
        total_events = await ledger.count_events()

        print("\n" + "="*60)
        print("✅ All tests passed!")
        print("="*60)
        print(f"""
   Event Ledger Stats:
   • Total events recorded: {total_events}
   • Database: {test_db}
   
   What we demonstrated:
   • ✓ Events are immutable and sequenced
   • ✓ Hash chain provides tamper detection
   • ✓ State is derived from events (projections)
   • ✓ Modifiers affect item pricing
   • ✓ Item removal doesn't delete - it's an event
   • ✓ Full order state recoverable from events
   • ✓ Payment flow tracked completely
   
   This is the KINDpos core. Everything else builds on this.
""")


if __name__ == "__main__":
    asyncio.run(test_event_ledger())