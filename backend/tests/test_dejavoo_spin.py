"""
Tests for DejavooSPInAdapter XML building and response parsing.

Covers:
    - _build_xml with and without params
    - _parse_response for approved, declined, and None root
    - initial status and connect behaviour
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import xml.etree.ElementTree as ET
from decimal import Decimal
import uuid

from app.core.adapters.dejavoo_spin import DejavooSPInAdapter
from app.core.adapters.base_payment import (
    PaymentDeviceConfig,
    PaymentDeviceType,
    PaymentDeviceStatus,
    TransactionRequest,
    TransactionStatus,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def make_config(device_id="deja-01"):
    return PaymentDeviceConfig(
        device_id=device_id,
        name="Dejavoo Test",
        device_type=PaymentDeviceType.SMART_TERMINAL,
        ip_address="192.168.1.100",
        mac_address="AA:BB:CC:DD:EE:FF",
        port=8443,
        protocol="spin",
        processor_id="dejavoo",
        register_id="REG001",
        tpn="TPN001",
        auth_key="AUTH_KEY_123",
    )


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_build_xml_sale():
    """_build_xml('Sale', {...}) produces valid DVSPIn XML with TransType."""
    adapter = DejavooSPInAdapter()
    adapter._config = make_config()

    xml_str = adapter._build_xml("Sale", {
        "PaymentType": "Credit",
        "Amount": "50.00",
        "Tip": "0.00",
        "Frequency": "OneTime",
        "RefId": "test_001",
    })

    root = ET.fromstring(xml_str)
    assert root.tag == "request"
    assert root.findtext("TransType") == "Sale"
    assert root.findtext("Amount") == "50.00"
    assert root.findtext("PaymentType") == "Credit"
    assert root.findtext("Tip") == "0.00"
    assert root.findtext("Frequency") == "OneTime"
    assert root.findtext("RefId") == "test_001"
    # Auth fields
    assert root.findtext("RegisterId") == "REG001"
    assert root.findtext("TPN") == "TPN001"
    assert root.findtext("AuthKey") == "AUTH_KEY_123"
    # Must NOT have old <function> element
    assert root.findtext("function") is None


def test_build_xml_no_params():
    """_build_xml('GetStatus') produces valid XML with TransType."""
    adapter = DejavooSPInAdapter()
    xml_str = adapter._build_xml("GetStatus")

    root = ET.fromstring(xml_str)
    assert root.tag == "request"
    assert root.findtext("TransType") == "GetStatus"
    assert root.findtext("Amount") is None


def test_parse_response_approved():
    """_parse_response with an approved XML root returns APPROVED TransactionResult."""
    adapter = DejavooSPInAdapter()

    root = ET.Element("response")
    ET.SubElement(root, "RespMSG").text = "Approved"
    ET.SubElement(root, "AuthCode").text = "ABC123"
    ET.SubElement(root, "Token").text = "TOK999"
    ET.SubElement(root, "CardBrand").text = "VISA"
    ET.SubElement(root, "LastFour").text = "4242"
    ET.SubElement(root, "EntryMode").text = "Chip"
    ET.SubElement(root, "InvNum").text = "inv001"
    ET.SubElement(root, "ResultCode").text = "000"

    result = adapter._parse_response(root, "inv001")

    assert result.status == TransactionStatus.APPROVED
    assert result.authorization_code == "ABC123"
    assert result.reference_number == "TOK999"
    assert result.card_brand == "VISA"
    assert result.last_four == "4242"
    assert result.transaction_id == "inv001"


def test_parse_response_declined():
    """_parse_response with a declined response returns DECLINED."""
    adapter = DejavooSPInAdapter()

    root = ET.Element("response")
    ET.SubElement(root, "RespMSG").text = "Declined"
    ET.SubElement(root, "InvNum").text = "inv002"

    result = adapter._parse_response(root, "inv002")
    assert result.status == TransactionStatus.DECLINED


def test_parse_response_none():
    """_parse_response(None, ...) returns ERROR TransactionResult."""
    adapter = DejavooSPInAdapter()

    result = adapter._parse_response(None, "inv123")

    assert result.status == TransactionStatus.ERROR
    assert result.transaction_id == "inv123"
    assert result.error is not None
    assert result.error.error_code == "CONN_FAIL"


def test_initial_status_offline():
    """Freshly created adapter starts with OFFLINE status."""
    adapter = DejavooSPInAdapter()
    assert adapter.status == PaymentDeviceStatus.OFFLINE


async def test_connect_sets_status():
    """connect() with mocked HTTP sets status based on _send result."""
    adapter = DejavooSPInAdapter()
    config = make_config()

    # Mock _send to return a "Ready" status response
    ready_root = ET.Element("response")
    ET.SubElement(ready_root, "RespMSG").text = "Ready"

    with patch.object(adapter, "_send", new_callable=AsyncMock, return_value=ready_root):
        connected = await adapter.connect(config)

    assert connected is True
    assert adapter.status == PaymentDeviceStatus.IDLE
    assert adapter.config == config


async def test_connect_offline_when_unreachable():
    """connect() returns False when device is unreachable (_send returns None)."""
    adapter = DejavooSPInAdapter()
    config = make_config()

    with patch.object(adapter, "_send", new_callable=AsyncMock, return_value=None):
        connected = await adapter.connect(config)

    assert connected is False
    assert adapter.status == PaymentDeviceStatus.OFFLINE
