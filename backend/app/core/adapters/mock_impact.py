"""
KINDpos Mock Impact Printer Adapter
=====================================
Nice. Dependable. Yours.

Simulates an impact (dot matrix) kitchen printer for testing and demos.
Implements the full BasePrinter contract without real hardware.

Impact printers differ from thermal:
    - Ribbon-based, not heat-based (survives kitchen heat)
    - Typically louder (the click-click is a feature, not a bug)
    - Usually tear-off, not auto-cut
    - Wider characters for kitchen readability
    - No cash drawer port (usually — that's on the receipt printer)

When your real Epson TM-U220 arrives, swap this for EpsonImpactAdapter.
Same interface, same behavior, real hardware.

File location: backend/app/core/adapters/mock_impact.py
"""

import logging
from datetime import datetime
from typing import Optional

from .base_printer import (
    BasePrinter,
    PrinterConfig,
    PrinterType,
    PrinterStatus,
    PrintJob,
    PrintResult,
    PrintJobType,
    CutType,
    PrintJobPriority,
)

logger = logging.getLogger("kindpos.printer.mock_impact")


class MockImpactPrinter(BasePrinter):
    """
    Mock impact (kitchen) printer for testing.

    Simulates an Epson TM-U220 or similar dot matrix kitchen printer.
    All operations log what would happen with real hardware.

    Key differences from thermal mock:
        - Default cut type is TEAR (no auto-cutter)
        - Wider character rendering for kitchen readability
        - No cash drawer support (returns False)
        - RUSH orders render with extra visual emphasis
    """

    def __init__(self, config: PrinterConfig, fail_mode: Optional[str] = None):
        """
        Initialize the mock impact printer.

        Args:
            config: PrinterConfig for this printer
            fail_mode: Optional failure simulation
                - None: prints succeed normally
                - "offline": all prints fail with OFFLINE status
                - "ribbon_out": all prints fail (impact equivalent of paper_out)
                - "jam": all prints fail with JAM status
                - "intermittent": every other print fails
        """
        super().__init__(config)
        self._fail_mode = fail_mode
        self._print_count = 0
        self._print_history: list[dict] = []
        self._reboot_count = 0

        # Impact printers default to tear, not cut
        if self._config.cut_type == CutType.FULL:
            self._config.cut_type = CutType.TEAR

        logger.info(
            f"[MOCK IMPACT] Initialized: '{config.name}' "
            f"(id={config.printer_id}, role={config.role})"
        )

    # -----------------------------------------------------------------
    # Connection
    # -----------------------------------------------------------------

    def connect(self) -> bool:
        """Simulate connecting to the printer."""
        if self._fail_mode == "offline":
            logger.warning(f"[MOCK IMPACT] '{self.name}' — Connection failed (simulated offline)")
            self._connected = False
            self._status = PrinterStatus.OFFLINE
            return False

        self._connected = True
        self._status = PrinterStatus.ONLINE
        logger.info(f"[MOCK IMPACT] '{self.name}' — Connected successfully")
        return True

    def disconnect(self) -> bool:
        """Simulate disconnecting from the printer."""
        self._connected = False
        self._status = PrinterStatus.OFFLINE
        logger.info(f"[MOCK IMPACT] '{self.name}' — Disconnected")
        return True

    # -----------------------------------------------------------------
    # Core Operations
    # -----------------------------------------------------------------

    def print_job(self, job: PrintJob) -> PrintResult:
        """
        Simulate printing a kitchen ticket.

        Renders with wider characters and kitchen-specific formatting.
        RUSH orders get extra visual emphasis (big text, border).
        """
        self._print_count += 1

        # Check if we should simulate a failure
        failure = self._check_failure()
        if failure:
            logger.warning(
                f"[MOCK IMPACT] '{self.name}' — Print FAILED: {failure} "
                f"(job_id={job.job_id[:8]}..., order={job.order_id})"
            )
            self._print_history.append({
                "job_id": job.job_id,
                "order_id": job.order_id,
                "success": False,
                "error": failure,
                "timestamp": datetime.now().isoformat(),
            })
            return PrintResult(
                success=False,
                job_id=job.job_id,
                printer_id=self.printer_id,
                message=f"Print failed: {failure}",
                error_code=failure,
            )

        # Simulate successful print
        self._render_impact_output(job)

        self._print_history.append({
            "job_id": job.job_id,
            "order_id": job.order_id,
            "job_type": job.job_type.value,
            "success": True,
            "timestamp": datetime.now().isoformat(),
        })

        logger.info(
            f"[MOCK IMPACT] '{self.name}' — Print SUCCESS "
            f"(job_id={job.job_id[:8]}..., order={job.order_id}, "
            f"type={job.job_type.value})"
        )

        return PrintResult(
            success=True,
            job_id=job.job_id,
            printer_id=self.printer_id,
            message="Printed successfully",
        )

    def check_status(self) -> PrinterStatus:
        """Simulate checking printer status."""
        if self._fail_mode == "offline":
            self._status = PrinterStatus.OFFLINE
        elif self._fail_mode == "ribbon_out":
            self._status = PrinterStatus.PAPER_OUT  # Ribbon out maps to paper_out status
        elif self._fail_mode == "jam":
            self._status = PrinterStatus.JAM
        elif self._connected:
            self._status = PrinterStatus.ONLINE
        else:
            self._status = PrinterStatus.OFFLINE

        logger.info(f"[MOCK IMPACT] '{self.name}' — Status: {self._status.value}")
        return self._status

    def cut_paper(self, cut_type: Optional[CutType] = None) -> bool:
        """
        Impact printers typically tear, not cut.
        This is mostly a no-op but logs the action.
        """
        actual_cut = cut_type or self._config.cut_type
        if actual_cut == CutType.TEAR:
            logger.info(f"[MOCK IMPACT] '{self.name}' — Tear point (no auto-cut)")
        else:
            logger.info(f"[MOCK IMPACT] '{self.name}' — Cut: {actual_cut.value}")
        return True

    def open_drawer(self) -> bool:
        """
        Impact/kitchen printers typically don't have a cash drawer.
        Returns False — drawer kicks go through the receipt printer.
        """
        logger.warning(
            f"[MOCK IMPACT] '{self.name}' — Drawer kick requested but "
            f"impact/kitchen printers typically don't have a drawer connected. "
            f"Route drawer kicks to a receipt printer."
        )
        return False

    # -----------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------

    def reboot(self) -> bool:
        """Simulate printer reboot."""
        logger.info(f"[MOCK IMPACT] '{self.name}' — Rebooting...")
        self._status = PrinterStatus.REBOOTING

        # Simulate reboot completing
        self._reboot_count += 1
        self._status = PrinterStatus.ONLINE
        self._connected = True

        logger.info(
            f"[MOCK IMPACT] '{self.name}' — Reboot complete "
            f"(total reboots: {self._reboot_count})"
        )
        return True

    # -----------------------------------------------------------------
    # Simulation Controls — For testing
    # -----------------------------------------------------------------

    def set_fail_mode(self, mode: Optional[str]):
        """
        Change the failure simulation mode.

        Args:
            mode: None, "offline", "ribbon_out", "jam", "intermittent"
        """
        self._fail_mode = mode
        logger.info(f"[MOCK IMPACT] '{self.name}' — Fail mode set to: {mode}")
        self.check_status()

    def get_print_history(self) -> list[dict]:
        """Return all print attempts for test assertions."""
        return self._print_history.copy()

    def get_print_count(self) -> int:
        """Total number of print attempts (success + failure)."""
        return self._print_count

    def get_successful_prints(self) -> int:
        """Number of successful prints."""
        return sum(1 for p in self._print_history if p["success"])

    def get_failed_prints(self) -> int:
        """Number of failed prints."""
        return sum(1 for p in self._print_history if not p["success"])

    def reset(self):
        """Reset all counters and history. Fresh start."""
        self._print_count = 0
        self._print_history.clear()
        self._reboot_count = 0
        self._fail_mode = None
        self._status = PrinterStatus.ONLINE
        self._connected = True
        logger.info(f"[MOCK IMPACT] '{self.name}' — Reset to clean state")

    # -----------------------------------------------------------------
    # Internal — Render output
    # -----------------------------------------------------------------

    def _check_failure(self) -> Optional[str]:
        """Check if this print should simulate a failure."""
        if self._fail_mode == "offline":
            return "printer_offline"
        elif self._fail_mode == "ribbon_out":
            return "ribbon_out"
        elif self._fail_mode == "jam":
            return "paper_jam"
        elif self._fail_mode == "intermittent" and self._print_count % 2 == 0:
            return "intermittent_failure"
        return None

    def _render_impact_output(self, job: PrintJob):
        """
        Render what the impact printer would actually output.

        Impact printers use wider characters for kitchen readability.
        RUSH orders get heavy visual emphasis — the kitchen needs
        to see it immediately.
        """
        width = 42  # Standard impact printer width in characters
        separator = "#" * width
        dash_line = "-" * width

        output_lines = []
        output_lines.append("")
        output_lines.append(separator)
        output_lines.append(f"  MOCK IMPACT OUTPUT — {self.name}")
        output_lines.append(f"  Job: {job.job_id[:8]}... | Order: {job.order_id}")

        if job.is_rush:
            output_lines.append(separator)
            output_lines.append(f"  !!! RUSH  RUSH  RUSH  RUSH !!!")
            output_lines.append(separator)

        if job.is_reprint:
            output_lines.append(f"  ** REPRINT ** (orig: {job.source_job_id[:8]}...)")

        output_lines.append(dash_line)

        # Header — table, server, order context
        if job.content.header_lines:
            for line in job.content.header_lines:
                output_lines.append(f"  {line.upper()}")  # Kitchen tickets are uppercase
            output_lines.append(dash_line)

        # Body — items and modifiers (the important part)
        if job.content.body_lines:
            for line in job.content.body_lines:
                output_lines.append(f"  {line.upper()}")  # Kitchen readability
            output_lines.append(dash_line)

        # Footer
        if job.content.footer_lines:
            for line in job.content.footer_lines:
                output_lines.append(f"  {line}")

        # Metadata
        if job.content.metadata:
            output_lines.append(dash_line)
            for key, value in job.content.metadata.items():
                output_lines.append(f"  {key}: {value}")

        output_lines.append(dash_line)
        output_lines.append(f"  Server: {job.server_name}")
        output_lines.append(f"  {datetime.now().strftime('%H:%M:%S')}")
        output_lines.append(f"  [TEAR HERE]")
        output_lines.append(separator)
        output_lines.append("")

        # Log the full rendered output
        full_output = "\n".join(output_lines)
        logger.info(f"\n{full_output}")
