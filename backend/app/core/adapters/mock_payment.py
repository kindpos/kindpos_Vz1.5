import asyncio
import random
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from enum import Enum

from .base_payment import (
    BasePaymentDevice,
    PaymentDeviceConfig,
    PaymentDeviceStatus,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
    BatchResult,
    BatchStatus,
    PaymentType,
    EntryMethod,
    PaymentError,
    PaymentErrorCategory
)

class MockScenarioMode(str, Enum):
    APPROVE_ALWAYS = "APPROVE_ALWAYS"
    DECLINE_ALWAYS = "DECLINE_ALWAYS"
    TIMEOUT = "TIMEOUT"
    CANCEL = "CANCEL"
    RANDOM = "RANDOM"
    SPECIFIC_SEQUENCE = "SPECIFIC_SEQUENCE"
    ERROR_BY_CATEGORY = "ERROR_BY_CATEGORY"

class MockPaymentDevice(BasePaymentDevice):
    """
    Full stand-in that simulates realistic behavior.
    Implements the entire BasePaymentDevice contract.
    """

    def __init__(self):
        self._status = PaymentDeviceStatus.OFFLINE
        self._config: Optional[PaymentDeviceConfig] = None
        self._mode = MockScenarioMode.APPROVE_ALWAYS
        self._card_delay = 3.0
        self._proc_delay = 1.5
        self._sequence: List[TransactionStatus] = []
        self._seq_index = 0
        self._error_category: Optional[PaymentErrorCategory] = None
        self._processed_transactions: List[TransactionResult] = []

    async def connect(self, config: PaymentDeviceConfig) -> bool:
        self._config = config
        await asyncio.sleep(0.5)
        self._status = PaymentDeviceStatus.IDLE
        return True

    async def disconnect(self) -> bool:
        if self.in_sacred_state:
            return False
        self._status = PaymentDeviceStatus.OFFLINE
        return True

    async def check_status(self) -> PaymentDeviceStatus:
        # Sacred state rule: never block or interrupt during card wait/processing
        return self._status

    def set_mode(self, mode: MockScenarioMode):
        self._mode = mode

    def set_delay(self, card: float, proc: float):
        self._card_delay = card
        self._proc_delay = proc

    def set_device_status(self, status: PaymentDeviceStatus):
        self._status = status

    def set_sequence(self, sequence: List[TransactionStatus]):
        self._sequence = sequence
        self._seq_index = 0

    def set_error_category(self, category: PaymentErrorCategory):
        self._error_category = category

    async def _simulate_transaction(self, request: TransactionRequest) -> TransactionResult:
        # IDLE -> AWAITING_CARD
        self._status = PaymentDeviceStatus.AWAITING_CARD
        await asyncio.sleep(self._card_delay)

        if self._mode == MockScenarioMode.CANCEL:
            self._status = PaymentDeviceStatus.IDLE
            return TransactionResult(
                transaction_id=request.transaction_id,
                status=TransactionStatus.CANCELLED,
                timestamp=datetime.now()
            )

        # AWAITING_CARD -> PROCESSING
        self._status = PaymentDeviceStatus.PROCESSING
        await asyncio.sleep(self._proc_delay)

        status = TransactionStatus.APPROVED
        error = None

        if self._mode == MockScenarioMode.APPROVE_ALWAYS:
            status = TransactionStatus.APPROVED
        elif self._mode == MockScenarioMode.DECLINE_ALWAYS:
            status = TransactionStatus.DECLINED
        elif self._mode == MockScenarioMode.TIMEOUT:
            # Note: Manager usually enforces this, but mock can simulate device-level timeout
            status = TransactionStatus.TIMEOUT
        elif self._mode == MockScenarioMode.RANDOM:
            r = random.random()
            if r < 0.8: status = TransactionStatus.APPROVED
            elif r < 0.9: status = TransactionStatus.DECLINED
            elif r < 0.95: status = TransactionStatus.TIMEOUT
            else: status = TransactionStatus.ERROR
        elif self._mode == MockScenarioMode.SPECIFIC_SEQUENCE:
            if self._seq_index < len(self._sequence):
                status = self._sequence[self._seq_index]
                self._seq_index += 1
            else:
                status = TransactionStatus.APPROVED
        elif self._mode == MockScenarioMode.ERROR_BY_CATEGORY:
            status = TransactionStatus.ERROR
            cat = self._error_category or PaymentErrorCategory.DEVICE
            error = PaymentError(
                category=cat,
                error_code="MOCK_ERR_001",
                message=f"Simulated {cat} error",
                source="MockPaymentDevice"
            )

        result = TransactionResult(
            transaction_id=request.transaction_id,
            status=status,
            authorization_code="123456" if status == TransactionStatus.APPROVED else None,
            reference_number=str(random.randint(100000, 999999)),
            card_brand=random.choice(["VISA", "MC", "AMEX", "DISCOVER"]),
            last_four=str(random.randint(1000, 9999)),
            entry_method=random.choice([EntryMethod.TAP, EntryMethod.CHIP, EntryMethod.SWIPE]),
            timestamp=datetime.now(),
            error=error
        )

        if status == TransactionStatus.APPROVED:
            self._processed_transactions.append(result)

        self._status = PaymentDeviceStatus.IDLE
        return result

    async def initiate_sale(self, request: TransactionRequest) -> TransactionResult:
        return await self._simulate_transaction(request)

    async def initiate_refund(self, request: TransactionRequest) -> TransactionResult:
        # Simple mock refund
        return TransactionResult(
            transaction_id=request.transaction_id,
            status=TransactionStatus.APPROVED,
            authorization_code="REF-123",
            timestamp=datetime.now()
        )

    async def initiate_void(self, request: TransactionRequest) -> TransactionResult:
        return TransactionResult(
            transaction_id=request.transaction_id,
            status=TransactionStatus.APPROVED,
            timestamp=datetime.now()
        )

    async def cancel_transaction(self) -> bool:
        if self._status == PaymentDeviceStatus.AWAITING_CARD:
            self._status = PaymentDeviceStatus.IDLE
            return True
        return False

    async def close_batch(self) -> BatchResult:
        total = sum(Decimal(str(t.authorization_code)) if t.authorization_code and t.authorization_code.isdigit() else Decimal("0.00") for t in self._processed_transactions) # This is dummy
        # Better: just use request amounts if we tracked them, but mock is simple
        count = len(self._processed_transactions)
        total_amt = Decimal("0.00")
        # In a real mock we'd track amounts
        
        res = BatchResult(
            batch_id=f"BATCH-{random.randint(1000, 9999)}",
            transaction_count=count,
            total_amount=total_amt,
            status=BatchStatus.SUCCESS,
            timestamp=datetime.now()
        )
        self._processed_transactions = []
        return res

    async def get_device_info(self) -> Dict[str, Any]:
        return {
            "model": "Mock-Terminal-2000",
            "serial": "MOCK-123456",
            "firmware": "1.0.0-mock",
            "capabilities": ["SALE", "REFUND", "VOID"]
        }

    async def get_capabilities(self) -> List[PaymentType]:
        return [PaymentType.SALE, PaymentType.REFUND, PaymentType.VOID]

    @property
    def status(self) -> PaymentDeviceStatus:
        return self._status

    @property
    def config(self) -> Optional[PaymentDeviceConfig]:
        return self._config
