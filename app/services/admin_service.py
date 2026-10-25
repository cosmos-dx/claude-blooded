"""Operator view: revenue, spend by provider, margins, job health."""
from __future__ import annotations

from app.dao.commerce import OrderDAO
from app.dao.jobs import JobDAO, UsageDAO
from app.dao.users import UserDAO
from app.llm.router import ModelRouter


class AdminService:
    def __init__(self, users: UserDAO, orders: OrderDAO, jobs: JobDAO, usage: UsageDAO, router: ModelRouter,
                 gst_percent: float, gateway_fee_percent: float):
        self.users, self.orders, self.jobs, self.usage, self.router = users, orders, jobs, usage, router
        self.gst, self.fee = gst_percent / 100, gateway_fee_percent / 100

    def summary(self, days: int = 30) -> dict:
        rev = self.orders.revenue(days)
        spend = self.usage.spend_by_provider(days)
        spend_inr = sum(float(s["inr"] or 0) for s in spend)
        revenue_inr = float(rev["paise"]) / 100
        net_revenue = revenue_inr / (1 + self.gst) * (1 - self.fee)      # prices include GST; the gateway keeps its fee
        return {"days": days, "users": self.users.count(), "paid_orders": rev["paid_orders"], "revenue_inr": revenue_inr,
                "net_revenue_inr": round(net_revenue, 2), "api_spend_inr": round(spend_inr, 2), "spend_today_inr": round(self.usage.spend_today(), 2),
                "margin_inr": round(net_revenue - spend_inr, 2), "spend": spend, "jobs": self.jobs.stats(days),
                "llm_providers_available": self.router.available()}
