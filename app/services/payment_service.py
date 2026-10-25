"""Checkout: create a gateway order, then fulfil it exactly once — from the browser's signed callback or
from the gateway webhook, whichever arrives first."""
from __future__ import annotations

from app.core.errors import AppError, Forbidden, NotFound
from app.dao.commerce import CreditDAO, OrderDAO, PaymentEventDAO
from app.db.pool import Database
from app.payments.gateways import PaymentGateway, PaymentProof
from app.services.plan_service import PlanService


class PaymentService:
    def __init__(self, db: Database, gateway: PaymentGateway, plans: PlanService, orders: OrderDAO, credits: CreditDAO,
                 events: PaymentEventDAO, currency: str):
        self.db, self.gateway, self.plans, self.orders, self.credits, self.events = db, gateway, plans, orders, credits, events
        self.currency = currency

    def start_checkout(self, user: dict, plan_code: str) -> dict:
        plan = self.plans.get(plan_code)
        if not plan["public"] or plan["price_paise"] <= 0:
            raise AppError("this plan can't be bought")
        order = self.orders.create(user["id"], plan, self.gateway.name, self.currency)
        gw = self.gateway.create_order(str(order["id"]), plan["price_paise"], self.currency,
                                       {"order": str(order["id"]), "plan": plan["code"], "email": user["email"]})
        self.orders.set_gateway_order(order["id"], gw.gateway_order_id)
        return {"order_id": str(order["id"]), "plan": plan, "checkout": {**gw.checkout, "prefill": {"email": user["email"]}}}

    def confirm(self, user: dict, proof: PaymentProof) -> dict:
        if not self.gateway.verify_payment(proof):
            raise AppError("payment could not be verified", code="payment_unverified")
        return self._fulfil(proof.gateway_order_id, proof.gateway_payment_id, expected_user=user["id"])

    def webhook(self, body: bytes, signature: str) -> dict:
        evt = self.gateway.parse_webhook(body, signature)
        if not self.events.record(self.gateway.name, evt["event_id"], evt["type"], {"order": evt["gateway_order_id"], "payment": evt["gateway_payment_id"]}):
            return {"status": "duplicate"}
        if evt["paid"] and evt["gateway_order_id"]:
            return self._fulfil(evt["gateway_order_id"], evt["gateway_payment_id"])
        return {"status": "ignored"}

    def _fulfil(self, gateway_order_id: str, payment_id: str, expected_user=None) -> dict:
        with self.db.transaction() as conn:
            order = self.orders.by_gateway_order(gateway_order_id, lock=True, conn=conn)
            if not order:
                raise NotFound("order not found")
            if expected_user is not None and str(order["user_id"]) != str(expected_user):
                raise Forbidden("this order belongs to another account")
            if order["status"] != "paid":
                self.orders.mark_paid(order["id"], payment_id, conn=conn)
                self.credits.grant(order["user_id"], self.plans.get(order["plan_code"]), order["id"], conn=conn)
        return {"status": "paid", "order_id": str(order["id"])}
