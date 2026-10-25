"""Payment gateways (payments.gateway in config). The service layer only sees this interface."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.errors import ProviderError
from app.core.registry import Registry


@dataclass
class GatewayOrder:
    gateway_order_id: str
    amount_paise: int
    currency: str
    checkout: dict          # what the browser needs to open the payment sheet


@dataclass
class PaymentProof:
    gateway_order_id: str
    gateway_payment_id: str
    signature: str


class PaymentGateway(ABC):
    name = "gateway"

    def __init__(self, settings: dict, app_settings: dict):
        self.settings = settings
        self.app = app_settings

    @abstractmethod
    def create_order(self, receipt: str, amount_paise: int, currency: str, notes: dict) -> GatewayOrder: ...

    @abstractmethod
    def verify_payment(self, proof: PaymentProof) -> bool: ...

    @abstractmethod
    def parse_webhook(self, body: bytes, signature: str) -> dict:
        """Return {"event_id", "type", "gateway_order_id", "gateway_payment_id", "paid": bool} or raise ProviderError."""


GATEWAYS: Registry[PaymentGateway] = Registry("payment gateway")


@GATEWAYS.register("razorpay")
class Razorpay(PaymentGateway):
    name = "razorpay"

    def _auth(self):
        key_id, secret = self.settings.get("key_id"), self.settings.get("key_secret")
        if not key_id or not secret:
            raise ProviderError("Razorpay keys are not configured (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET)")
        return key_id, secret

    def create_order(self, receipt, amount_paise, currency, notes) -> GatewayOrder:
        key_id, secret = self._auth()
        r = httpx.post(f"{self.settings['api_base']}/orders", auth=(key_id, secret), timeout=20,
                       json={"amount": amount_paise, "currency": currency, "receipt": receipt[:40], "notes": notes})
        if r.status_code >= 300:
            raise ProviderError(f"Razorpay order failed: HTTP {r.status_code}", retryable=r.status_code >= 500)
        data = r.json()
        return GatewayOrder(data["id"], amount_paise, currency,
                            checkout={"provider": "razorpay", "key": key_id, "order_id": data["id"], "amount": amount_paise,
                                      "currency": currency, "name": self.app.get("name", "")})

    def verify_payment(self, proof: PaymentProof) -> bool:
        _, secret = self._auth()
        expected = hmac.new(secret.encode(), f"{proof.gateway_order_id}|{proof.gateway_payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, proof.signature or "")

    def parse_webhook(self, body: bytes, signature: str) -> dict:
        secret = self.settings.get("webhook_secret")
        if not secret:
            raise ProviderError("RAZORPAY_WEBHOOK_SECRET is not configured")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise ProviderError("bad webhook signature")
        data = json.loads(body)
        payment = (data.get("payload", {}).get("payment") or {}).get("entity") or {}
        order = (data.get("payload", {}).get("order") or {}).get("entity") or {}
        return {"event_id": data.get("id") or f"{data.get('event')}:{payment.get('id')}", "type": data.get("event", ""),
                "gateway_order_id": payment.get("order_id") or order.get("id"), "gateway_payment_id": payment.get("id"),
                "paid": data.get("event") in ("payment.captured", "order.paid")}


@GATEWAYS.register("mock")
class MockGateway(PaymentGateway):
    """Development only: every payment succeeds. Refused when APP_ENV=production."""
    name = "mock"

    def create_order(self, receipt, amount_paise, currency, notes) -> GatewayOrder:
        oid = f"mock_order_{uuid.uuid4().hex[:12]}"
        return GatewayOrder(oid, amount_paise, currency, checkout={"provider": "mock", "order_id": oid, "amount": amount_paise})

    def verify_payment(self, proof: PaymentProof) -> bool:
        return proof.signature == "mock"

    def parse_webhook(self, body: bytes, signature: str) -> dict:
        raise ProviderError("mock gateway has no webhooks")
