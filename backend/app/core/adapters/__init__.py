"""
KINDpos Adapter Layer
======================
"Keep your hardware. We just swap the brain."

This package contains the universal adapter interfaces and
implementations for all peripheral hardware:

    - Printers (thermal, impact, label)
    - Cash drawers (via printer DK port)
    - Payment devices (future)

Each adapter implements a base contract so the PrinterManager
(and future DeviceManager) can work with any hardware without
knowing the specifics.
"""

from .base_printer import (
    BasePrinter,
    PrinterConfig,
    PrinterType,
    PrinterStatus,
    PrintJob,
    PrintJobContent,
    PrintJobType,
    PrintJobPriority,
    PrintResult,
    OrderContext,
    CutType,
)

from .mock_thermal import MockThermalPrinter
from .mock_impact import MockImpactPrinter
from .printer_manager import PrinterManager

__all__ = [
    # Base contract
    "BasePrinter",
    "PrinterConfig",
    "PrinterType",
    "PrinterStatus",
    "PrintJob",
    "PrintJobContent",
    "PrintJobType",
    "PrintJobPriority",
    "PrintResult",
    "OrderContext",
    "CutType",
    # Mock adapters
    "MockThermalPrinter",
    "MockImpactPrinter",
    # Manager
    "PrinterManager",
]
