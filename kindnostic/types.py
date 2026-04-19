"""KINDnostic type definitions — Status, Category, and ProbeResult."""

import dataclasses
from enum import Enum
from typing import Any, Optional


# ─── Category ordering (CRITICAL runs first) ────────────────
_CATEGORY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "LOW": 2,
}


class Status(str, Enum):
    """Probe outcome status."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class Category(str, Enum):
    """Probe severity category. CRITICAL < HIGH < LOW for sort ordering."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    LOW = "LOW"

    def __lt__(self, other):
        if not isinstance(other, Category):
            return NotImplemented
        return _CATEGORY_ORDER[self.value] < _CATEGORY_ORDER[other.value]

    def __le__(self, other):
        if not isinstance(other, Category):
            return NotImplemented
        return _CATEGORY_ORDER[self.value] <= _CATEGORY_ORDER[other.value]

    def __gt__(self, other):
        if not isinstance(other, Category):
            return NotImplemented
        return _CATEGORY_ORDER[self.value] > _CATEGORY_ORDER[other.value]

    def __ge__(self, other):
        if not isinstance(other, Category):
            return NotImplemented
        return _CATEGORY_ORDER[self.value] >= _CATEGORY_ORDER[other.value]


@dataclasses.dataclass(frozen=True)
class ProbeResult:
    """Immutable result returned by every probe function."""
    probe_name: str
    category: Category
    status: Status
    message: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
