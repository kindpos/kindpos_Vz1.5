"""
Tests for the precision gate in EventLedger.

Verifies _check_monetary_precision() identifies non-2dp values,
and that the ledger warns (but does not reject) on bad precision.
"""

import logging
import os
import pytest
from app.core.event_ledger import EventLedger, _check_monetary_precision, _MONETARY_KEYS
from app.core.events import create_event, EventType, payment_initiated


class TestCheckMonetaryPrecision:

    def test_check_monetary_precision_clean(self):
        payload = {"price": 10.00, "amount": 5.50}
        assert _check_monetary_precision(payload) == []

    def test_check_monetary_precision_3dp(self):
        payload = {"price": 10.333}
        result = _check_monetary_precision(payload)
        assert len(result) == 1
        assert "price=10.333" in result[0]

    def test_check_monetary_precision_multiple_bad(self):
        payload = {"price": 1.111, "amount": 2.222}
        result = _check_monetary_precision(payload)
        assert len(result) == 2
        keys_found = {r.split("=")[0] for r in result}
        assert keys_found == {"price", "amount"}

    def test_check_monetary_precision_non_monetary_keys_ignored(self):
        payload = {"name": "test", "quantity": 3.333}
        assert _check_monetary_precision(payload) == []

    def test_check_monetary_precision_integers_ok(self):
        payload = {"price": 10}
        assert _check_monetary_precision(payload) == []

    def test_check_monetary_precision_none_values_ok(self):
        payload = {"price": None}
        assert _check_monetary_precision(payload) == []


class TestLedgerPrecisionWarnings:

    @pytest.fixture
    def tmp_db(self, tmp_path):
        return str(tmp_path / "test_precision.db")

    async def test_ledger_rejects_bad_precision(self, tmp_db):
        event = create_event(
            event_type=EventType.PAYMENT_INITIATED,
            terminal_id="T1",
            payload={
                "order_id": "order-1",
                "payment_id": "p1",
                "amount": 10.333,
                "method": "card",
            },
            correlation_id="order-1",
        )

        async with EventLedger(tmp_db) as ledger:
            with pytest.raises(ValueError, match="non-2dp monetary values"):
                await ledger.append(event)

            # Verify nothing was stored
            count = await ledger.count_events()
            assert count == 0

    async def test_ledger_accepts_valid_precision(self, tmp_db):
        event = create_event(
            event_type=EventType.PAYMENT_INITIATED,
            terminal_id="T1",
            payload={
                "order_id": "order-1",
                "payment_id": "p1",
                "amount": 10.33,
                "method": "card",
            },
            correlation_id="order-1",
        )

        async with EventLedger(tmp_db) as ledger:
            result = await ledger.append(event)
            assert result.sequence_number is not None
            assert result.sequence_number >= 1

            count = await ledger.count_events()
            assert count == 1
