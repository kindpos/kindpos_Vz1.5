"""
KINDnet Overseer - Printer Discovery Module
=============================================
Nice. Dependable. Yours.

Network scanner for KINDpos site survey and deployment.
Discovers ESC/POS printers on restaurant networks, collects
device information, and prepares printer configurations for
KINDpos terminal import.

Design Philosophy:
    - Brand-agnostic: Works with any ESC/POS printer
    - Protocol-level: No firmware dependencies
    - Event-sourced: All operations logged
    - Local-first: No cloud dependencies

Discovery Methods:
    Phase 3A.1: Port scanning (9100/tcp)
    Phase 3A.2: Device identification (MAC, ESC/POS, HTTP)
    Phase 3A.3: mDNS/Bonjour listener
    Phase 3A.4: SNMP metadata queries
    Phase 3A.5: USB device enumeration

File location: scanner/__init__.py
"""

from .printer_detector import (
    DiscoveredPrinter,
    PrinterDiscovery,
)

__all__ = [
    "DiscoveredPrinter",
    "PrinterDiscovery",
]