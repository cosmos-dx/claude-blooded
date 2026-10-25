"""Plans, orders, credit packs and payment events."""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from app.dao.base import BaseDAO


class PlanDAO(BaseDAO):
    def upsert(self, plan: dict, sort: int, conn=None) -> None:
        self.run("""INSERT INTO plans (code, name, price_paise, videos, max_seconds, tier, public, sort, updated_at)
                    VALUES (%(code)s, %(name)s, %(price_paise)s, %(videos)s, %(max_seconds)s, %(tier)s, %(public)s, %(sort)s, now())
                    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, price_paise = EXCLUDED.price_paise,
                      videos = EXCLUDED.videos, max_seconds = EXCLUDED.max_seconds, tier = EXCLUDED.tier,
                      public = EXCLUDED.public, sort = EXCLUDED.sort, updated_at = now()""", {**plan, "sort": sort}, conn)

    def get(self, code: str, conn=None) -> Optional[dict]:
        return self.one("SELECT * FROM plans WHERE code = %s", (code,), conn)


class OrderDAO(BaseDAO):
    def create(self, user_id: str, plan: dict, gateway: str, currency: str, conn=None) -> dict:
        return self.one("""INSERT INTO orders (user_id, plan_code, amount_paise, currency, gateway)
                           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                        (user_id, plan["code"], plan["price_paise"], currency, gateway), conn)

    def set_gateway_order(self, order_id: str, gateway_order_id: str, conn=None) -> None:
        self.run("UPDATE orders SET gateway_order_id = %s WHERE id = %s", (gateway_order_id, order_id), conn)

    def by_gateway_order(self, gateway_order_id: str, lock: bool = False, conn=None) -> Optional[dict]:
        return self.one("SELECT * FROM orders WHERE gateway_order_id = %s" + (" FOR UPDATE" if lock else ""), (gateway_order_id,), conn)

    def mark_paid(self, order_id: str, payment_id: str, conn=None) -> None:
        self.run("UPDATE orders SET status = 'paid', gateway_payment_id = %s, paid_at = now() WHERE id = %s", (payment_id, order_id), conn)

    def mark_failed(self, order_id: str, conn=None) -> None:
        self.run("UPDATE orders SET status = 'failed' WHERE id = %s AND status = 'created'", (order_id,), conn)

    def for_user(self, user_id: str, conn=None) -> list[dict]:
        return self.all("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT 50", (user_id,), conn)

    def revenue(self, days: int, conn=None) -> dict:
        return self.one("""SELECT count(*) AS paid_orders, coalesce(sum(amount_paise), 0) AS paise FROM orders
                           WHERE status = 'paid' AND paid_at > now() - make_interval(days => %s)""", (days,), conn)


class CreditDAO(BaseDAO):
    def grant(self, user_id: str, plan: dict, order_id: Optional[str], conn=None) -> Optional[dict]:
        return self.one("""INSERT INTO credit_packs (user_id, order_id, plan_code, tier, max_seconds, total, remaining)
                           VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING *""",
                        (user_id, order_id, plan["code"], plan["tier"], plan["max_seconds"], plan["videos"], plan["videos"]), conn)

    def reserve(self, user_id: str, seconds: int, conn) -> Optional[dict]:
        """Take one credit from the cheapest pack that covers `seconds` (call inside a transaction)."""
        pack = self.one("""SELECT * FROM credit_packs WHERE user_id = %s AND remaining > 0 AND max_seconds >= %s
                           ORDER BY max_seconds, created_at LIMIT 1 FOR UPDATE SKIP LOCKED""", (user_id, seconds), conn)
        if pack:
            self.run("UPDATE credit_packs SET remaining = remaining - 1 WHERE id = %s", (pack["id"],), conn)
        return pack

    def refund(self, pack_id: str, conn=None) -> None:
        self.run("UPDATE credit_packs SET remaining = remaining + 1 WHERE id = %s AND remaining < total", (pack_id,), conn)

    def summary(self, user_id: str, conn=None) -> list[dict]:
        return self.all("""SELECT max_seconds, tier, sum(remaining)::int AS remaining FROM credit_packs
                           WHERE user_id = %s AND remaining > 0 GROUP BY max_seconds, tier ORDER BY max_seconds""", (user_id,), conn)


class PaymentEventDAO(BaseDAO):
    def record(self, gateway: str, event_id: str, event_type: str, payload: dict, conn=None) -> bool:
        """False when this event was already processed (webhooks are retried)."""
        row = self.one("""INSERT INTO payment_events (gateway, event_id, event_type, payload) VALUES (%s, %s, %s, %s)
                          ON CONFLICT (gateway, event_id) DO NOTHING RETURNING id""",
                       (gateway, event_id, event_type, Jsonb(payload)), conn)
        return row is not None
