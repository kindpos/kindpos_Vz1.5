"""
KINDpos Printer Manager — The Brain
=====================================
Nice. Dependable. Yours.

The PrinterManager is the brain of the printer adapter system.
Adapters are translators — they just talk to hardware.
The Manager does all the thinking:

    - Job routing: Find the right printer for the job
    - Double-print prevention: Check the Event Ledger before printing
    - Retry logic: 2-3 silent retries before escalating
    - Fallback hierarchy: Designated backup → same type/role → emergency
    - Manager alerts: Notify via Messenger when all else fails
    - Maintenance scheduling: Off-hours reboots to extend hardware life
    - Printer registry: Track all printers, their status, and roles

The Manager never talks to hardware directly. It tells adapters what
to do and records everything in the Event Ledger.

File location: backend/app/core/adapters/printer_manager.py
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .base_printer import (
    BasePrinter,
    PrinterConfig,
    PrinterType,
    PrinterStatus,
    PrintJob,
    PrintJobType,
    PrintResult,
    CutType,
)

from ..events import (
    EventType,
    Event,
    ticket_printed,
    ticket_print_failed,
    ticket_reprinted,
    print_retrying,
    print_rerouted,
    printer_registered,
    printer_status_changed,
    printer_error,
    printer_role_created,
    printer_fallback_assigned,
    printer_reboot_started,
    printer_reboot_completed,
    printer_health_warning,
    drawer_opened,
    drawer_open_failed,
)

from ..event_ledger import EventLedger
from ..ephemeral_log import EphemeralLog

logger = logging.getLogger("kindpos.printer.manager")


# How many times to retry before escalating
MAX_RETRIES = 3

# Seconds between retry attempts
RETRY_DELAY = 1.0


class PrinterManager:
    """
    Central manager for all printer operations.

    Owns the printer registry, handles job routing, retries,
    fallback, and maintenance. All actions are event-sourced
    through the Event Ledger.

    Usage:
        manager = PrinterManager(ledger=event_ledger, terminal_id="terminal-01")

        # Register printers
        manager.register_printer(receipt_printer)
        manager.register_printer(kitchen_printer)

        # Print a job — manager handles everything
        result = await manager.submit_job(print_job)

        # Open cash drawer
        result = await manager.open_drawer()

        # Schedule maintenance
        await manager.schedule_maintenance()
    """

    def __init__(self, ledger: EventLedger, terminal_id: str, ephemeral_log: Optional[EphemeralLog] = None):
        """
        Initialize the PrinterManager.

        Args:
            ledger: The Event Ledger for recording all actions
            terminal_id: This terminal's ID (for event creation)
            ephemeral_log: Separate non-chained log for operational telemetry
        """
        self._ledger = ledger
        self._ephemeral = ephemeral_log or ledger  # fall back to ledger if not provided
        self._terminal_id = terminal_id
        self._printers: dict[str, BasePrinter] = {}  # printer_id -> adapter
        self._custom_roles: set[str] = {"receipt", "kitchen", "bar"}  # Default roles
        self._print_queue: list[PrintJob] = []  # Jobs waiting for retry/reroute

        logger.info(f"[MANAGER] PrinterManager initialized (terminal={terminal_id})")

    # =================================================================
    # PRINTER REGISTRY
    # =================================================================

    async def register_printer(self, printer: BasePrinter) -> bool:
        """
        Register a printer adapter with the manager.

        Connects to the printer, records a PRINTER_REGISTERED event,
        and adds it to the active registry.
        """
        printer_id = printer.printer_id

        if printer_id in self._printers:
            logger.warning(f"[MANAGER] Printer '{printer.name}' already registered")
            return False

        # Try to connect
        connected = printer.connect()
        if not connected:
            logger.warning(
                f"[MANAGER] Printer '{printer.name}' registered but failed to connect"
            )

        # Add to registry
        self._printers[printer_id] = printer

        # Record event
        event = printer_registered(
            terminal_id=self._terminal_id,
            printer_id=printer_id,
            printer_name=printer.name,
            printer_type=printer.printer_type.value,
            connection_string=printer.get_config().connection_string,
            role=printer.role,
            discovered_via="manual",
        )
        await self._ledger.append(event)

        logger.info(
            f"[MANAGER] Registered: '{printer.name}' "
            f"(type={printer.printer_type.value}, role={printer.role}, "
            f"status={printer.status.value})"
        )
        return True

    async def unregister_printer(self, printer_id: str) -> bool:
        """Remove a printer from the registry and disconnect."""
        printer = self._printers.get(printer_id)
        if not printer:
            logger.warning(f"[MANAGER] Cannot unregister — printer '{printer_id}' not found")
            return False

        printer.disconnect()
        del self._printers[printer_id]
        logger.info(f"[MANAGER] Unregistered: '{printer.name}'")
        return True

    def get_printer(self, printer_id: str) -> Optional[BasePrinter]:
        """Get a printer by ID."""
        return self._printers.get(printer_id)

    def get_all_printers(self) -> list[BasePrinter]:
        """Get all registered printers."""
        return list(self._printers.values())

    def get_printers_by_role(self, role: str) -> list[BasePrinter]:
        """Get all printers assigned to a specific role."""
        return [
            p for p in self._printers.values()
            if p.can_handle_role(role)
        ]

    def get_ready_printers_by_role(self, role: str) -> list[BasePrinter]:
        """Get all printers that are ready AND match the role."""
        return [
            p for p in self._printers.values()
            if p.can_handle_role(role) and p.is_ready()
        ]

    # =================================================================
    # CUSTOM ROLES
    # =================================================================

    async def create_custom_role(self, role_name: str, created_by: Optional[str] = None) -> bool:
        """
        Create a custom printer role.
        Operators can define roles like "Pizza Station", "Patio Bar", etc.
        """
        role_lower = role_name.lower().strip()
        if role_lower in self._custom_roles:
            logger.warning(f"[MANAGER] Role '{role_name}' already exists")
            return False

        self._custom_roles.add(role_lower)

        event = printer_role_created(
            terminal_id=self._terminal_id,
            role_name=role_name,
            created_by=created_by,
        )
        await self._ephemeral.append(event)

        logger.info(f"[MANAGER] Custom role created: '{role_name}'")
        return True

    def get_available_roles(self) -> set[str]:
        """Get all available printer roles (default + custom)."""
        return self._custom_roles.copy()

    # =================================================================
    # FALLBACK ASSIGNMENT
    # =================================================================

    async def assign_fallback(
        self,
        printer_id: str,
        fallback_printer_id: str,
    ) -> bool:
        """
        Designate a backup printer for fallback routing.
        Operator sets this during setup — calm time, not Friday rush.
        """
        printer = self._printers.get(printer_id)
        fallback = self._printers.get(fallback_printer_id)

        if not printer:
            logger.warning(f"[MANAGER] Cannot assign fallback — printer '{printer_id}' not found")
            return False
        if not fallback:
            logger.warning(f"[MANAGER] Cannot assign fallback — fallback '{fallback_printer_id}' not found")
            return False

        # Update config
        printer.get_config().fallback_printer_id = fallback_printer_id

        # Record event
        event = printer_fallback_assigned(
            terminal_id=self._terminal_id,
            printer_id=printer_id,
            printer_name=printer.name,
            fallback_printer_id=fallback_printer_id,
            fallback_printer_name=fallback.name,
        )
        await self._ephemeral.append(event)

        logger.info(
            f"[MANAGER] Fallback assigned: '{printer.name}' → '{fallback.name}'"
        )
        return True

    # =================================================================
    # DOUBLE-PRINT PREVENTION
    # =================================================================

    async def _has_already_printed(self, job_id: str) -> bool:
        """
        Check the Event Ledger to see if this job has already been printed.

        Queries TICKET_PRINTED events and checks payload for matching job_id.
        This is the core of double-print prevention.
        """
        printed_events = await self._ledger.get_events_by_type(
            EventType.TICKET_PRINTED
        )
        for event in printed_events:
            if event.payload.get("job_id") == job_id:
                return True
        return False

    # =================================================================
    # JOB SUBMISSION — The Main Event
    # =================================================================

    async def submit_job(self, job: PrintJob) -> PrintResult:
        """
        Submit a print job. The manager handles everything:
            1. Double-print check
            2. Find the right printer
            3. Try to print
            4. Retry on failure (up to MAX_RETRIES)
            5. Fallback to backup printer
            6. Alert manager if all else fails

        This is the only method the rest of KINDpos needs to call
        for printing. Everything else is handled internally.
        """
        logger.info(
            f"[MANAGER] Job submitted: {job.job_id[:8]}... "
            f"(order={job.order_id}, type={job.job_type.value}, "
            f"role={job.target_role})"
        )

        # ----- Step 1: Double-print prevention -----
        if not job.is_reprint:
            already_printed = await self._has_already_printed(job.job_id)
            if already_printed:
                logger.warning(
                    f"[MANAGER] BLOCKED duplicate print: {job.job_id[:8]}... "
                    f"(order={job.order_id})"
                )
                return PrintResult(
                    success=False,
                    job_id=job.job_id,
                    printer_id="",
                    message="Duplicate print blocked — already printed",
                    error_code="duplicate_blocked",
                )

        # ----- Step 2: Find the right printer -----
        target_printer = self._resolve_printer(job)

        if not target_printer:
            logger.error(
                f"[MANAGER] No printer available for role '{job.target_role}'"
            )
            # No printer at all — queue it and alert
            self._print_queue.append(job)
            await self._alert_no_printer(job)
            return PrintResult(
                success=False,
                job_id=job.job_id,
                printer_id="",
                message=f"No printer available for role '{job.target_role}'",
                error_code="no_printer_available",
            )

        # ----- Step 3: Try to print with retries -----
        result = await self._print_with_retries(job, target_printer)

        if result.success:
            return result

        # ----- Step 4: Primary failed — try fallback -----
        logger.warning(
            f"[MANAGER] Primary printer '{target_printer.name}' failed "
            f"after {MAX_RETRIES} retries. Starting fallback..."
        )

        fallback_result = await self._try_fallback(job, target_printer)

        if fallback_result and fallback_result.success:
            return fallback_result

        # ----- Step 5: All printers failed — alert manager -----
        logger.error(
            f"[MANAGER] ALL printers failed for job {job.job_id[:8]}... "
            f"Alerting manager and queuing job."
        )
        self._print_queue.append(job)
        await self._alert_print_failure(job, target_printer)

        return PrintResult(
            success=False,
            job_id=job.job_id,
            printer_id=target_printer.printer_id,
            message="All printers failed — job queued, manager alerted",
            error_code="all_printers_failed",
            retry_count=MAX_RETRIES,
        )

    # =================================================================
    # PRINTER RESOLUTION — Find the right printer
    # =================================================================

    def _resolve_printer(self, job: PrintJob) -> Optional[BasePrinter]:
        """
        Find the best printer for this job.

        Returns the PRIMARY printer for this role. If the primary is down,
        submit_job will fast-fail and trigger the fallback hierarchy.

        Priority:
            1. Specific printer override (job.target_printer_id)
            2. Designated primary for role (has fallback configured — even if offline)
            3. First ready printer matching the target role
            4. First ANY printer matching the role (even if not ready)
        """
        # Specific printer override
        if job.target_printer_id:
            printer = self._printers.get(job.target_printer_id)
            if printer:
                return printer
            logger.warning(
                f"[MANAGER] Specified printer '{job.target_printer_id}' "
                f"not found, falling back to role match"
            )

        # Check for a designated primary (has fallback assigned)
        # This is the printer the operator configured as "the" printer
        # for this role — even if it's down, we want the fallback chain
        role_printers = self.get_printers_by_role(job.target_role)
        for printer in role_printers:
            config = printer.get_config()
            if config.fallback_printer_id:
                return printer  # This is the designated primary

        # No designated primary — use first ready printer
        ready_printers = self.get_ready_printers_by_role(job.target_role)
        if ready_printers:
            return ready_printers[0]

        # No ready printers — return any printer with this role
        if role_printers:
            return role_printers[0]

        return None

    # =================================================================
    # RETRY LOGIC — Silent retries before escalating
    # =================================================================

    async def _print_with_retries(
        self,
        job: PrintJob,
        printer: BasePrinter,
    ) -> PrintResult:
        """
        Try to print on the given printer with up to MAX_RETRIES attempts.

        Each retry is:
            - Silent (staff never sees it)
            - Logged as a PRINT_RETRYING event
            - Delayed slightly to let transient errors clear

        If the printer is known offline, fail immediately (no wasted retries).
        """
        # Fast-fail: if printer is offline, don't waste time retrying
        if not printer.is_ready():
            logger.info(
                f"[MANAGER] Printer '{printer.name}' is not ready "
                f"(status={printer.status.value}) — skipping retries"
            )
            fail_event = ticket_print_failed(
                terminal_id=self._terminal_id,
                order_id=job.order_id,
                printer_id=printer.printer_id,
                error=f"Printer not ready (status: {printer.status.value})",
                will_retry=False,
            )
            await self._ephemeral.append(fail_event)

            return PrintResult(
                success=False,
                job_id=job.job_id,
                printer_id=printer.printer_id,
                message=f"Printer '{printer.name}' is {printer.status.value}",
                error_code="printer_not_ready",
            )

        last_result = None

        for attempt in range(1, MAX_RETRIES + 1):
            result = printer.print_job(job)

            if result.success:
                # Record success in the Event Ledger
                if job.is_reprint:
                    event = ticket_reprinted(
                        terminal_id=self._terminal_id,
                        order_id=job.order_id,
                        printer_id=printer.printer_id,
                        printer_name=printer.name,
                        original_job_id=job.source_job_id,
                        ticket_type=job.target_role,
                    )
                else:
                    event = ticket_printed(
                        terminal_id=self._terminal_id,
                        order_id=job.order_id,
                        printer_id=printer.printer_id,
                        printer_name=printer.name,
                        ticket_type=job.target_role,
                    )

                # Add job_id to payload for double-print prevention lookups
                enriched_payload = {**event.payload, "job_id": job.job_id}
                event = Event(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    terminal_id=event.terminal_id,
                    event_type=event.event_type,
                    payload=enriched_payload,
                    user_id=event.user_id,
                    user_role=event.user_role,
                    correlation_id=event.correlation_id,
                )
                await self._ledger.append(event)

                if attempt > 1:
                    logger.info(
                        f"[MANAGER] Print succeeded on retry {attempt} "
                        f"(printer='{printer.name}')"
                    )
                return result

            # Print failed — log retry event
            last_result = result

            if attempt < MAX_RETRIES:
                retry_event = print_retrying(
                    terminal_id=self._terminal_id,
                    order_id=job.order_id,
                    printer_id=printer.printer_id,
                    job_id=job.job_id,
                    retry_count=attempt,
                    error=result.message,
                )
                await self._ephemeral.append(retry_event)

                logger.info(
                    f"[MANAGER] Retry {attempt}/{MAX_RETRIES} "
                    f"for job {job.job_id[:8]}... on '{printer.name}'"
                )
                await asyncio.sleep(RETRY_DELAY)

        # All retries exhausted — log failure
        fail_event = ticket_print_failed(
            terminal_id=self._terminal_id,
            order_id=job.order_id,
            printer_id=printer.printer_id,
            error=last_result.message if last_result else "Unknown error",
            will_retry=False,
        )
        await self._ephemeral.append(fail_event)

        return last_result

    # =================================================================
    # FALLBACK HIERARCHY — When the primary fails
    # =================================================================

    async def _try_fallback(
        self,
        job: PrintJob,
        failed_printer: BasePrinter,
    ) -> Optional[PrintResult]:
        """
        Walk the fallback hierarchy:
            1. Designated backup (operator-assigned)
            2. Same type AND role (impact→impact kitchen, thermal→thermal receipt)
            3. Any printer matching role (emergency — better than nothing)

        Returns PrintResult on success, None if all fallbacks fail.
        """
        failed_id = failed_printer.printer_id

        # ----- Tier 1: Designated backup -----
        fallback_id = failed_printer.fallback_printer_id
        if fallback_id:
            fallback = self._printers.get(fallback_id)
            if fallback and fallback.is_ready():
                logger.info(
                    f"[MANAGER] Fallback Tier 1 (designated): "
                    f"'{failed_printer.name}' → '{fallback.name}'"
                )
                result = await self._print_on_fallback(
                    job, failed_printer, fallback, "designated"
                )
                if result and result.success:
                    return result

        # ----- Tier 2: Same type AND role -----
        same_type_printers = [
            p for p in self._printers.values()
            if p.printer_id != failed_id
            and p.is_ready()
            and p.matches_type(failed_printer.printer_type)
            and p.can_handle_role(job.target_role)
        ]
        for fallback in same_type_printers:
            logger.info(
                f"[MANAGER] Fallback Tier 2 (same type + role): "
                f"'{failed_printer.name}' → '{fallback.name}'"
            )
            result = await self._print_on_fallback(
                job, failed_printer, fallback, "same_type"
            )
            if result and result.success:
                return result

        # ----- Tier 3: Any printer matching role (emergency) -----
        any_role_printers = [
            p for p in self._printers.values()
            if p.printer_id != failed_id
            and p.is_ready()
            and p.can_handle_role(job.target_role)
        ]
        for fallback in any_role_printers:
            # Skip ones we already tried in Tier 2
            if fallback in same_type_printers:
                continue
            logger.info(
                f"[MANAGER] Fallback Tier 3 (emergency — any matching role): "
                f"'{failed_printer.name}' → '{fallback.name}'"
            )
            result = await self._print_on_fallback(
                job, failed_printer, fallback, "emergency"
            )
            if result and result.success:
                return result

        # All fallbacks exhausted
        return None

    async def _print_on_fallback(
        self,
        job: PrintJob,
        original_printer: BasePrinter,
        fallback_printer: BasePrinter,
        tier: str,
    ) -> Optional[PrintResult]:
        """
        Attempt to print on a fallback printer.
        Single attempt — no retries on fallbacks (keep it moving).
        Logs a PRINT_REROUTED event.
        """
        result = fallback_printer.print_job(job)

        if result.success:
            # Log the reroute
            reroute_event = print_rerouted(
                terminal_id=self._terminal_id,
                order_id=job.order_id,
                job_id=job.job_id,
                original_printer_id=original_printer.printer_id,
                original_printer_name=original_printer.name,
                rerouted_to_printer_id=fallback_printer.printer_id,
                rerouted_to_printer_name=fallback_printer.name,
                reason=f"Primary printer failed after {MAX_RETRIES} retries",
                fallback_tier=tier,
            )
            await self._ephemeral.append(reroute_event)

            # Also log the successful print
            print_event = ticket_printed(
                terminal_id=self._terminal_id,
                order_id=job.order_id,
                printer_id=fallback_printer.printer_id,
                printer_name=fallback_printer.name,
                ticket_type=job.target_role,
            )
            enriched_payload = {**print_event.payload, "job_id": job.job_id}
            print_event = Event(
                event_id=print_event.event_id,
                timestamp=print_event.timestamp,
                terminal_id=print_event.terminal_id,
                event_type=print_event.event_type,
                payload=enriched_payload,
                user_id=print_event.user_id,
                user_role=print_event.user_role,
                correlation_id=print_event.correlation_id,
            )
            await self._ledger.append(print_event)

            result.rerouted_from = original_printer.printer_id

            logger.info(
                f"[MANAGER] Fallback SUCCESS (tier={tier}): "
                f"'{original_printer.name}' → '{fallback_printer.name}'"
            )

        return result

    # =================================================================
    # CASH DRAWER
    # =================================================================

    async def open_drawer(
        self,
        printer_id: Optional[str] = None,
        reason: str = "payment",
        opened_by: Optional[str] = None,
    ) -> bool:
        """
        Open the cash drawer.

        If no printer_id is specified, finds the first receipt printer
        (cash drawers connect through receipt printers).
        """
        # Find the right printer
        if printer_id:
            printer = self._printers.get(printer_id)
        else:
            # Cash drawers are on receipt printers
            receipt_printers = self.get_ready_printers_by_role("receipt")
            printer = receipt_printers[0] if receipt_printers else None

        if not printer:
            logger.error("[MANAGER] No receipt printer available for drawer kick")
            fail_event = drawer_open_failed(
                terminal_id=self._terminal_id,
                printer_id=printer_id or "unknown",
                error="No receipt printer available",
            )
            await self._ephemeral.append(fail_event)
            return False

        # Try to open
        success = printer.open_drawer()

        if success:
            event = drawer_opened(
                terminal_id=self._terminal_id,
                printer_id=printer.printer_id,
                reason=reason,
                opened_by=opened_by,
            )
            await self._ephemeral.append(event)
            logger.info(
                f"[MANAGER] Drawer opened via '{printer.name}' "
                f"(reason={reason}, by={opened_by})"
            )
        else:
            event = drawer_open_failed(
                terminal_id=self._terminal_id,
                printer_id=printer.printer_id,
                error="Drawer kick command failed",
            )
            await self._ephemeral.append(event)
            logger.warning(f"[MANAGER] Drawer kick failed on '{printer.name}'")

        return success

    # =================================================================
    # HEALTH MONITORING
    # =================================================================

    async def check_all_printers(self) -> dict[str, PrinterStatus]:
        """
        Check status of all registered printers.
        Updates internal status and logs any changes.
        """
        results = {}

        for printer_id, printer in self._printers.items():
            previous_status = printer.status
            current_status = printer.check_status()
            results[printer_id] = current_status

            # Log status change
            if current_status != previous_status:
                event = printer_status_changed(
                    terminal_id=self._terminal_id,
                    printer_id=printer_id,
                    printer_name=printer.name,
                    previous_status=previous_status.value,
                    new_status=current_status.value,
                )
                await self._ephemeral.append(event)

                logger.info(
                    f"[MANAGER] Status change: '{printer.name}' "
                    f"{previous_status.value} → {current_status.value}"
                )

                # Proactive health warning
                if current_status == PrinterStatus.OVERHEATED:
                    warning_event = printer_health_warning(
                        terminal_id=self._terminal_id,
                        printer_id=printer_id,
                        printer_name=printer.name,
                        warning_type="overheating",
                        details="Print head temperature elevated — scheduled reboot recommended",
                    )
                    await self._ephemeral.append(warning_event)

        return results

    # =================================================================
    # MAINTENANCE — Off-hours reboots
    # =================================================================

    async def reboot_printer(self, printer_id: str) -> bool:
        """
        Reboot a specific printer.
        Used for scheduled maintenance or manual intervention.
        """
        printer = self._printers.get(printer_id)
        if not printer:
            logger.warning(f"[MANAGER] Cannot reboot — printer '{printer_id}' not found")
            return False

        # Log start
        start_event = printer_reboot_started(
            terminal_id=self._terminal_id,
            printer_id=printer_id,
            printer_name=printer.name,
            reason="scheduled_maintenance",
        )
        await self._ephemeral.append(start_event)

        start_time = datetime.now(timezone.utc)

        # Execute reboot
        success = printer.reboot()

        # Log completion
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        complete_event = printer_reboot_completed(
            terminal_id=self._terminal_id,
            printer_id=printer_id,
            printer_name=printer.name,
            duration_seconds=duration,
        )
        await self._ephemeral.append(complete_event)

        logger.info(
            f"[MANAGER] Reboot {'complete' if success else 'failed'}: "
            f"'{printer.name}' ({duration:.1f}s)"
        )
        return success

    async def maintenance_cycle(self) -> dict[str, bool]:
        """
        Run maintenance on all printers.

        Call this during off-hours (scheduled by the system
        based on operating_hours in PrinterConfig).

        Reboots each printer, lets heads cool, clears buffers.
        Extends hardware life significantly.
        """
        results = {}
        logger.info("[MANAGER] Starting maintenance cycle...")

        for printer_id, printer in self._printers.items():
            logger.info(f"[MANAGER] Maintenance: '{printer.name}'...")
            success = await self.reboot_printer(printer_id)
            results[printer_id] = success

        logger.info(
            f"[MANAGER] Maintenance cycle complete. "
            f"{sum(results.values())}/{len(results)} successful."
        )
        return results

    # =================================================================
    # ALERTS — When things go wrong
    # =================================================================

    async def _alert_print_failure(
        self,
        job: PrintJob,
        failed_printer: BasePrinter,
    ) -> None:
        """
        Alert the manager that a print job failed on all printers.

        This would integrate with the KINDpos Messenger system.
        For now, logs the alert and records a PRINTER_ERROR event.

        Deferred: connect to Messenger system for real-time manager alerts
        """
        error_event = printer_error(
            terminal_id=self._terminal_id,
            printer_id=failed_printer.printer_id,
            printer_name=failed_printer.name,
            error=f"Print job failed after all retries and fallbacks. "
                  f"Order: {job.order_id}, Job: {job.job_id[:8]}...",
            requires_attention=True,
        )
        await self._ephemeral.append(error_event)

        logger.error(
            f"[MANAGER] *** MANAGER ALERT ***\n"
            f"  Print failure — all printers exhausted\n"
            f"  Order: {job.order_id}\n"
            f"  Failed printer: {failed_printer.name}\n"
            f"  Job type: {job.job_type.value}\n"
            f"  Job queued for retry when printer recovers"
        )

    async def _alert_no_printer(self, job: PrintJob) -> None:
        """Alert that no printer is available for the requested role."""
        error_event = printer_error(
            terminal_id=self._terminal_id,
            printer_id="none",
            printer_name="none",
            error=f"No printer available for role '{job.target_role}'. "
                  f"Order: {job.order_id}",
            requires_attention=True,
        )
        await self._ephemeral.append(error_event)

        logger.error(
            f"[MANAGER] *** MANAGER ALERT ***\n"
            f"  No printer available for role: {job.target_role}\n"
            f"  Order: {job.order_id}\n"
            f"  Job queued — register a printer for this role"
        )

    # =================================================================
    # QUEUE MANAGEMENT — Pending jobs
    # =================================================================

    def get_queued_jobs(self) -> list[PrintJob]:
        """Get all jobs waiting in the retry queue."""
        return self._print_queue.copy()

    async def retry_queued_jobs(self) -> list[PrintResult]:
        """
        Retry all queued jobs.

        Call this when a printer comes back online or a new
        printer is registered. Tries each queued job again
        through the full submit_job flow.
        """
        if not self._print_queue:
            return []

        results = []
        remaining = []

        logger.info(f"[MANAGER] Retrying {len(self._print_queue)} queued jobs...")

        for job in self._print_queue:
            result = await self.submit_job(job)
            results.append(result)
            if not result.success:
                remaining.append(job)

        self._print_queue = remaining

        succeeded = sum(1 for r in results if r.success)
        logger.info(
            f"[MANAGER] Queue retry complete: {succeeded}/{len(results)} succeeded, "
            f"{len(remaining)} still queued"
        )
        return results

    # =================================================================
    # STATUS SUMMARY
    # =================================================================

    def get_status_summary(self) -> dict:
        """
        Get a complete status summary of the printer system.
        Useful for dashboards, diagnostics, and the hardware layout view.
        """
        printers = []
        for printer_id, printer in self._printers.items():
            config = printer.get_config()
            printers.append({
                "printer_id": printer_id,
                "name": printer.name,
                "type": printer.printer_type.value,
                "role": printer.role,
                "status": printer.status.value,
                "is_ready": printer.is_ready(),
                "location_tag": config.location_tag,
                "fallback_printer_id": config.fallback_printer_id,
                "is_active": config.is_active,
            })

        return {
            "terminal_id": self._terminal_id,
            "total_printers": len(self._printers),
            "ready_printers": sum(1 for p in self._printers.values() if p.is_ready()),
            "queued_jobs": len(self._print_queue),
            "available_roles": sorted(self._custom_roles),
            "printers": printers,
        }
