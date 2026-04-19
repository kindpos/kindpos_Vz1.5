import asyncio
import sys
import os
from decimal import Decimal
from datetime import datetime

# Setup path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.core.adapters.base_payment import (
    TransactionRequest, 
    PaymentDeviceConfig, 
    PaymentDeviceType,
    TransactionStatus
)
from app.core.adapters.mock_payment import MockPaymentDevice, MockScenarioMode
from app.core.adapters.payment_manager import PaymentManager
from app.core.event_ledger import EventLedger

async def run_test():
    print("--- Payment System Integration Test ---")
    
    # 1. Setup Ledger
    ledger_path = "./data/test_payment_ledger.db"
    if os.path.exists(ledger_path):
        os.remove(ledger_path)
    
    async with EventLedger(ledger_path) as ledger:
        manager = PaymentManager(ledger, "term-01")
        
        # 2. Setup Mock Device
        mock = MockPaymentDevice()
        config = PaymentDeviceConfig(
            device_id="mock-01",
            name="Test Mock Reader",
            device_type=PaymentDeviceType.SMART_TERMINAL,
            ip_address="127.0.0.1",
            mac_address="00:00:00:00:00:01",
            protocol="mock",
            processor_id="test_proc"
        )
        await mock.connect(config)
        manager.register_device(mock)
        manager.map_terminal_to_device("term-01", "mock-01")
        
        # 3. Test Successful Sale
        print("\nTest 1: Successful Sale")
        request = TransactionRequest(
            order_id="ORD-123",
            amount=Decimal("10.00"),
            terminal_id="term-01",
            server_id="serv-01"
        )
        mock.set_delay(0.1, 0.1)
        result = await manager.initiate_sale(request)
        print(f"Result Status: {result.status}")
        assert result.status == TransactionStatus.APPROVED
        
        # 4. Test Idempotency
        print("\nTest 2: Idempotency (Repeat Sale)")
        result2 = await manager.initiate_sale(request)
        print(f"Result 2 Status: {result2.status}")
        assert result2.status == TransactionStatus.APPROVED
        assert result2.authorization_code == result.authorization_code
        
        # 5. Test Decline
        print("\nTest 3: Declined Sale")
        mock.set_mode(MockScenarioMode.DECLINE_ALWAYS)
        request3 = TransactionRequest(
            order_id="ORD-124",
            amount=Decimal("20.00"),
            terminal_id="term-01",
            server_id="serv-01"
        )
        result3 = await manager.initiate_sale(request3)
        print(f"Result 3 Status: {result3.status}")
        assert result3.status == TransactionStatus.DECLINED

    print("\n--- All Tests Passed ---")

if __name__ == "__main__":
    asyncio.run(run_test())
