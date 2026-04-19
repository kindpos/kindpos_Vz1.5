"""
KINDpos Diagnostic Event Model

Data model for the Entomology Diagnostic System.
Defines diagnostic categories, severities, event structure,
hash computation, and the event code registry.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# ENUMS
# =============================================================================

class DiagnosticCategory(str, Enum):
    """Classification of diagnostic events by system domain."""
    DEVICE = "DEVICE"
    NETWORK = "NETWORK"
    SYSTEM = "SYSTEM"
    PERIPHERAL = "PERIPHERAL"
    RECOVERY = "RECOVERY"


_SEVERITY_ORDER = {
    "INFO": 0,
    "WARNING": 1,
    "ERROR": 2,
    "CRITICAL": 3,
}


class DiagnosticSeverity(str, Enum):
    """Severity levels with defined ordering: INFO < WARNING < ERROR < CRITICAL."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def __lt__(self, other):
        if not isinstance(other, DiagnosticSeverity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] < _SEVERITY_ORDER[other.value]

    def __le__(self, other):
        if not isinstance(other, DiagnosticSeverity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] <= _SEVERITY_ORDER[other.value]

    def __gt__(self, other):
        if not isinstance(other, DiagnosticSeverity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] > _SEVERITY_ORDER[other.value]

    def __ge__(self, other):
        if not isinstance(other, DiagnosticSeverity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] >= _SEVERITY_ORDER[other.value]


# =============================================================================
# CONSTANTS
# =============================================================================

GENESIS_HASH = "KIND_DIAGNOSTIC_GENESIS"
DEFAULT_RETENTION_DAYS = 90

# Event code pattern: PREFIX-NUMBER or PREFIX-WORD (e.g., DEV-001, SYS-HEARTBEAT)
EVENT_CODE_PATTERN = re.compile(r"^[A-Z]+-[A-Z0-9]+$")


# =============================================================================
# HASH COMPUTATION
# =============================================================================

def compute_diagnostic_hash(
    prev_hash: str,
    diagnostic_id: str,
    timestamp: str,
    category: str,
    severity: str,
    source: str,
    event_code: str,
    message: str,
    context: dict,
) -> str:
    """
    Compute SHA-256 hash for a diagnostic event.

    The hash chain is independent from the business event ledger.
    """
    data = (
        prev_hash
        + diagnostic_id
        + timestamp
        + category
        + severity
        + source
        + event_code
        + message
        + json.dumps(context, sort_keys=True)
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# =============================================================================
# DIAGNOSTIC EVENT MODEL
# =============================================================================

class DiagnosticEvent(BaseModel):
    """
    A single diagnostic event record in the Entomology system.

    Forms an independent hash chain for tamper detection,
    separate from the business event ledger.
    """

    # Identity & Linking
    diagnostic_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    terminal_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Classification
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    source: str
    event_code: str
    message: str
    context: dict[str, Any]

    # Integrity
    prev_hash: str
    hash: str

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v):
        if isinstance(v, str) and v not in DiagnosticCategory.__members__:
            raise ValueError(f"Invalid category: {v}")
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v):
        if isinstance(v, str) and v not in DiagnosticSeverity.__members__:
            raise ValueError(f"Invalid severity: {v}")
        return v

    @field_validator("context", mode="before")
    @classmethod
    def validate_context_is_dict(cls, v):
        if not isinstance(v, dict):
            raise ValueError("context must be a dict")
        return v

    @field_validator("event_code", mode="before")
    @classmethod
    def validate_event_code_format(cls, v):
        if not EVENT_CODE_PATTERN.match(v):
            raise ValueError(
                f"event_code '{v}' must match pattern PREFIX-CODE "
                f"(e.g., DEV-001, SYS-HEARTBEAT)"
            )
        return v


# =============================================================================
# EVENT CODE REGISTRY
# =============================================================================

EVENT_CODE_REGISTRY: dict[str, str] = {
    # DEVICE (DEV-)
    "DEV-001": "Payment terminal unreachable (connection refused)",
    "DEV-002": "Payment terminal timeout (no response within threshold)",
    "DEV-003": "Payment terminal offline (status change to OFFLINE)",
    "DEV-004": "Payment terminal unexpected response (malformed XML, unexpected status)",
    "DEV-005": "Payment terminal reboot detected",
    "DEV-006": "Payment terminal status change (any state transition)",

    # NETWORK (NET-)
    "NET-001": "TCP connection timeout to peripheral",
    "NET-002": "TCP connection refused by peripheral",
    "NET-003": "WebSocket connection dropped",
    "NET-004": "WebSocket reconnect attempt",
    "NET-005": "Gateway unreachable",
    "NET-006": "DNS resolution failure",
    "NET-007": "Elevated latency detected (above threshold)",
    "NET-008": "Peer terminal unreachable",

    # SYSTEM (SYS-)
    "SYS-001": "Event ledger write failure",
    "SYS-002": "Event ledger integrity check failure (hash mismatch)",
    "SYS-003": "Disk space warning (threshold exceeded)",
    "SYS-004": "Memory usage warning (threshold exceeded)",
    "SYS-005": "CPU temperature warning",
    "SYS-006": "Application exception (unhandled)",
    "SYS-007": "Scheduled reboot (4 AM cron) — pre-shutdown marker",
    "SYS-HEARTBEAT": "Ambient health snapshot (adaptive interval)",

    # PERIPHERAL (PER-)
    "PER-001": "Printer connection failed",
    "PER-002": "Printer connection refused",
    "PER-003": "Print job timeout",
    "PER-004": "Print queue overflow",
    "PER-005": "Printer status change (online/offline transition)",
    "PER-006": "Printer failover triggered (rerouted to backup)",
    "PER-007": "Cash drawer open failure",

    # RECOVERY (REC-)
    "REC-001": "Auto-retry succeeded (payment, print, connection)",
    "REC-002": "Auto-retry exhausted (max retries, still failed)",
    "REC-003": "Failover activated (switched to backup device)",
    "REC-004": "Device reconnected after outage",
    "REC-005": "Deferred mode entered (payment system operating offline)",
    "REC-006": "Deferred mode exited (back to live processing)",
    "REC-007": "Manual recovery by operator (device restarted, cable reseated, etc.)",
}
