"""LLM provider contract. Agents never import a vendor SDK; they call the ModelRouter, which picks a
provider built by the factory below from config (llm.providers.<name>.kind)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.registry import Registry


@dataclass
class LLMRequest:
    system: str
    messages: list[dict]                 # Anthropic-style messages; assistant turns are echoed back unchanged
    model_alias: str                     # e.g. "opus" | "haiku" — mapped per provider in config
    max_tokens: int = 16000
    effort: str = "medium"
    cache_system: bool = True            # long, stable system prompts are cached
    role: str = ""                       # which agent asked (for the usage ledger)
    tools: list[dict] = field(default_factory=list)       # provider-ready tool definitions (app/llm/tools.py)
    capabilities: tuple[str, ...] = ()   # server-side features the provider must support (e.g. web_search)


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    server_tools: dict = field(default_factory=dict)      # e.g. {"web_search": 2} (billed per call)


@dataclass
class LLMResponse:
    text: str
    assistant_content: list[dict]        # what to append to `messages` for a follow-up turn
    usage: LLMUsage
    provider: str
    model: str
    model_alias: str
    stop_reason: str = ""
    sources: list[dict] = field(default_factory=list)     # [{"url", "title"}] the model actually retrieved
    raw: Any = field(default=None, repr=False)


class LLMProvider(ABC):
    def __init__(self, name: str, settings: dict):
        self.name = name
        self.settings = settings

    def model_for(self, alias: str) -> str:
        models = self.settings.get("models", {})
        if alias not in models:
            raise KeyError(f"provider {self.name} has no model for alias '{alias}'")
        return models[alias]

    @abstractmethod
    def available(self) -> bool:
        """True when credentials are configured."""

    def supports(self, capabilities: tuple[str, ...]) -> bool:
        """True when every server-side capability (from config llm.providers.<name>.capabilities) is offered."""
        return set(capabilities) <= set(self.settings.get("capabilities") or [])

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """One model call. Raise ProviderError(retryable=True) for errors another provider could absorb."""


PROVIDERS: Registry[LLMProvider] = Registry("llm provider kind")
