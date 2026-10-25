"""Prices every provider call (USD and INR), writes it to the usage ledger and tallies it per job stage.
The current job/stage travel in a context variable, so the shared ModelRouter needs no job argument."""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

from app.core.config import Config
from app.dao.jobs import UsageDAO
from app.llm.base import LLMResponse


@dataclass
class Tally:
    job_id: Optional[str]
    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    cost_inr: float = 0.0
    calls: list = field(default_factory=list)


_scope: contextvars.ContextVar[Optional[Tally]] = contextvars.ContextVar("cost_scope", default=None)


class CostService:
    def __init__(self, config: Config, usage_dao: UsageDAO):
        self.usd_inr = float(config.get("money.usd_inr", 88))
        self.prices = config.get("llm.prices_usd_per_mtok") or {}
        self.tool_prices = config.get("llm.server_tool_prices_usd") or {}
        self.usage_dao = usage_dao

    @contextmanager
    def scope(self, job_id: Optional[str]) -> Iterator[Tally]:
        tally = Tally(job_id)
        token = _scope.set(tally)
        try:
            yield tally
        finally:
            _scope.reset(token)

    def llm_usd(self, resp: LLMResponse) -> float:
        p = self.prices.get(resp.model_alias, {})
        u = resp.usage
        tokens = (u.input_tokens * p.get("input", 0) + u.output_tokens * p.get("output", 0)
                  + u.cache_read * p.get("cache_read", 0) + u.cache_write * p.get("cache_write", 0)) / 1e6
        return tokens + sum(n * float(self.tool_prices.get(k, 0)) for k, n in u.server_tools.items())

    def record_llm(self, resp: LLMResponse, role: str) -> None:
        usd = 0.0 if resp.provider == "fake" else self.llm_usd(resp)
        tally = _scope.get()
        row = dict(job_id=tally.job_id if tally else None, kind="llm", provider=resp.provider, model=resp.model, role=role,
                   input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens, cache_read=resp.usage.cache_read,
                   cache_write=resp.usage.cache_write, cost_usd=usd, cost_inr=usd * self.usd_inr)
        self.usage_dao.add(row)
        if tally:
            tally.input_tokens += resp.usage.input_tokens + resp.usage.cache_read + resp.usage.cache_write
            tally.output_tokens += resp.usage.output_tokens
            tally.cost_inr += usd * self.usd_inr

    def record_tts(self, provider: str, model: str, characters: int, usd_per_1k: float) -> None:
        if characters <= 0:
            return
        usd = characters * usd_per_1k / 1000
        tally = _scope.get()
        self.usage_dao.add(dict(job_id=tally.job_id if tally else None, kind="tts", provider=provider, model=model, role="voice",
                                characters=characters, cost_usd=usd, cost_inr=usd * self.usd_inr))
        if tally:
            tally.characters += characters
            tally.cost_inr += usd * self.usd_inr
