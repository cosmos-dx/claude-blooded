"""Composition root. Every concrete class is chosen here from config through its registry (factory
pattern); the API and the worker only ask the container for services."""
from __future__ import annotations

import os
from functools import cached_property, lru_cache

from app.core.config import Config, get_config


class Container:
    def __init__(self, config: Config):
        self.config = config
        os.environ.setdefault("REEL_FONT_DIR", str(config.get("render.font_dir")))   # read by the renderers at import
        if config.is_production and config.get("payments.gateway") == "mock":
            raise RuntimeError("the mock payment gateway is not allowed in production")

    # ---------------------------------------------------------------- infrastructure
    @cached_property
    def db(self):
        from app.db.pool import Database
        return Database(self.config)

    @cached_property
    def storage(self):
        from app.storage.stores import STORES
        s = self.config.get("storage") or {}
        return STORES.create(s.get("provider", "local"), s, self.config.get("app.data_dir"))

    @cached_property
    def mailer(self):
        from app.mail.mailers import MAILERS
        provider = self.config.get("mail.provider")
        if self.config.is_production and provider == "console":
            raise RuntimeError("MAIL_PROVIDER=console is not allowed in production")
        return MAILERS.create(provider, self.config.get(f"mail.{provider}") or {})

    @cached_property
    def gateway(self):
        from app.payments.gateways import GATEWAYS
        name = self.config.get("payments.gateway")
        return GATEWAYS.create(name, self.config.get(f"payments.{name}") or {}, self.config.get("app") or {})

    @cached_property
    def tts(self):
        from app.tts import providers  # noqa: F401  (register implementations)
        from app.tts.base import TTS
        name = self.config.get("tts.provider")
        return TTS.create(name, self.config.get(f"tts.{name}") or {})

    @cached_property
    def router(self):
        from app.llm.router import ModelRouter
        return ModelRouter(self.config, on_usage=self.cost.record_llm)

    @cached_property
    def skills(self) -> dict:
        from app.skills.base import SKILLS
        from app.skills.reel_kinetic_01 import skill as _k  # noqa: F401  (register)
        from app.skills.reel_tutor_01 import skill as _t  # noqa: F401
        return {code: SKILLS.create(code, self.config.get(f"skills.settings.{code}") or {}) for code in self.config.get("skills.enabled")}

    @cached_property
    def agents(self) -> dict:
        from app.agents import agents as _a  # noqa: F401  (register)
        from app.agents.base import AGENTS
        return {name: AGENTS.create(name, self.router, self.config) for name in AGENTS.names()}

    # ---------------------------------------------------------------- DAOs
    @cached_property
    def users(self):
        from app.dao.users import UserDAO
        return UserDAO(self.db)

    @cached_property
    def otps(self):
        from app.dao.users import OtpDAO
        return OtpDAO(self.db)

    @cached_property
    def plans_dao(self):
        from app.dao.commerce import PlanDAO
        return PlanDAO(self.db)

    @cached_property
    def orders(self):
        from app.dao.commerce import OrderDAO
        return OrderDAO(self.db)

    @cached_property
    def credits(self):
        from app.dao.commerce import CreditDAO
        return CreditDAO(self.db)

    @cached_property
    def payment_events(self):
        from app.dao.commerce import PaymentEventDAO
        return PaymentEventDAO(self.db)

    @cached_property
    def jobs(self):
        from app.dao.jobs import JobDAO
        return JobDAO(self.db)

    @cached_property
    def job_events(self):
        from app.dao.jobs import JobEventDAO
        return JobEventDAO(self.db)

    @cached_property
    def usage(self):
        from app.dao.jobs import UsageDAO
        return UsageDAO(self.db)

    @cached_property
    def trends(self):
        from app.dao.jobs import TrendDAO
        return TrendDAO(self.db)

    # ---------------------------------------------------------------- services
    @cached_property
    def cost(self):
        from app.services.cost_service import CostService
        return CostService(self.config, self.usage)

    @cached_property
    def tokens(self):
        from app.core.security import TokenService
        return TokenService(self.config)

    @cached_property
    def plans(self):
        from app.services.plan_service import PlanService
        return PlanService(self.config, self.plans_dao, self.credits)

    @cached_property
    def auth(self):
        from app.services.auth_service import AuthService
        return AuthService(self.config, self.db, self.users, self.otps, self.mailer, self.tokens, self.plans)

    @cached_property
    def payments(self):
        from app.services.payment_service import PaymentService
        return PaymentService(self.db, self.gateway, self.plans, self.orders, self.credits, self.payment_events,
                              self.config.get("payments.currency", "INR"))

    @cached_property
    def job_service(self):
        from app.services.job_service import JobService
        return JobService(self.config, self.db, self.jobs, self.job_events, self.usage, self.credits, self.storage, list(self.skills))

    @cached_property
    def admin(self):
        from app.services.admin_service import AdminService
        return AdminService(self.users, self.orders, self.jobs, self.usage, self.router,
                            float(self.config.get("payments.gst_percent", 18)), float(self.config.get("payments.gateway_fee_percent", 2)))

    @cached_property
    def step_deps(self):
        from app.workflows import steps as _s  # noqa: F401  (register)
        from app.workflows.base import StepDeps
        return StepDeps(config=self.config, router=self.router, agents=self.agents, tts=self.tts, cost=self.cost, trends=self.trends)


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container(get_config())
