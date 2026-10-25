"""ModelRouter: maps an agent role (+ the job's tier) to a profile from config, then tries that profile's
providers in order, falling back on retryable errors. A `Conversation` pins the provider that answered
so repair turns (thinking blocks included) go back to the same model."""
from __future__ import annotations

from typing import Callable, Optional

from app.core import logging as log
from app.core.config import Config
from app.core.errors import ProviderError
from app.llm.base import PROVIDERS, LLMProvider, LLMRequest, LLMResponse
from app.llm import anthropic_providers, fake  # noqa: F401  (register implementations)

logger = log.get("llm.router")
UsageHook = Callable[[LLMResponse, str], None]   # (response, role) -> record cost


class Conversation:
    def __init__(self, router: "ModelRouter", role: str, profile: dict, system: str):
        self.router, self.role, self.profile, self.system = router, role, profile, system
        self.messages: list[dict] = []
        self.provider: Optional[LLMProvider] = None

    def ask(self, user_text: str, max_tokens: Optional[int] = None) -> LLMResponse:
        self.messages.append({"role": "user", "content": user_text})
        req = LLMRequest(system=self.system, messages=self.messages, model_alias=self.profile["model"],
                         max_tokens=int(max_tokens or self.profile.get("max_tokens", 16000)),
                         effort=self.profile.get("effort", "medium"), role=self.role)
        resp, self.provider = self.router._dispatch(req, self.profile, pinned=self.provider)
        self.messages.append({"role": "assistant", "content": resp.assistant_content})
        return resp


class ModelRouter:
    def __init__(self, config: Config, on_usage: Optional[UsageHook] = None):
        self.config = config
        self.on_usage = on_usage
        self.providers: dict[str, LLMProvider] = {}
        for name, settings in (config.get("llm.providers") or {}).items():
            self.providers[name] = PROVIDERS.create(settings["kind"], name, settings)
        self.profiles = config.get("llm.profiles") or {}
        self.roles = config.get("llm.roles") or {}
        self.tiers = config.get("tiers") or {}

    def profile_for(self, role: str, tier: str = "standard") -> dict:
        name = self.roles.get(role, "economy")
        if name == "tier":
            name = self.tiers.get(tier, {}).get("llm_profile", "economy")
        if name not in self.profiles:
            raise RuntimeError(f"llm profile '{name}' (role {role}) is not configured")
        return self.profiles[name]

    def available(self) -> list[str]:
        return [n for n, p in self.providers.items() if p.available()]

    def conversation(self, role: str, system: str, tier: str = "standard") -> Conversation:
        return Conversation(self, role, self.profile_for(role, tier), system)

    def _dispatch(self, req: LLMRequest, profile: dict, pinned: Optional[LLMProvider]):
        order = [pinned] if pinned else [self.providers[n] for n in profile.get("providers", []) if n in self.providers]
        candidates = [p for p in order if p and p.available()]
        if not candidates:
            raise ProviderError("no LLM provider is configured (set ANTHROPIC_API_KEY, AWS_BEDROCK_API_KEY_ANTHROPIC or MEGALLM_API_KEY)")
        last: Optional[Exception] = None
        for provider in candidates:
            try:
                resp = provider.complete(req)
                if self.on_usage:
                    self.on_usage(resp, req.role)
                return resp, provider
            except ProviderError as e:
                last = e
                logger.warning("provider %s failed for %s: %s", provider.name, req.role, e)
                if not e.retryable:
                    raise
        raise last or ProviderError("all providers failed")
