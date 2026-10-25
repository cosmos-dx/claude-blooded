"""ModelRouter: maps an agent role (+ the job's tier) to a profile from config, then tries that profile's
providers in order, falling back on retryable errors. A `Conversation` pins the provider that answered
so repair turns (thinking blocks included) go back to the same model, and runs the agent loop: server
tools (web search/fetch) are resumed on `pause_turn`, client tools are executed here."""
from __future__ import annotations

import json
from typing import Callable, Optional, Sequence

from app.core import logging as log
from app.core.config import Config
from app.core.errors import ProviderError
from app.llm.base import PROVIDERS, LLMProvider, LLMRequest, LLMResponse
from app.llm.tools import Tool
from app.llm import anthropic_providers, fake  # noqa: F401  (register implementations)

logger = log.get("llm.router")
UsageHook = Callable[[LLMResponse, str], None]   # (response, role) -> record cost


class Conversation:
    def __init__(self, router: "ModelRouter", role: str, profile: dict, system: str, tools: Sequence[Tool] = ()):
        self.router, self.role, self.profile, self.system = router, role, profile, system
        self.messages: list[dict] = []
        self.provider: Optional[LLMProvider] = None
        self.tools = list(tools)              # kept for every turn: a history with tool blocks needs the definitions
        self.sources: list[dict] = []         # everything retrieved across the conversation

    @property
    def researched(self) -> bool:
        return any(t.server for t in self.tools)

    def ask(self, user_text: str, max_tokens: Optional[int] = None) -> LLMResponse:
        self.messages.append({"role": "user", "content": user_text})
        client = {t.name: t for t in self.tools if not t.server}
        texts: list[str] = []
        resp: Optional[LLMResponse] = None
        for _ in range(int(self.router.config.get("llm.max_tool_rounds", 8))):
            req = LLMRequest(system=self.system, messages=self.messages, model_alias=self.profile["model"],
                             max_tokens=int(max_tokens or self.profile.get("max_tokens", 16000)),
                             effort=self.profile.get("effort", "medium"), role=self.role,
                             tools=[t.definition() for t in self.tools],
                             capabilities=tuple(t.capability for t in self.tools if t.server))
            resp, self.provider = self.router._dispatch(req, self.profile, pinned=self.provider)
            self.messages.append({"role": "assistant", "content": resp.assistant_content})
            self._add_sources(resp.sources)
            if resp.text.strip():
                texts.append(resp.text)
            if resp.stop_reason == "pause_turn":          # a long server-tool turn: send it back to continue
                continue
            calls = [b for b in resp.assistant_content if b.get("type") == "tool_use"]
            if resp.stop_reason == "tool_use" and calls:
                self.messages.append({"role": "user", "content": [self._run(client, c) for c in calls]})
                continue
            break
        assert resp is not None
        if not resp.text.strip() and texts:              # the answer may have landed before a final tool round
            resp.text = texts[-1]
        resp.sources = list(self.sources)
        return resp

    def _run(self, client: dict, call: dict) -> dict:
        tool = client.get(call.get("name"))
        if tool is None:
            out, err = f"unknown tool {call.get('name')}", True
        else:
            try:
                out, err = tool.run(call.get("input") or {}), False
            except Exception as e:  # noqa: BLE001 — a tool failure goes back to the model, never fails the job
                logger.warning("tool %s failed: %s", tool.name, e)
                out, err = json.dumps({"error": str(e)[:300]}), True
        return {"type": "tool_result", "tool_use_id": call["id"], "content": out, **({"is_error": True} if err else {})}

    def _add_sources(self, sources: list[dict]) -> None:
        seen = {s["url"] for s in self.sources}
        self.sources += [s for s in sources if s["url"] not in seen]


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

    def can_serve(self, role: str, tier: str, capabilities: Sequence[str]) -> bool:
        """True when some configured provider in the role's profile offers these server-side capabilities."""
        profile = self.profile_for(role, tier)
        return any(p.available() and p.supports(tuple(capabilities))
                   for p in (self.providers.get(n) for n in profile.get("providers", [])) if p)

    def conversation(self, role: str, system: str, tier: str = "standard", tools: Sequence[Tool] = ()) -> Conversation:
        return Conversation(self, role, self.profile_for(role, tier), system, tools)

    def _dispatch(self, req: LLMRequest, profile: dict, pinned: Optional[LLMProvider]):
        order = [pinned] if pinned else [self.providers[n] for n in profile.get("providers", []) if n in self.providers]
        candidates = [p for p in order if p and p.available() and p.supports(req.capabilities)]
        if not candidates:
            need = f" with {', '.join(req.capabilities)}" if req.capabilities else ""
            raise ProviderError(f"no LLM provider{need} is configured (set ANTHROPIC_API_KEY, AWS_BEDROCK_* or MEGALLM_API_KEY)")
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
