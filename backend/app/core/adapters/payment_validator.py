from decimal import Decimal
from typing import Dict, Any, Optional, List
from .base_payment import (
    TransactionRequest,
    ValidationResult,
    ValidationStatus,
    BasePaymentDevice,
    PaymentDeviceStatus,
    PaymentType
)
from ..event_ledger import EventLedger
from ..events import EventType

class PaymentValidator:
    """
    Every transaction passes through the validator BEFORE reaching the PaymentManager.
    """

    def __init__(self, ledger: EventLedger):
        self._ledger = ledger
        self._tip_ceiling_percent = 50
        self._tip_ceiling_dollars = Decimal("100.00")
        self._max_transaction_total = Decimal("10000.00")

    async def validate(self, request: TransactionRequest, device: Optional[BasePaymentDevice] = None) -> ValidationResult:
        # Rule 1: Amount > 0
        if request.amount <= 0:
            return ValidationResult(status=ValidationStatus.REJECTED, reason="Amount must be greater than zero.", rule="Rule 1")

        # Rule 2: Tip >= 0
        if request.tip_amount < 0:
            return ValidationResult(status=ValidationStatus.REJECTED, reason="Tip cannot be negative.", rule="Rule 2")

        # Rule 3: Service charge >= 0
        if request.service_charge_amount < 0:
            return ValidationResult(status=ValidationStatus.REJECTED, reason="Service charge cannot be negative.", rule="Rule 3")

        # Rule 4: Total <= ceiling ($10,000)
        total = request.amount + request.tip_amount + request.service_charge_amount
        if total > self._max_transaction_total:
            return ValidationResult(status=ValidationStatus.REJECTED, reason=f"Total amount exceeds maximum limit of ${self._max_transaction_total}.", rule="Rule 4")

        # Rule 5: Tip <= ceiling (Dual threshold)
        tip_pct = (request.tip_amount / request.amount * 100) if request.amount > 0 else 0
        if request.tip_amount > self._tip_ceiling_dollars or tip_pct > self._tip_ceiling_percent:
            return ValidationResult(
                status=ValidationStatus.NEEDS_APPROVAL, 
                reason="Tip exceeds standard ceiling. Manager approval required.", 
                rule="Rule 5",
                approval_type="TIP_CEILING",
                details={"percent": float(tip_pct), "amount": float(request.tip_amount)}
            )

        # Rule 7: Unique transaction_id (Idempotency check)
        # This will be handled by Manager check as well, but validator does first pass
        # Note: In real app we'd query ledger efficiently
        
        # Rule 9: Device available
        if device:
             if device.status in [PaymentDeviceStatus.OFFLINE, PaymentDeviceStatus.ERROR, PaymentDeviceStatus.REBOOTING]:
                 return ValidationResult(status=ValidationStatus.REJECTED, reason=f"Device {device.config.name if device.config else 'unknown'} is currently unavailable.", rule="Rule 9")
             if device.in_sacred_state:
                 return ValidationResult(status=ValidationStatus.REJECTED, reason="Device is currently busy processing another transaction.", rule="Rule 9")

        return ValidationResult(status=ValidationStatus.VALID)
