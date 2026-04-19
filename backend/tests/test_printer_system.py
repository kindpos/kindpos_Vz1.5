# DEFERRED: test_payment_manager.py — mock out of sync with base_payment.py
# DEFERRED: printer health check — requires physical hardware, skip in CI

"""
KINDpos Printer Adapter System — Test Suite
=============================================
Nice. Dependable. Yours.

Tests every scenario we designed:
    1. Basic printing (thermal + impact)
    2. Double-print prevention
    3. Deliberate reprint (allowed)
    4. Retry on failure (silent, 3 attempts)
    5. Fallback Tier 1: Designated backup
    6. Fallback Tier 2: Same type + role
    7. All printers failed — job queued, manager alerted
    8. Queue retry when printer recovers
    9. Cash drawer operations
    10. Maintenance reboot cycle
    11. Health monitoring
    12. Custom role creation
    13. Rush order printing
    14. Delivery ticket printing
    15. Status summary / diagnostics
    16. Event Ledger audit trail + hash chain verification

Run from project root (KINDpos/):
    python -m backend.tests.test_printer_system

File location: backend/tests/test_printer_system.py
"""

import asyncio
import logging
import sys
import os

# Ensure the project root (KINDpos/) is on the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.core.adapters.base_printer import (
    PrinterConfig,
    PrinterType,
    PrinterStatus,
    PrintJob,
    PrintJobContent,
    PrintJobType,
    PrintJobPriority,
    OrderContext,
    CutType,
)
from app.core.adapters.mock_thermal import MockThermalPrinter
from app.core.adapters.mock_impact import MockImpactPrinter
from app.core.adapters.printer_manager import PrinterManager
from app.core.event_ledger import EventLedger
from app.core.events import EventType

# Logging — show the manager's work
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("kindpos.test")


# =============================================================
# HELPER: Create test printers
# =============================================================

def create_receipt_printer(name="Front Register", printer_id="printer-receipt-01"):
    config = PrinterConfig(
        printer_id=printer_id,
        name=name,
        printer_type=PrinterType.THERMAL,
        role="receipt",
        connection_string="usb://mock-thermal-01",
        location_tag="front counter",
        cut_type=CutType.FULL,
        operating_hours_start="06:00",
        operating_hours_end="23:00",
    )
    return MockThermalPrinter(config)


def create_kitchen_printer(name="Kitchen Main", printer_id="printer-kitchen-01"):
    config = PrinterConfig(
        printer_id=printer_id,
        name=name,
        printer_type=PrinterType.IMPACT,
        role="kitchen",
        connection_string="usb://mock-impact-01",
        location_tag="hot line",
        cut_type=CutType.TEAR,
        operating_hours_start="06:00",
        operating_hours_end="23:00",
    )
    return MockImpactPrinter(config)


def create_backup_kitchen_printer(name="Kitchen Backup", printer_id="printer-kitchen-02"):
    config = PrinterConfig(
        printer_id=printer_id,
        name=name,
        printer_type=PrinterType.IMPACT,
        role="kitchen",
        connection_string="usb://mock-impact-02",
        location_tag="cold line",
        cut_type=CutType.TEAR,
    )
    return MockImpactPrinter(config)


def create_bar_printer(name="Bar Printer", printer_id="printer-bar-01"):
    config = PrinterConfig(
        printer_id=printer_id,
        name=name,
        printer_type=PrinterType.THERMAL,
        role="bar",
        connection_string="usb://mock-thermal-02",
        location_tag="bar",
        cut_type=CutType.PARTIAL,
    )
    return MockThermalPrinter(config)


# =============================================================
# HELPER: Create test print jobs
# =============================================================

def create_kitchen_ticket(order_id="order-001", server="Maria"):
    return PrintJob(
        order_id=order_id,
        job_type=PrintJobType.KITCHEN_TICKET,
        order_context=OrderContext.DINE_IN,
        priority=PrintJobPriority.NORMAL,
        target_role="kitchen",
        terminal_id="terminal-01",
        server_name=server,
        content=PrintJobContent(
            header_lines=[
                "TABLE 7 -- SEAT 1",
                "Server: " + server,
            ],
            body_lines=[
                "1x  RIBEYE STEAK",
                "    > MED RARE",
                "    > NO MUSHROOMS",
                "1x  CAESAR SALAD",
                "    > DRESSING ON SIDE",
            ],
            footer_lines=[
                "*** FIRE ***",
            ],
            metadata={
                "table": "7",
                "seat": "1",
                "course": "entree",
            },
        ),
    )


def create_receipt(order_id="order-001", server="Maria"):
    return PrintJob(
        order_id=order_id,
        job_type=PrintJobType.RECEIPT,
        order_context=OrderContext.DINE_IN,
        priority=PrintJobPriority.NORMAL,
        target_role="receipt",
        terminal_id="terminal-01",
        server_name=server,
        content=PrintJobContent(
            header_lines=[
                "TONY'S PIZZA PALACE",
                "123 Main St, Miami FL",
                "================================",
            ],
            body_lines=[
                "1x  Ribeye Steak        $42.00",
                "1x  Caesar Salad        $14.00",
                "--------------------------------",
                "Subtotal                $56.00",
                "Tax (7%)                 $3.92",
                "================================",
                "TOTAL                   $59.92",
            ],
            footer_lines=[
                "VISA **** 4242          $59.92",
                "",
                "Thank you for dining with us!",
                "kindpos.com",
            ],
            metadata={
                "table": "7",
                "payment_method": "card",
                "transaction_id": "stripe_x9k2",
            },
        ),
    )


def create_rush_ticket(order_id="order-002", server="James"):
    job = create_kitchen_ticket(order_id=order_id, server=server)
    job.priority = PrintJobPriority.RUSH
    job.content.header_lines.insert(0, "!!! RUSH ORDER !!!")
    return job


def create_delivery_ticket(order_id="order-003", server="Alex"):
    return PrintJob(
        order_id=order_id,
        job_type=PrintJobType.KITCHEN_TICKET,
        order_context=OrderContext.DELIVERY,
        priority=PrintJobPriority.NORMAL,
        target_role="kitchen",
        terminal_id="terminal-01",
        server_name=server,
        content=PrintJobContent(
            header_lines=[
                "*** DELIVERY ***",
                "Server: " + server,
            ],
            body_lines=[
                "2x  LARGE PEPPERONI",
                "1x  GARLIC KNOTS",
                "1x  2-LITER COKE",
            ],
            footer_lines=[
                "DELIVER TO:",
                "456 Oak Ave, Apt 3B",
                "Customer: Johnson",
                "Phone: 555-0142",
                "Notes: Ring buzzer twice",
            ],
            metadata={
                "delivery_address": "456 Oak Ave, Apt 3B",
                "customer_name": "Johnson",
                "customer_phone": "555-0142",
            },
        ),
    )


# =============================================================
# TESTS
# =============================================================

import pytest

@pytest.mark.asyncio
async def test_basic_printing(manager):
    """Test 1: Kitchen ticket + receipt print normally."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic Printing")
    print("=" * 60)

    ticket = create_kitchen_ticket()
    result = await manager.submit_job(ticket)
    assert result.success, "Kitchen ticket should print! Got: " + str(result.message)
    print("  [PASS] Kitchen ticket printed successfully")

    receipt = create_receipt()
    result = await manager.submit_job(receipt)
    assert result.success, "Receipt should print! Got: " + str(result.message)
    print("  [PASS] Receipt printed successfully")

    print("  [PASS] TEST 1 PASSED")


@pytest.mark.asyncio
async def test_double_print_prevention(manager):
    """Test 2: Same job_id blocked on second attempt."""
    print("\n" + "=" * 60)
    print("TEST 2: Double-Print Prevention")
    print("=" * 60)

    ticket = create_kitchen_ticket(order_id="order-dup-test")

    result = await manager.submit_job(ticket)
    assert result.success, "First print should succeed"
    print("  [PASS] First print succeeded")

    result = await manager.submit_job(ticket)
    assert not result.success, "Duplicate should be blocked"
    assert result.error_code == "duplicate_blocked", \
        "Expected duplicate_blocked, got " + str(result.error_code)
    print("  [PASS] Duplicate correctly blocked")

    print("  [PASS] TEST 2 PASSED")


@pytest.mark.asyncio
async def test_deliberate_reprint(manager):
    """Test 3: Deliberate reprint allowed (new job_id, refs original)."""
    print("\n" + "=" * 60)
    print("TEST 3: Deliberate Reprint")
    print("=" * 60)

    original = create_kitchen_ticket(order_id="order-reprint-test")
    result = await manager.submit_job(original)
    assert result.success, "Original print should succeed"
    print("  [PASS] Original printed")

    reprint = PrintJob(
        order_id="order-reprint-test",
        job_type=PrintJobType.REPRINT,
        order_context=OrderContext.DINE_IN,
        target_role="kitchen",
        terminal_id="terminal-01",
        server_name="Maria",
        source_job_id=original.job_id,
        content=original.content,
    )
    result = await manager.submit_job(reprint)
    assert result.success, "Reprint should be allowed! Got: " + str(result.message)
    print("  [PASS] Reprint allowed (different job_id, references original)")

    print("  [PASS] TEST 3 PASSED")


@pytest.mark.asyncio
async def test_retry_on_failure(manager):
    """Test 4: Intermittent failure, silent retry succeeds."""
    print("\n" + "=" * 60)
    print("TEST 4: Retry on Failure")
    print("=" * 60)

    kitchen = None
    for p in manager.get_all_printers():
        if p.role == "kitchen" and p.name == "Kitchen Main":
            kitchen = p
            break
    assert kitchen, "Kitchen printer not found"

    kitchen.set_fail_mode("intermittent")

    ticket = create_kitchen_ticket(order_id="order-retry-test")
    result = await manager.submit_job(ticket)

    assert result.success, "Should succeed on retry! Got: " + str(result.message)
    print("  [PASS] Print succeeded after retry")

    kitchen.set_fail_mode(None)
    print("  [PASS] TEST 4 PASSED")


@pytest.mark.asyncio
async def test_fallback_tier1_designated(manager):
    """Test 5: Primary fails, falls back to designated backup."""
    print("\n" + "=" * 60)
    print("TEST 5: Fallback Tier 1 -- Designated Backup")
    print("=" * 60)

    kitchen_main = manager.get_printer("printer-kitchen-01")
    kitchen_backup = manager.get_printer("printer-kitchen-02")
    assert kitchen_main and kitchen_backup

    await manager.assign_fallback("printer-kitchen-01", "printer-kitchen-02")
    print("  [PASS] Fallback assigned: Kitchen Main -> Kitchen Backup")

    kitchen_main.set_fail_mode("offline")

    ticket = create_kitchen_ticket(order_id="order-fallback-t1")
    result = await manager.submit_job(ticket)

    assert result.success, "Fallback should catch it! Got: " + str(result.message)
    assert result.rerouted_from == "printer-kitchen-01", "Should show rerouted from main"
    print("  [PASS] Job rerouted to Kitchen Backup (Tier 1: designated)")

    kitchen_main.set_fail_mode(None)
    print("  [PASS] TEST 5 PASSED")


@pytest.mark.asyncio
async def test_fallback_tier2_same_type(manager):
    """Test 6: No designated backup, finds same type + role."""
    print("\n" + "=" * 60)
    print("TEST 6: Fallback Tier 2 -- Same Type + Role")
    print("=" * 60)

    kitchen_main = manager.get_printer("printer-kitchen-01")
    kitchen_main.get_config().fallback_printer_id = None
    kitchen_main.set_fail_mode("offline")

    # Explicitly target Kitchen Main — forces fallback to discover Backup
    ticket = create_kitchen_ticket(order_id="order-fallback-t2")
    ticket.target_printer_id = "printer-kitchen-01"
    result = await manager.submit_job(ticket)

    assert result.success, "Tier 2 fallback should work! Got: " + str(result.message)
    print("  [PASS] Job rerouted to Kitchen Backup (Tier 2: same type + role)")

    kitchen_main.set_fail_mode(None)
    print("  [PASS] TEST 6 PASSED")


@pytest.mark.asyncio
async def test_fallback_all_failed(manager):
    """Test 7: All kitchen printers fail -- job queued, manager alerted."""
    print("\n" + "=" * 60)
    print("TEST 7: All Printers Failed -- Queue + Alert")
    print("=" * 60)

    kitchen_main = manager.get_printer("printer-kitchen-01")
    kitchen_backup = manager.get_printer("printer-kitchen-02")
    kitchen_main.set_fail_mode("offline")
    kitchen_backup.set_fail_mode("offline")

    ticket = create_kitchen_ticket(order_id="order-all-fail")
    result = await manager.submit_job(ticket)

    assert not result.success, "Should fail when all printers are down"
    assert result.error_code == "all_printers_failed", \
        "Expected all_printers_failed, got " + str(result.error_code)
    print("  [PASS] Correctly reported all printers failed")

    queued = manager.get_queued_jobs()
    assert len(queued) > 0, "Job should be in the queue"
    print("  [PASS] Job queued (" + str(len(queued)) + " job(s) in queue)")

    kitchen_main.set_fail_mode(None)
    kitchen_backup.set_fail_mode(None)
    print("  [PASS] TEST 7 PASSED")


@pytest.mark.asyncio
async def test_queue_retry(manager):
    """Test 8: Queued jobs retry when printer recovers."""
    print("\n" + "=" * 60)
    print("TEST 8: Queue Retry on Recovery")
    print("=" * 60)

    # First, force a job into the queue by failing all kitchen printers
    kitchen_main = manager.get_printer("printer-kitchen-01")
    kitchen_backup = manager.get_printer("printer-kitchen-02")
    kitchen_main.set_fail_mode("offline")
    kitchen_backup.set_fail_mode("offline")

    ticket = create_kitchen_ticket(order_id="order-queue-retry")
    await manager.submit_job(ticket)

    queued_before = len(manager.get_queued_jobs())
    print("  Jobs in queue before retry: " + str(queued_before))
    assert queued_before > 0, "Should have a queued job"

    # Now recover printers and retry
    kitchen_main.set_fail_mode(None)
    kitchen_backup.set_fail_mode(None)

    results = await manager.retry_queued_jobs()

    succeeded = sum(1 for r in results if r.success)
    print("  Retried: " + str(len(results)) + " jobs, " + str(succeeded) + " succeeded")

    queued_after = len(manager.get_queued_jobs())
    print("  Jobs in queue after retry: " + str(queued_after))

    assert queued_after < queued_before, "Queue should shrink after retry"
    print("  [PASS] Queued jobs recovered successfully")

    print("  [PASS] TEST 8 PASSED")

@pytest.mark.asyncio

async def test_cash_drawer(manager):
    """Test 9: Cash drawer opens via receipt printer, fails on kitchen."""
    print("\n" + "=" * 60)
    print("TEST 9: Cash Drawer Operations")
    print("=" * 60)

    success = await manager.open_drawer(reason="payment", opened_by="Maria")
    assert success, "Drawer should open through receipt printer"
    print("  [PASS] Drawer opened via receipt printer")

    success = await manager.open_drawer(
        printer_id="printer-kitchen-01",
        reason="manual",
        opened_by="Manager",
    )
    assert not success, "Kitchen printer shouldn't have a drawer"
    print("  [PASS] Kitchen printer correctly reports no drawer")

    print("  [PASS] TEST 9 PASSED")


@pytest.mark.asyncio


async def test_maintenance_reboot(manager):
    """Test 10: Maintenance reboot cycle."""
    print("\n" + "=" * 60)
    print("TEST 10: Maintenance Reboot Cycle")
    print("=" * 60)

    results = await manager.maintenance_cycle()

    total = len(results)
    succeeded = sum(1 for v in results.values() if v)

    print("  Rebooted: " + str(succeeded) + "/" + str(total) + " printers")
    assert succeeded == total, "All reboots should succeed"
    print("  [PASS] All printers rebooted successfully")

    print("  [PASS] TEST 10 PASSED")


@pytest.mark.asyncio


async def test_health_check(manager):
    """Test 11: Health monitoring and status detection."""
    print("\n" + "=" * 60)
    print("TEST 11: Health Monitoring")
    print("=" * 60)

    statuses = await manager.check_all_printers()
    for printer_id, status in statuses.items():
        printer = manager.get_printer(printer_id)
        print("  " + printer.name + ": " + status.value)

    assert all(s == PrinterStatus.ONLINE for s in statuses.values()), \
        "All printers should be online after reboot"
    print("  [PASS] All printers reporting online")

    kitchen = manager.get_printer("printer-kitchen-01")
    kitchen.set_fail_mode("offline")
    statuses = await manager.check_all_printers()
    assert statuses["printer-kitchen-01"] == PrinterStatus.OFFLINE
    print("  [PASS] Detected offline printer")

    kitchen.set_fail_mode(None)
    kitchen.connect()
    print("  [PASS] TEST 11 PASSED")


@pytest.mark.asyncio


async def test_custom_roles(manager):
    """Test 12: Custom printer role creation."""
    print("\n" + "=" * 60)
    print("TEST 12: Custom Roles")
    print("=" * 60)

    await manager.create_custom_role("Pizza Station", created_by="Owner")
    await manager.create_custom_role("Patio Bar", created_by="Owner")
    await manager.create_custom_role("Delivery", created_by="Owner")

    roles = manager.get_available_roles()
    print("  Available roles: " + str(sorted(roles)))

    assert "pizza station" in roles
    assert "patio bar" in roles
    assert "delivery" in roles

    result = await manager.create_custom_role("Pizza Station")
    assert not result, "Duplicate role should return False"
    print("  [PASS] Duplicate role correctly rejected")

    print("  [PASS] TEST 12 PASSED")


@pytest.mark.asyncio


async def test_rush_order(manager):
    """Test 13: Rush order prints with emphasis."""
    print("\n" + "=" * 60)
    print("TEST 13: Rush Order")
    print("=" * 60)

    rush = create_rush_ticket()
    assert rush.is_rush, "Should be marked as rush"

    result = await manager.submit_job(rush)
    assert result.success, "Rush order should print! Got: " + str(result.message)
    print("  [PASS] Rush order printed with emphasis")

    print("  [PASS] TEST 13 PASSED")


@pytest.mark.asyncio


async def test_delivery_ticket(manager):
    """Test 14: Delivery ticket with address info."""
    print("\n" + "=" * 60)
    print("TEST 14: Delivery Ticket")
    print("=" * 60)

    delivery = create_delivery_ticket()
    assert delivery.order_context == OrderContext.DELIVERY

    result = await manager.submit_job(delivery)
    assert result.success, "Delivery ticket should print! Got: " + str(result.message)
    print("  [PASS] Delivery ticket printed with address info")

    print("  [PASS] TEST 14 PASSED")


@pytest.mark.asyncio


async def test_status_summary(manager):
    """Test 15: Full status summary for diagnostics."""
    print("\n" + "=" * 60)
    print("TEST 15: Status Summary")
    print("=" * 60)

    summary = manager.get_status_summary()

    print("  Terminal: " + summary["terminal_id"])
    print("  Total printers: " + str(summary["total_printers"]))
    print("  Ready printers: " + str(summary["ready_printers"]))
    print("  Queued jobs: " + str(summary["queued_jobs"]))
    print("  Available roles: " + str(summary["available_roles"]))
    print("  Printers:")
    for p in summary["printers"]:
        line = "    - " + p["name"]
        line += " (" + p["type"] + "/" + p["role"] + ")"
        line += " -- " + p["status"]
        print(line)

    assert summary["total_printers"] == 4, "Should have 4 printers"
    print("  [PASS] Status summary complete")

    print("  [PASS] TEST 15 PASSED")


@pytest.mark.asyncio


async def test_event_ledger_audit(ledger):
    """Test 16: Verify the Event Ledger captured everything."""
    print("\n" + "=" * 60)
    print("TEST 16: Event Ledger Audit Trail")
    print("=" * 60)

    total = await ledger.count_events()
    print("  Total events in ledger: " + str(total))

    event_types_to_check = [
        (EventType.PRINTER_REGISTERED, "Printer registrations"),
        (EventType.TICKET_PRINTED, "Successful prints"),
        (EventType.TICKET_PRINT_FAILED, "Failed prints"),
        (EventType.TICKET_REPRINTED, "Reprints"),
        (EventType.PRINT_RETRYING, "Retries"),
        (EventType.PRINT_REROUTED, "Reroutes"),
        (EventType.PRINTER_ERROR, "Errors/alerts"),
        (EventType.DRAWER_OPENED, "Drawer opens"),
        (EventType.DRAWER_OPEN_FAILED, "Drawer failures"),
        (EventType.PRINTER_REBOOT_STARTED, "Reboots started"),
        (EventType.PRINTER_REBOOT_COMPLETED, "Reboots completed"),
        (EventType.PRINTER_ROLE_CREATED, "Custom roles"),
        (EventType.PRINTER_FALLBACK_ASSIGNED, "Fallback assignments"),
        (EventType.PRINTER_STATUS_CHANGED, "Status changes"),
    ]

    for event_type, label in event_types_to_check:
        events = await ledger.get_events_by_type(event_type)
        count = len(events)
        indicator = "[X]" if count > 0 else "[ ]"
        print("  " + indicator + " " + label + ": " + str(count))

    # Verify hash chain integrity
    is_valid, invalid_at = await ledger.verify_chain()
    if is_valid:
        print("\n  [PASS] Hash chain integrity: VALID (" + str(total) + " events)")
    else:
        print("\n  [FAIL] Hash chain broken at sequence " + str(invalid_at))

    assert is_valid, "Hash chain should be valid!"

    print("\n  [PASS] TEST 16 PASSED")


# =============================================================
# MAIN
# =============================================================

async def run_all_tests():
    """Run the complete test suite."""
    print()
    print("+" + "-" * 58 + "+")
    print("|    KINDpos Printer Adapter System -- Test Suite            |")
    print("|    Nice. Dependable. Yours.                               |")
    print("+" + "-" * 58 + "+")

    # Use a temporary test database
    db_path = os.path.join(project_root, "data", "test_printer_system.db")

    # Clean up previous test database
    for ext in ["", "-shm", "-wal"]:
        path = db_path + ext
        if os.path.exists(path):
            os.remove(path)

    async with EventLedger(db_path) as ledger:
        manager = PrinterManager(ledger=ledger, terminal_id="terminal-01")

        # Register printers
        print("\n" + "=" * 60)
        print("SETUP: Registering Printers")
        print("=" * 60)

        await manager.register_printer(create_receipt_printer())
        await manager.register_printer(create_kitchen_printer())
        await manager.register_printer(create_backup_kitchen_printer())
        await manager.register_printer(create_bar_printer())

        printer_count = len(manager.get_all_printers())
        print("  [PASS] Registered " + str(printer_count) + " printers")

        # Run all tests
        try:
            await test_basic_printing(manager)
            await test_double_print_prevention(manager)
            await test_deliberate_reprint(manager)
            await test_retry_on_failure(manager)
            await test_fallback_tier1_designated(manager)
            await test_fallback_tier2_same_type(manager)
            await test_fallback_all_failed(manager)
            await test_queue_retry(manager)
            await test_cash_drawer(manager)
            await test_maintenance_reboot(manager)
            await test_health_check(manager)
            await test_custom_roles(manager)
            await test_rush_order(manager)
            await test_delivery_ticket(manager)
            await test_status_summary(manager)
            await test_event_ledger_audit(ledger)

            print()
            print("+" + "-" * 58 + "+")
            print("|                                                          |")
            print("|    ALL 16 TESTS PASSED!                                  |")
            print("|                                                          |")
            print("|    The printer adapter system is solid.                   |")
            print("|    Swap the brain. Keep your hardware.                    |")
            print("|                                                          |")
            print("|    Nice. Dependable. Yours.                              |")
            print("|                                                          |")
            print("+" + "-" * 58 + "+")
            print()

        except AssertionError as e:
            print("\n  [FAIL] TEST FAILED: " + str(e))
            raise
        except Exception as e:
            print("\n  [FAIL] UNEXPECTED ERROR: " + str(e))
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())