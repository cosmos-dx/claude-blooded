"""Plan catalog: config/app.yaml is the source of truth; plans are mirrored into the DB at startup."""
from __future__ import annotations

from app.core.config import Config
from app.core.errors import NotFound
from app.dao.commerce import CreditDAO, PlanDAO


class PlanService:
    def __init__(self, config: Config, plans: PlanDAO, credits: CreditDAO):
        self.config, self.plan_dao, self.credits = config, plans, credits
        self.catalog = {p["code"]: self._normalize(p) for p in (config.get("plans") or [])}

    @staticmethod
    def _normalize(p: dict) -> dict:
        return {"code": p["code"], "name": p["name"], "price_paise": int(round(float(p["price_inr"]) * 100)), "price_inr": p["price_inr"],
                "videos": int(p["videos"]), "max_seconds": int(p["max_seconds"]), "tier": p["tier"],
                "public": bool(p.get("public", True)), "highlight": bool(p.get("highlight", False))}

    def sync(self) -> None:
        for i, plan in enumerate(self.catalog.values()):
            self.plan_dao.upsert(plan, i)

    def public(self) -> list[dict]:
        out = []
        for p in self.catalog.values():
            if p["public"]:
                out.append({**p, "per_video_inr": round(p["price_inr"] / p["videos"], 2)})
        return out

    def get(self, code: str) -> dict:
        if code not in self.catalog:
            raise NotFound("unknown plan")
        return self.catalog[code]

    def grant_signup(self, user_id, conn=None) -> None:
        grant = self.config.get("signup_grant") or {}
        if grant.get("enabled") and grant.get("plan") in self.catalog:
            self.credits.grant(user_id, self.catalog[grant["plan"]], None, conn=conn)
