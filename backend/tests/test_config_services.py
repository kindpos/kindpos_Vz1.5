"""
Tests for StoreConfigService — projects store configuration from event streams.
"""

import pytest
import os
from app.core.event_ledger import EventLedger
from app.core.events import create_event, EventType
from app.services.store_config_service import StoreConfigService


@pytest.fixture
async def ledger_and_service(tmp_path):
    """Provide an EventLedger + StoreConfigService backed by a temp DB."""
    db_path = str(tmp_path / "test_config.db")
    async with EventLedger(db_path) as ledger:
        service = StoreConfigService(ledger)
        yield ledger, service


def _store_event(event_type, payload):
    return create_event(
        event_type=event_type,
        terminal_id="terminal-test",
        payload=payload,
    )


class TestStoreConfigService:

    async def test_default_config(self, ledger_and_service):
        ledger, service = ledger_and_service
        config = await service.get_projected_config()
        assert config.info.restaurant_name == "KINDpos"

    async def test_store_info_updated(self, ledger_and_service):
        ledger, service = ledger_and_service

        event = _store_event(EventType.STORE_INFO_UPDATED, {
            'restaurant_name': 'New Name Grill',
            'phone': '555-1234',
        })
        await ledger.append(event)

        config = await service.get_projected_config()
        assert config.info.restaurant_name == 'New Name Grill'
        assert config.info.phone == '555-1234'

    async def test_tax_rule_created(self, ledger_and_service):
        ledger, service = ledger_and_service

        event = _store_event(EventType.STORE_TAX_RULE_CREATED, {
            'tax_rule_id': 'tax-1',
            'name': 'Sales Tax',
            'rate_percent': 8.25,
            'applies_to': 'all',
        })
        await ledger.append(event)

        config = await service.get_projected_config()
        assert len(config.tax_rules) == 1
        assert config.tax_rules[0].name == 'Sales Tax'
        assert config.tax_rules[0].rate_percent == 8.25

    async def test_tax_rule_updated(self, ledger_and_service):
        ledger, service = ledger_and_service

        e1 = _store_event(EventType.STORE_TAX_RULE_CREATED, {
            'tax_rule_id': 'tax-1',
            'name': 'Sales Tax',
            'rate_percent': 8.25,
            'applies_to': 'all',
        })
        e2 = _store_event(EventType.STORE_TAX_RULE_UPDATED, {
            'tax_rule_id': 'tax-1',
            'name': 'Sales Tax',
            'rate_percent': 9.00,
            'applies_to': 'all',
        })
        await ledger.append(e1)
        await ledger.append(e2)

        config = await service.get_projected_config()
        assert len(config.tax_rules) == 1
        assert config.tax_rules[0].rate_percent == 9.00

    async def test_tax_rule_deleted(self, ledger_and_service):
        ledger, service = ledger_and_service

        e1 = _store_event(EventType.STORE_TAX_RULE_CREATED, {
            'tax_rule_id': 'tax-1',
            'name': 'Sales Tax',
            'rate_percent': 8.25,
            'applies_to': 'all',
        })
        e2 = _store_event(EventType.STORE_TAX_RULE_DELETED, {
            'tax_rule_id': 'tax-1',
        })
        await ledger.append(e1)
        await ledger.append(e2)

        config = await service.get_projected_config()
        assert len(config.tax_rules) == 0

    async def test_cc_processing_rate(self, ledger_and_service):
        ledger, service = ledger_and_service

        event = _store_event(EventType.STORE_CC_PROCESSING_RATE_UPDATED, {
            'rate_percent': 3.5,
            'per_transaction_fee': 0.25,
        })
        await ledger.append(event)

        config = await service.get_projected_config()
        assert config.cc_processing.rate_percent == 3.5
        assert config.cc_processing.per_transaction_fee == 0.25

    async def test_multiple_store_info_updates(self, ledger_and_service):
        ledger, service = ledger_and_service

        e1 = _store_event(EventType.STORE_INFO_UPDATED, {
            'restaurant_name': 'First Name',
            'phone': '555-0001',
        })
        e2 = _store_event(EventType.STORE_INFO_UPDATED, {
            'restaurant_name': 'Second Name',
            'city': 'Portland',
        })
        await ledger.append(e1)
        await ledger.append(e2)

        config = await service.get_projected_config()
        # Last update wins for restaurant_name
        assert config.info.restaurant_name == 'Second Name'
        # city from second event
        assert config.info.city == 'Portland'
        # phone from first event should persist (not overwritten by second)
        assert config.info.phone == '555-0001'
