"""
KINDpos Monetary Precision Utilities

Single rounding policy for all currency math: ROUND_HALF_UP to 2 decimal places.
This matches industry standard (customers expect $X.XX5 to round UP) and
aligns with the frontend's Math.round() / toFixed() behavior.

Usage:
    from app.core.money import money_round
    total = money_round(subtotal * tax_rate)
"""

from decimal import Decimal, ROUND_HALF_UP

_TWO_DP = Decimal("0.01")


def money_round(value: float | int) -> float:
    """Round a monetary value to 2 decimal places using ROUND_HALF_UP.

    Converts through Decimal(str(...)) to avoid IEEE 754 representation
    errors (e.g., Decimal(0.1) != Decimal('0.1')).
    """
    return float(Decimal(str(value)).quantize(_TWO_DP, rounding=ROUND_HALF_UP))
