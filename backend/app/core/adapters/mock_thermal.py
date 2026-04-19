"""
KINDpos Mock Thermal Printer Adapter
=====================================
Nice. Dependable. Yours.

Simulates a thermal receipt printer for testing and demos.
Implements the full BasePrinter contract without real hardware.
Logs everything so you can see exactly what KINDpos would do.

Use this to validate:
    - Print lifecycle (job in, result out)
    - Double-print prevention (via PrinterManager)
    - Failure/retry scenarios (simulate errors)
    - Rerouting logic (simulate offline)
    - Cash drawer kicks
    - Maintenance reboots

When your real Epson arrives, swap this for EpsonThermalAdapter.
Same interface, same behavior, real hardware.

File location: backend/app/core/adapters/mock_thermal.py
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

logger = logging.getLogger("kindpos.printer.mock_thermal")


class MockThermalPrinter(BasePrinter):
    """
    Mock thermal (receipt) printer for testing.

    Simulates an Epson TM-T88 or similar thermal receipt printer.
    All operations log what would happen with real hardware.

    Features:
        - Configurable failure simulation
        - Print output logged to console and internal buffer
        - Status simulation (online, paper_out, offline, etc.)
        - Tracks all print history for test assertions
    """

    def __init__(self, config: PrinterConfig, fail_mode: Optional[str] = None):
        """
        Initialize the mock thermal printer.

        Args:
            config: PrinterConfig for this printer
            fail_mode: Optional failure simulation
                - None: prints succeed normally
                - "offline": all prints fail with OFFLINE status
                - "paper_out": all prints fail with PAPER_OUT status
                - "jam": all prints fail with JAM status
                - "intermittent": every other print fails
                - "overheat_after": fails after N prints (set via overheat_threshold)
        """
        super().__init__(config)
        self._fail_mode = fail_mode
        self._print_count = 0
        self._print_history: list[dict] = []
        self._drawer_history: list[dict] = []
        self._overheat_threshold = 10  # Fails after this many prints in overheat mode
        self._reboot_count = 0

        logger.info(
            f"[MOCK THERMAL] Initialized: '{config.name}' "
            f"(id={config.printer_id}, role={config.role})"
        )

    # -----------------------------------------------------------------
    # Connection
    # -----------------------------------------------------------------

    def connect(self) -> bool:
        """Simulate connecting to the printer."""
        if self._fail_mode == "offline":
            logger.warning(f"[MOCK THERMAL] '{self.name}' — Connection failed (simulated offline)")
            self._connected = False
            self._status = PrinterStatus.OFFLINE
            return False

        self._connected = True
        self._status = PrinterStatus.ONLINE
        logger.info(f"[MOCK THERMAL] '{self.name}' — Connected successfully")
        return True

    def disconnect(self) -> bool:
        """Simulate disconnecting from the printer."""
        self._connected = False
        self._status = PrinterStatus.OFFLINE
        logger.info(f"[MOCK THERMAL] '{self.name}' — Disconnected")
        return True

    # -----------------------------------------------------------------
    # Core Operations
    # -----------------------------------------------------------------

    def print_job(self, job: PrintJob) -> PrintResult:
        """
        Simulate printing a job.

        Logs the full output that would go to a real thermal printer.
        Respects fail_mode for testing error scenarios.
        """
        self._print_count += 1

        # Check if we should simulate a failure
        failure = self._check_failure()
        if failure:
            logger.warning(
                f"[MOCK THERMAL] '{self.name}' — Print FAILED: {failure} "
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
        self._render_thermal_output(job)

        self._print_history.append({
            "job_id": job.job_id,
            "order_id": job.order_id,
            "job_type": job.job_type.value,
            "success": True,
            "timestamp": datetime.now().isoformat(),
        })

        logger.info(
            f"[MOCK THERMAL] '{self.name}' — Print SUCCESS "
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
        elif self._fail_mode == "paper_out":
            self._status = PrinterStatus.PAPER_OUT
        elif self._fail_mode == "jam":
            self._status = PrinterStatus.JAM
        elif self._fail_mode == "overheat_after" and self._print_count >= self._overheat_threshold:
            self._status = PrinterStatus.OVERHEATED
        elif self._connected:
            self._status = PrinterStatus.ONLINE
        else:
            self._status = PrinterStatus.OFFLINE

        logger.info(f"[MOCK THERMAL] '{self.name}' — Status: {self._status.value}")
        return self._status

    def cut_paper(self, cut_type: Optional[CutType] = None) -> bool:
        """Simulate paper cut."""
        actual_cut = cut_type or self._config.cut_type
        logger.info(f"[MOCK THERMAL] '{self.name}' — Paper cut: {actual_cut.value}")
        return True

    def open_drawer(self) -> bool:
        """Simulate cash drawer kick."""
        if not self._connected:
            logger.warning(f"[MOCK THERMAL] '{self.name}' — Drawer kick FAILED: not connected")
            return False

        self._drawer_history.append({
            "timestamp": datetime.now().isoformat(),
            "success": True,
        })
        logger.info(f"[MOCK THERMAL] '{self.name}' — Cash drawer OPENED")
        return True

    # -----------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------

    def reboot(self) -> bool:
        """Simulate printer reboot."""
        logger.info(f"[MOCK THERMAL] '{self.name}' — Rebooting...")
        self._status = PrinterStatus.REBOOTING

        # Simulate reboot completing
        self._reboot_count += 1
        self._print_count = 0  # Reset overheat counter
        self._status = PrinterStatus.ONLINE
        self._connected = True

        logger.info(
            f"[MOCK THERMAL] '{self.name}' — Reboot complete "
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
            mode: None, "offline", "paper_out", "jam",
                  "intermittent", "overheat_after"
        """
        self._fail_mode = mode
        logger.info(f"[MOCK THERMAL] '{self.name}' — Fail mode set to: {mode}")
        # Update status to reflect new mode
        self.check_status()

    def set_overheat_threshold(self, count: int):
        """Set how many prints before overheat simulation triggers."""
        self._overheat_threshold = count

    def get_print_history(self) -> list[dict]:
        """Return all print attempts for test assertions."""
        return self._print_history.copy()

    def get_drawer_history(self) -> list[dict]:
        """Return all drawer kick attempts for test assertions."""
        return self._drawer_history.copy()

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
        self._drawer_history.clear()
        self._reboot_count = 0
        self._fail_mode = None
        self._status = PrinterStatus.ONLINE
        self._connected = True
        logger.info(f"[MOCK THERMAL] '{self.name}' — Reset to clean state")

    # -----------------------------------------------------------------
    # Internal — Render output
    # -----------------------------------------------------------------

    def _check_failure(self) -> Optional[str]:
        """Check if this print should simulate a failure."""
        if self._fail_mode == "offline":
            return "printer_offline"
        elif self._fail_mode == "paper_out":
            return "paper_out"
        elif self._fail_mode == "jam":
            return "paper_jam"
        elif self._fail_mode == "intermittent" and self._print_count % 2 == 0:
            return "intermittent_failure"
        elif self._fail_mode == "overheat_after" and self._print_count >= self._overheat_threshold:
            self._status = PrinterStatus.OVERHEATED
            return "print_head_overheated"
        return None

    def _render_thermal_output(self, job: PrintJob):
        """
        Render what the thermal printer would actually output.
        Logs to console so you can see the exact ticket.
        """
        width = 48  # Standard 80mm thermal receipt width in characters
        separator = "=" * width
        dash_line = "-" * width

        output_lines = []
        output_lines.append("")
        output_lines.append(separator)
        output_lines.append(f"  MOCK THERMAL OUTPUT — {self.name}")
        output_lines.append(f"  Job: {job.job_id[:8]}... | Order: {job.order_id}")
        output_lines.append(f"  Type: {job.job_type.value} | Context: {job.order_context.value}")

        if job.is_rush:
            output_lines.append(f"  *** RUSH ORDER ***")

        if job.is_reprint:
            output_lines.append(f"  [REPRINT of {job.source_job_id[:8]}...]")

        output_lines.append(separator)

        # Header
        if job.content.header_lines:
            for line in job.content.header_lines:
                output_lines.append(f"  {line}")
            output_lines.append(dash_line)

        # Body
        if job.content.body_lines:
            for line in job.content.body_lines:
                output_lines.append(f"  {line}")
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

        output_lines.append(separator)
        output_lines.append(f"  Server: {job.server_name} | Terminal: {job.terminal_id}")
        output_lines.append(f"  Printed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output_lines.append(f"  Cut: {self._config.cut_type.value}")
        output_lines.append(separator)
        output_lines.append("")

        # Log the full rendered output
        full_output = "\n".join(output_lines)
        logger.info(f"\n{full_output}")
