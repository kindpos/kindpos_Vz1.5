from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from decimal import Decimal
import uuid

# 1.1 PaymentDeviceType
class PaymentDeviceType(str, Enum):
    SMART_TERMINAL = "SMART_TERMINAL"
    PIN_PAD = "PIN_PAD"
    MOBILE = "MOBILE"

# 1.2 PaymentDeviceStatus
class PaymentDeviceStatus(str, Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    DEFERRED_MODE = "DEFERRED_MODE"
    IDLE = "IDLE"
    AWAITING_CARD = "AWAITING_CARD"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    REBOOTING = "REBOOTING"

# 1.3 PaymentDeviceConfig
class PaymentDeviceConfig(BaseModel):
    device_id: str
    name: str
    device_type: PaymentDeviceType
    ip_address: str
    mac_address: str
    port: int = 9000
    protocol: str  # 'spin', 'stripe', or 'mock'
    location_notes: Optional[str] = None
    enabled: bool = True
    processor_id: str
    register_id: Optional[str] = None  # SPIn Register ID for Dejavoo devices
    tpn: Optional[str] = None          # SPIn Terminal Processing Number
    auth_key: Optional[str] = None     # SPIn Auth Key

# 1.4 TransactionRequest
class PaymentType(str, Enum):
    SALE = "SALE"
    REFUND = "REFUND"
    VOID = "VOID"
    AUTH_ONLY = "AUTH_ONLY"

class SplitType(str, Enum):
    EVEN = "EVEN"
    BY_SEAT = "BY_SEAT"
    BY_AMOUNT = "BY_AMOUNT"
    BY_ITEM = "BY_ITEM"

# 1.5 SplitInfo
class SplitInfo(BaseModel):
    split_type: SplitType
    part_number: int
    total_parts: int
    seat_id: Optional[str] = None
    item_ids: Optional[List[str]] = None

class TransactionRequest(BaseModel):
    transaction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    amount: Decimal
    tip_amount: Decimal = Decimal("0.00")
    service_charge_amount: Decimal = Decimal("0.00")
    payment_type: PaymentType = PaymentType.SALE
    terminal_id: str
    server_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    split_info: Optional[SplitInfo] = None
    seat_numbers: Optional[List[int]] = None

    @field_validator("amount", "tip_amount", "service_charge_amount", mode="before")
    @classmethod
    def _coerce_via_str(cls, v):
        """Avoid IEEE 754 artifacts: Decimal(str(10.10)) not Decimal(10.10)."""
        if isinstance(v, float):
            return Decimal(str(v))
        return v

# 1.6 TransactionResult
class TransactionStatus(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"

class EntryMethod(str, Enum):
    TAP = "TAP"
    CHIP = "CHIP"
    SWIPE = "SWIPE"
    MANUAL = "MANUAL"

# 1.8 PaymentErrorCategory & PaymentError
class PaymentErrorCategory(str, Enum):
    DEVICE = "DEVICE"
    NETWORK = "NETWORK"
    PROCESSOR = "PROCESSOR"
    SYSTEM = "SYSTEM"

class PaymentError(BaseModel):
    category: PaymentErrorCategory
    error_code: str
    message: str
    source: str
    recoverable: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)

class TransactionResult(BaseModel):
    transaction_id: str
    status: TransactionStatus
    authorization_code: Optional[str] = None
    reference_number: Optional[str] = None
    card_brand: Optional[str] = None
    last_four: Optional[str] = None
    entry_method: Optional[EntryMethod] = None
    processor_response_code: Optional[str] = None
    processor_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[PaymentError] = None

# 1.9 ValidationResult
class ValidationStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    REJECTED = "REJECTED"

class ValidationResult(BaseModel):
    status: ValidationStatus
    reason: Optional[str] = None
    rule: Optional[str] = None
    approval_type: Optional[str] = None # TIP_CEILING, DEFERRED_LIMIT, AMOUNT_CEILING
    details: Dict[str, Any] = {}

# 1.10 ProcessorProfile
class ProcessorProfile(BaseModel):
    processor_id: str
    processor_name: str
    supports_deferred: bool = True
    tip_adjust_max_percent: int = 50
    tip_adjust_window_hours: int = 24
    auto_batch_time: Optional[str] = None
    refund_requires_card: bool = False
    void_window_hours: int = 24
    settlement_delay_days: int = 2

# 1.11 BatchResult
class BatchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"

class BatchResult(BaseModel):
    batch_id: str
    transaction_count: int
    total_amount: Decimal
    deferred_count: int = 0
    deferred_amount: Decimal = Decimal("0.00")
    status: BatchStatus
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[PaymentError] = None

# Section 2: BasePaymentDevice (Abstract Contract)
from abc import ABC, abstractmethod

class BasePaymentDevice(ABC):
    """
    The interface every adapter must implement.
    Adapters are translators ONLY.
    """

    @abstractmethod
    async def connect(self, config: PaymentDeviceConfig) -> bool:
        """Establish connection to device using config."""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """Clean shutdown. BLOCKED during sacred states."""
        pass

    @abstractmethod
    async def check_status(self) -> PaymentDeviceStatus:
        """Health check. Never blocks during sacred states."""
        pass

    @abstractmethod
    async def initiate_sale(self, request: TransactionRequest) -> TransactionResult:
        """Core sale."""
        pass

    @abstractmethod
    async def initiate_refund(self, request: TransactionRequest) -> TransactionResult:
        """Refund against previous transaction."""
        pass

    @abstractmethod
    async def initiate_void(self, request: TransactionRequest) -> TransactionResult:
        """Void unsettled transaction."""
        pass

    @abstractmethod
    async def cancel_transaction(self) -> bool:
        """Abort during AWAITING_CARD only."""
        pass

    @abstractmethod
    async def close_batch(self) -> BatchResult:
        """Settle all authorized transactions."""
        pass

    @abstractmethod
    async def get_device_info(self) -> Dict[str, Any]:
        """Model, serial, firmware, capabilities."""
        pass

    @abstractmethod
    async def get_capabilities(self) -> List[PaymentType]:
        """Declares supported transaction types."""
        pass

    @property
    @abstractmethod
    def status(self) -> PaymentDeviceStatus:
        """Current status (read-only)."""
        pass

    @property
    @abstractmethod
    def config(self) -> Optional[PaymentDeviceConfig]:
        """Current config."""
        pass

    @property
    def in_sacred_state(self) -> bool:
        """True if AWAITING_CARD or PROCESSING."""
        return self.status in [PaymentDeviceStatus.AWAITING_CARD, PaymentDeviceStatus.PROCESSING]

    # Phase 2 signatures
    async def adjust_tip(self, transaction_id: str, tip_amount: Decimal) -> TransactionResult:
        """Adjust tip on existing transaction."""
        raise NotImplementedError("Tip adjustment is Phase 2.")
