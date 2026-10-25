"""Agent base: an LLM role with a prompt file (app/prompts/<role>.md), a JSON contract and one repair turn.
Agents are created by the factory (AGENTS registry) and talk to models only through the ModelRouter."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.config import Config
from app.core.errors import AppError, ProviderError
from app.core.registry import Registry
from app.llm.router import Conversation, ModelRouter
from app.llm.tools import Tool, build

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in the reply")
    return json.loads(m.group(0))


class Agent:
    role = ""

    def __init__(self, router: ModelRouter, config: Config):
        self.router, self.config = router, config

    def tools(self, request: dict, tier: str) -> list[Tool]:
        """This agent's tools from config: the always-on ones (agents.tools.<role>) plus live web research
        (agents.research) for eligible tiers and lengths, when a provider in the role's profile can run it."""
        cfg = self.config
        names = list(cfg.get(f"agents.tools.{self.role}") or [])
        research = cfg.get("agents.research") or {}
        web = (research.get("tools") or {}).get(self.role) or []
        eligible = tier in (research.get("tiers") or []) and int(request.get("seconds") or 0) >= int(research.get("min_seconds") or 0)
        if web and eligible:
            caps = [t.capability for t in build(web, cfg) if t.server]
            if self.router.can_serve(self.role, tier, caps):
                names += web
        return build(names, cfg)

    def system_prompt(self, **fmt) -> str:
        text = (PROMPTS / f"{self.role}.md").read_text()
        for k, v in fmt.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    def ask_json(self, convo: Conversation, user_text: str, validate: Callable[[dict], Any], max_tokens: Optional[int] = None) -> Any:
        """Ask, parse, validate; on a bad reply send the error back once in the same conversation (cached prefix)."""
        reply = convo.ask(user_text, max_tokens)
        for attempt in range(2):
            try:
                return validate(extract_json(reply.text))
            except (ValueError, KeyError, TypeError) as e:
                if attempt == 1:
                    raise AppError(f"{self.role} returned an invalid answer: {str(e)[:200]}", code="agent_invalid")
                reply = convo.ask(f"That JSON is invalid: {str(e)[:1200]}\nReturn the full corrected JSON only.", max_tokens)
        raise ProviderError("unreachable")


AGENTS: Registry[Agent] = Registry("agent")
