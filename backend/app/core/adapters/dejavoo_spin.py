import asyncio
import xml.etree.ElementTree as ET
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal

import httpx

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

logger = logging.getLogger("kindpos.payment.dejavoo")


class DejavooSPInAdapter(BasePaymentDevice):
    """
    Dejavoo SPIn adapter — plain HTTP GET over LAN.

    Protocol:
        GET http://{ip}:{port}/spin/cgi.html?TerminalTransaction={url_encoded_xml}

    The XML includes RegisterId, AuthKey, and TPN inside the body.
    Response is XML wrapped in <xmp> tags.
    """

    def __init__(self):
        self._status = PaymentDeviceStatus.OFFLINE
        self._config: Optional[PaymentDeviceConfig] = None

    @property
    def status(self) -> PaymentDeviceStatus:
        return self._status

    @property
    def config(self) -> Optional[PaymentDeviceConfig]:
        return self._config

    async def connect(self, config: PaymentDeviceConfig) -> bool:
        self._config = config
        status = await self.check_status()
        return status != PaymentDeviceStatus.OFFLINE

    async def disconnect(self) -> bool:
        self._status = PaymentDeviceStatus.OFFLINE
        return True

    # ── Transactions ──────────────────────────────────────────────────────────

    async def check_status(self) -> PaymentDeviceStatus:
        if self.in_sacred_state:
            return self._status

        try:
            xml = self._build_xml("GetStatus")
            response = await self._send(xml, timeout=3.0)
            if response is not None:
                resp_msg = response.findtext("RespMSG") or ""
                if "Approved" in resp_msg or resp_msg == "Ready":
                    self._status = PaymentDeviceStatus.IDLE
                elif "Busy" in resp_msg:
                    if not self.in_sacred_state:
                        self._status = PaymentDeviceStatus.PROCESSING
                else:
                    # Any XML response means the device is reachable
                    self._status = PaymentDeviceStatus.ONLINE
            else:
                self._status = PaymentDeviceStatus.OFFLINE
        except Exception as e:
            logger.error(f"Dejavoo health check failed: {e}")
            self._status = PaymentDeviceStatus.OFFLINE

        return self._status

    async def initiate_sale(self, request: TransactionRequest) -> TransactionResult:
        xml = self._build_xml("Sale", {
            "PaymentType": "Credit",
            "Amount": f"{request.amount:.2f}",
            "Tip": f"{request.tip_amount:.2f}",
            "Frequency": "OneTime",
            "RefId": request.transaction_id,
            "ConfirmAmount": "No",
            "PrintReceipt": "No",
            "SigCapture": "No",
        })

        self._status = PaymentDeviceStatus.AWAITING_CARD
        try:
            root = await self._send(xml)
            return self._parse_response(root, request.transaction_id)
        finally:
            self._status = PaymentDeviceStatus.IDLE

    async def initiate_refund(self, request: TransactionRequest) -> TransactionResult:
        xml = self._build_xml("Return", {
            "PaymentType": "Credit",
            "Amount": f"{request.amount:.2f}",
            "Frequency": "OneTime",
            "RefId": request.transaction_id,
            "ConfirmAmount": "No",
            "PrintReceipt": "No",
            "SigCapture": "No",
        })
        try:
            root = await self._send(xml)
            return self._parse_response(root, request.transaction_id)
        finally:
            self._status = PaymentDeviceStatus.IDLE

    async def initiate_void(self, request: TransactionRequest) -> TransactionResult:
        xml = self._build_xml("Void", {
            "RefId": request.transaction_id,
            "PrintReceipt": "No",
        })
        try:
            root = await self._send(xml)
            return self._parse_response(root, request.transaction_id)
        finally:
            self._status = PaymentDeviceStatus.IDLE

    async def cancel_transaction(self) -> bool:
        xml = self._build_xml("Cancel")
        try:
            root = await self._send(xml, timeout=10.0)
            if root is not None:
                msg = root.findtext("Message") or root.findtext("RespMSG") or ""
                return "Cancel" in msg
        except Exception:
            pass
        return False

    async def adjust_tip(self, transaction_id: str, tip_amount: Decimal) -> TransactionResult:
        xml = self._build_xml("TipAdjust", {
            "RefId": transaction_id,
            "Tip": f"{tip_amount:.2f}",
        })
        try:
            root = await self._send(xml)
            return self._parse_response(root, transaction_id)
        except Exception as e:
            logger.error(f"Tip adjust failed: {e}")
            return TransactionResult(
                transaction_id=transaction_id,
                status=TransactionStatus.ERROR,
                error=PaymentError(
                    category=PaymentErrorCategory.DEVICE,
                    error_code="TIP_ADJ_ERR",
                    message=str(e),
                    source="DejavooSPInAdapter",
                ),
            )

    async def close_batch(self) -> BatchResult:
        xml = self._build_xml("BatchClose")
        try:
            root = await self._send(xml)
            if root is not None:
                resp_msg = root.findtext("RespMSG") or ""
                success = "Approved" in resp_msg
                return BatchResult(
                    batch_id=root.findtext("BatchID") or "UNKNOWN",
                    transaction_count=int(root.findtext("BatchCount") or "0"),
                    total_amount=Decimal(root.findtext("BatchAmount") or "0.00"),
                    status=BatchStatus.SUCCESS if success else BatchStatus.FAILED,
                    timestamp=datetime.now()
                )
        except Exception as e:
            pass
        return BatchResult(
            batch_id="ERROR",
            transaction_count=0,
            total_amount=Decimal("0.00"),
            status=BatchStatus.FAILED,
            error=PaymentError(
                category=PaymentErrorCategory.SYSTEM,
                error_code="BATCH_ERR",
                message="Batch close failed",
                source="DejavooSPInAdapter"
            )
        )

    async def get_device_info(self) -> Dict[str, Any]:
        return {
            "adapter": "DejavooSPInAdapter",
            "protocol": "SPIn HTTP GET (LAN)",
            "config": self._config.dict() if self._config else None
        }

    async def get_capabilities(self) -> List[PaymentType]:
        return [PaymentType.SALE, PaymentType.REFUND, PaymentType.VOID]

    # ── Protocol layer ────────────────────────────────────────────────────────

    def _build_xml(self, trans_type: str, params: Dict[str, str] = None) -> str:
        """Build DVSPIn XML with TransType and auth fields."""
        parts = ["<request>"]

        # Transaction params first (matches working first_transaction.py order)
        if params:
            for k, v in params.items():
                parts.append(f"<{k}>{v}</{k}>")

        # TransType (not <function>)
        parts.append(f"<TransType>{trans_type}</TransType>")

        # Auth fields
        if self._config:
            if self._config.register_id:
                parts.append(f"<RegisterId>{self._config.register_id}</RegisterId>")
            tpn = getattr(self._config, 'tpn', None) or ''
            if tpn:
                parts.append(f"<TPN>{tpn}</TPN>")
            auth_key = getattr(self._config, 'auth_key', None) or ''
            if auth_key:
                parts.append(f"<AuthKey>{auth_key}</AuthKey>")

        parts.append("</request>")
        return "".join(parts)

    async def _send(self, xml_body: str, timeout: float = None) -> Optional[ET.Element]:
        """
        Send SPIn request as HTTP GET:
        GET http://{ip}:{port}/spin/cgi.html?TerminalTransaction={url_encoded_xml}

        Returns parsed XML Element (the <response> inside <xmp>), or None.
        """
        if not self._config:
            return None

        encoded = urllib.parse.quote(xml_body, safe='')
        url = f"http://{self._config.ip_address}:{self._config.port}/spin/cgi.html?TerminalTransaction={encoded}"

        try:
            logger.debug(f"SPIn → GET {self._config.ip_address}:{self._config.port} : {xml_body}")
            print(f"  SPIn → {self._config.ip_address}:{self._config.port}")
            print(f"  SPIn XML: {xml_body}")

            request_timeout = timeout or 120.0
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                resp = await client.get(url)
            resp.raise_for_status()

            # Handle response as bytes if no charset detected
            try:
                body = resp.text.strip()
            except Exception:
                body = resp.content.decode('utf-8', errors='replace').strip()

            logger.debug(f"SPIn ← {body}")
            print(f"  SPIn ← {resp.status_code} ({len(body)} bytes)")

            # Strip <xmp>...</xmp> wrapper if present
            if "<xmp>" in body:
                body = body.split("<xmp>", 1)[-1]
            if "</xmp>" in body:
                body = body.split("</xmp>", 1)[0]

            body = body.strip()
            if not body:
                print(f"  SPIn ← empty body after stripping xmp")
                return None

            # URL-decode any encoded chars in the response
            body = urllib.parse.unquote(body)
            print(f"  SPIn resp:  {body}")

            return ET.fromstring(body)

        except Exception as e:
            logger.error(f"SPIn request failed: {type(e).__name__}: {e}")
            print(f"  SPIn request failed: {type(e).__name__}: {e}")
            return None

    def _parse_response(self, root: Optional[ET.Element], expected_inv: str) -> TransactionResult:
        if root is None:
            return TransactionResult(
                transaction_id=expected_inv,
                status=TransactionStatus.ERROR,
                error=PaymentError(
                    category=PaymentErrorCategory.NETWORK,
                    error_code="CONN_FAIL",
                    message="Could not reach payment device",
                    source="DejavooSPInAdapter"
                )
            )

        try:
            resp_msg = root.findtext("RespMSG") or root.findtext("Message") or ""
            # URL-decode response message
            resp_msg = urllib.parse.unquote(resp_msg)

            result_code = root.findtext("ResultCode") or ""
            status = TransactionStatus.ERROR
            if result_code == "0" or "Approved" in resp_msg or "Approval" in resp_msg:
                status = TransactionStatus.APPROVED
            elif "Declined" in resp_msg:
                status = TransactionStatus.DECLINED
            elif "Cancel" in resp_msg:
                status = TransactionStatus.CANCELLED

            entry_map = {
                "Swipe": EntryMethod.SWIPE,
                "Chip": EntryMethod.CHIP,
                "Contactless": EntryMethod.TAP,
                "Manual": EntryMethod.MANUAL,
            }
            entry_mode = entry_map.get(root.findtext("EntryMode") or "", EntryMethod.TAP)

            # Card details may be in ExtData (e.g. "CardType=VISA,AcntLast4=0049,Amount=0.01")
            card_brand = root.findtext("CardBrand") or root.findtext("CardType") or ""
            last_four = root.findtext("LastFour") or root.findtext("AcntLast4") or ""
            ext_data = root.findtext("ExtData") or ""
            if ext_data:
                for pair in ext_data.split(","):
                    pair = pair.strip()
                    if pair.startswith("CardType=") and not card_brand:
                        card_brand = pair.split("=", 1)[1]
                    elif pair.startswith("AcntLast4=") and not last_four:
                        last_four = pair.split("=", 1)[1]

            return TransactionResult(
                transaction_id=root.findtext("RefId") or root.findtext("InvNum") or expected_inv,
                status=status,
                authorization_code=root.findtext("AuthCode"),
                reference_number=root.findtext("Token"),
                card_brand=card_brand or None,
                last_four=last_four or None,
                entry_method=entry_mode,
                processor_response_code=result_code,
                processor_message=resp_msg,
                timestamp=datetime.now()
            )

        except Exception as e:
            return TransactionResult(
                transaction_id=expected_inv,
                status=TransactionStatus.ERROR,
                error=PaymentError(
                    category=PaymentErrorCategory.SYSTEM,
                    error_code="PARSE_FAIL",
                    message=f"Failed to parse Dejavoo response: {e}",
                    source="DejavooSPInAdapter"
                )
            )
