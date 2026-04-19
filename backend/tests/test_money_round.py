"""
Tests for app.core.money.money_round()

Verifies ROUND_HALF_UP to 2 decimal places via Decimal(str(value)).
"""

import pytest
from app.core.money import money_round


class TestMoneyRound:

    def test_rounds_half_up(self):
        assert money_round(0.005) == 0.01
        assert money_round(0.015) == 0.02
        assert money_round(10.005) == 10.01

    def test_exact_values_unchanged(self):
        assert money_round(1.00) == 1.0
        assert money_round(10.50) == 10.5
        assert money_round(99.99) == 99.99

    def test_zero(self):
        assert money_round(0) == 0.0
        assert money_round(0.0) == 0.0
        assert money_round(0.00) == 0.0

    def test_negative_values(self):
        # ROUND_HALF_UP: -1.005 -> -1.01 (rounds the digit up in magnitude)
        assert money_round(-1.005) == -1.01
        assert money_round(-10.50) == -10.5

    def test_integers(self):
        assert money_round(5) == 5.0
        assert money_round(100) == 100.0

    def test_many_decimals(self):
        assert money_round(10.3333333) == 10.33
        assert money_round(2.6666666) == 2.67

    def test_float_precision_trap(self):
        # IEEE 754: float(2.675) is actually 2.67499999...
        # But Decimal(str(2.675)) == Decimal('2.675'), so ROUND_HALF_UP -> 2.68
        assert money_round(2.675) == 2.68

    def test_large_amounts(self):
        assert money_round(99999.99) == 99999.99
        assert money_round(100000.005) == 100000.01

    def test_very_small(self):
        assert money_round(0.001) == 0.0
        assert money_round(0.009) == 0.01
