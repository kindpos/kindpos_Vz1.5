"""
FastAPI Dependencies

Shared dependencies for API routes.
The Event Ledger is managed here as a singleton.
"""

from typing import AsyncGenerator, Optional
from app.core.event_ledger import EventLedger
from app.core.ephemeral_log import EphemeralLog
from app.core.adapters.printer_manager import PrinterManager
from app.services.diagnostic_collector import DiagnosticCollector
from app.printing.print_dispatcher import PrintDispatcher
from app.config import settings

# Global singleton instances (initialized on startup)
_ledger: EventLedger | None = None
_ephemeral_log: EphemeralLog | None = None
_printer_manager: PrinterManager | None = None
_diagnostic_collector: DiagnosticCollector | None = None
_print_dispatcher: PrintDispatcher | None = None


async def get_ledger() -> EventLedger:
    """Dependency that provides the Event Ledger."""
    if _ledger is None:
        raise RuntimeError("Event Ledger not initialized")
    return _ledger


async def get_ephemeral_log() -> EphemeralLog:
    """Dependency that provides the Ephemeral Log."""
    if _ephemeral_log is None:
        raise RuntimeError("Ephemeral Log not initialized")
    return _ephemeral_log


async def init_ledger() -> EventLedger:
    """Initialize the Event Ledger and Ephemeral Log on startup."""
    global _ledger, _ephemeral_log
    _ledger = EventLedger(settings.database_path)
    await _ledger.connect()
    _ephemeral_log = EphemeralLog(
        settings.database_path.replace("event_ledger.db", "ephemeral_log.db")
    )
    await _ephemeral_log.connect()
    return _ledger


async def close_ledger() -> None:
    """Close the Event Ledger and Ephemeral Log on shutdown."""
    global _ledger, _ephemeral_log
    if _ledger:
        await _ledger.close()
        _ledger = None
    if _ephemeral_log:
        await _ephemeral_log.close()
        _ephemeral_log = None


def get_printer_manager() -> PrinterManager | None:
    """Optional dependency — returns None if PrinterManager not initialized."""
    return _printer_manager


def set_printer_manager(manager: PrinterManager) -> None:
    """Register a PrinterManager instance (called during startup)."""
    global _printer_manager
    _printer_manager = manager


def get_diagnostic_collector() -> Optional[DiagnosticCollector]:
    """Optional dependency — returns None if DiagnosticCollector not initialized."""
    return _diagnostic_collector


def set_diagnostic_collector(collector: DiagnosticCollector) -> None:
    """Register a DiagnosticCollector instance (called during startup)."""
    global _diagnostic_collector
    _diagnostic_collector = collector


def get_print_dispatcher() -> Optional[PrintDispatcher]:
    """Optional dependency — returns None if PrintDispatcher not initialized."""
    return _print_dispatcher


def set_print_dispatcher(dispatcher: PrintDispatcher) -> None:
    """Register a PrintDispatcher instance (called during startup)."""
    global _print_dispatcher
    _print_dispatcher = dispatcher
