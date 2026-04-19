"""Dummy probe — always passes. Used to verify the pipeline end-to-end."""

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.LOW


def probe_dummy() -> ProbeResult:
    """A no-op probe that always returns PASS."""
    return ProbeResult(
        probe_name="dummy",
        category=Category.LOW,
        status=Status.PASS,
        message=None,
        metadata={"note": "pipeline verification probe"},
    )
