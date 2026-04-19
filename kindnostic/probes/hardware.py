"""Hardware probes — SSD health, clock sync, display resolution."""

import os
import shutil
from datetime import datetime, timezone

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.HIGH

_SSD_FREE_WARN_MB = 500


def probe_ssd_health() -> ProbeResult:
    """Check free space on the data partition. <500MB free = WARN."""
    data_path = os.environ.get("KINDPOS_DATA_PATH", "./data")

    if not os.path.exists(data_path):
        return ProbeResult(
            probe_name="ssd_health",
            category=Category.HIGH,
            status=Status.PASS,
            message="Data path not found — fresh system",
            metadata={"data_path": data_path},
        )

    usage = shutil.disk_usage(data_path)
    free_mb = usage.free / (1024 * 1024)
    total_mb = usage.total / (1024 * 1024)

    if free_mb < _SSD_FREE_WARN_MB:
        return ProbeResult(
            probe_name="ssd_health",
            category=Category.HIGH,
            status=Status.WARN,
            message=f"Low disk space: {free_mb:.0f}MB free of {total_mb:.0f}MB total",
            metadata={
                "free_mb": round(free_mb, 1),
                "total_mb": round(total_mb, 1),
                "threshold_mb": _SSD_FREE_WARN_MB,
            },
        )

    return ProbeResult(
        probe_name="ssd_health",
        category=Category.HIGH,
        status=Status.PASS,
        message=None,
        metadata={
            "free_mb": round(free_mb, 1),
            "total_mb": round(total_mb, 1),
        },
    )


def probe_clock_sync() -> ProbeResult:
    """Check if system clock is plausible. Pi has no RTC — NTP failures cause drift."""
    now = datetime.now(timezone.utc)

    # Simple heuristic: year must be >= 2026 (deployment year)
    # and not absurdly far in the future
    if now.year < 2026:
        return ProbeResult(
            probe_name="clock_sync",
            category=Category.HIGH,
            status=Status.WARN,
            message=f"System clock appears wrong: {now.isoformat()} (year < 2026)",
            metadata={"system_time": now.isoformat(), "reason": "year_too_old"},
        )

    if now.year > 2035:
        return ProbeResult(
            probe_name="clock_sync",
            category=Category.HIGH,
            status=Status.WARN,
            message=f"System clock appears wrong: {now.isoformat()} (year > 2035)",
            metadata={"system_time": now.isoformat(), "reason": "year_too_new"},
        )

    return ProbeResult(
        probe_name="clock_sync",
        category=Category.HIGH,
        status=Status.PASS,
        message=None,
        metadata={"system_time": now.isoformat()},
    )


def probe_display_resolution() -> ProbeResult:
    """Verify framebuffer is 1024x600. Non-Pi environments get a PASS with note."""
    fb_path = "/sys/class/graphics/fb0"

    if not os.path.exists(fb_path):
        return ProbeResult(
            probe_name="display_resolution",
            category=Category.HIGH,
            status=Status.PASS,
            message="No framebuffer device — not running on Pi hardware",
            metadata={"framebuffer": False},
        )

    try:
        with open(os.path.join(fb_path, "virtual_size"), "r") as f:
            size_str = f.read().strip()
        # Format: "1024,600"
        parts = size_str.split(",")
        width, height = int(parts[0]), int(parts[1])
    except (FileNotFoundError, ValueError, IndexError):
        return ProbeResult(
            probe_name="display_resolution",
            category=Category.HIGH,
            status=Status.PASS,
            message="Could not read framebuffer resolution",
            metadata={"framebuffer": True, "readable": False},
        )

    if width != 1024 or height != 600:
        return ProbeResult(
            probe_name="display_resolution",
            category=Category.HIGH,
            status=Status.WARN,
            message=f"Display resolution is {width}x{height}, expected 1024x600",
            metadata={"width": width, "height": height, "expected": "1024x600"},
        )

    return ProbeResult(
        probe_name="display_resolution",
        category=Category.HIGH,
        status=Status.PASS,
        message=None,
        metadata={"width": width, "height": height},
    )
