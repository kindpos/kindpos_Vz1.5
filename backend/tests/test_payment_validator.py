"""
Tests for PaymentValidator from app.core.adapters.payment_validator.

Verifies all validation rules: amount checks, tip ceilings,
transaction limits, and device availability.
"""

import uuid
import pytest
import pytest_asyncio
from decimal import Decimal

from app.core.adapters.payment_validator import PaymentValidator
from app.core.adapters.base_payment import (
    TransactionRequest,
    ValidationResult,
    ValidationStatus,
    PaymentDeviceStatus,
    PaymentDeviceConfig,
    PaymentDeviceType,
)
from app.core.adapters.mock_payment import MockPaymentDevice
from app.core.event_ledger import EventLedger


def make_request(amount=50.0, tip=0.0, service_charge=0.0):
    return TransactionRequest(
        transaction_id=str(uuid.uuid4()),
        order_id="order-001",
        amount=Decimal(str(amount)),
        tip_amount=Decimal(str(tip)),
        service_charge_amount=Decimal(str(service_charge)),
        terminal_id="T-01",
    )


@pytest_asyncio.fixture
async def validator():
    async with EventLedger(":memory:") as ledger:
        yield PaymentValidator(ledger)


class TestPaymentValidator:

    async def test_valid_transaction(self, validator):
        result = await validator.validate(make_request(amount=50))
        assert result.status == ValidationStatus.VALID

    async def test_zero_amount_rejected(self, validator):
        result = await validator.validate(make_request(amount=0))
        assert result.status == ValidationStatus.REJECTED
        assert result.rule == "Rule 1"

    async def test_negative_amount_rejected(self, validator):
        result = await validator.validate(make_request(amount=-10))
        assert result.status == ValidationStatus.REJECTED

    async def test_negative_tip_rejected(self, validator):
        result = await validator.validate(make_request(amount=50, tip=-5))
        assert result.status == ValidationStatus.REJECTED
        assert result.rule == "Rule 2"

    async def test_negative_service_charge_rejected(self, validator):
        result = await validator.validate(make_request(amount=50, service_charge=-1))
        assert result.status == ValidationStatus.REJECTED
        assert result.rule == "Rule 3"

    async def test_exceeds_max_total(self, validator):
        result = await validator.validate(make_request(amount=9999, tip=2))
        assert result.status == ValidationStatus.REJECTED
        assert result.rule == "Rule 4"

    async def test_tip_over_dollar_ceiling_needs_approval(self, validator):
        result = await validator.validate(make_request(amount=50, tip=101))
        assert result.status == ValidationStatus.NEEDS_APPROVAL
        assert result.rule == "Rule 5"

    async def test_tip_over_percent_ceiling_needs_approval(self, validator):
        # tip=11 on amount=20 is 55%, exceeds 50% ceiling
        result = await validator.validate(make_request(amount=20, tip=11))
        assert result.status == ValidationStatus.NEEDS_APPROVAL
        assert result.rule == "Rule 5"

    async def test_tip_within_both_ceilings_valid(self, validator):
        # tip=40 on amount=100 is 40%, under 50% ceiling and under $100 ceiling
        result = await validator.validate(make_request(amount=100, tip=40))
        assert result.status == ValidationStatus.VALID

    async def test_device_offline_rejected(self, validator):
        device = MockPaymentDevice()
        # Device starts OFFLINE by default
        assert device.status == PaymentDeviceStatus.OFFLINE
        result = await validator.validate(make_request(), device=device)
        assert result.status == ValidationStatus.REJECTED
        assert result.rule == "Rule 9"

    async def test_device_error_rejected(self, validator):
        device = MockPaymentDevice()
        device.set_device_status(PaymentDeviceStatus.ERROR)
        result = await validator.validate(make_request(), device=device)
        assert result.status == ValidationStatus.REJECTED

    async def test_device_in_sacred_state_rejected(self, validator):
        device = MockPaymentDevice()
        device.set_device_status(PaymentDeviceStatus.PROCESSING)
        result = await validator.validate(make_request(), device=device)
        assert result.status == ValidationStatus.REJECTED
        assert result.rule == "Rule 9"

    async def test_no_device_still_valid(self, validator):
        result = await validator.validate(make_request(), device=None)
        assert result.status == ValidationStatus.VALID
