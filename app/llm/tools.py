"""Agent tools, built by name from config (tools.<name>.kind). Two kinds:

* server tools run on the provider (Claude API web search / web fetch). A request carrying one is only
  routed to providers whose config lists the matching capability.
* client tools run in this app: the model asks, `run` answers, the Conversation loop sends the result back.
  New research sources (an analytics store, a trend database, a competitor crawler) plug in here as client
  tools without touching agents or the router."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Iterable

from app.core.registry import Registry


class Tool(ABC):
    capability = ""                      # server tools: the provider capability they need; client tools: ""

    def __init__(self, name: str, settings: dict):
        self.name, self.settings = name, settings

    @property
    def server(self) -> bool:
        return bool(self.capability)

    @abstractmethod
    def definition(self) -> dict:
        """The entry for the Messages API `tools` list."""

    def run(self, payload: dict) -> str:
        """Client tools only: answer one call. Must not raise on bad input; return an error the model can read."""
        raise NotImplementedError(f"{self.name} runs on the provider")


TOOLS: Registry[Tool] = Registry("tool kind")


@TOOLS.register("claude_web_search")
class WebSearch(Tool):
    capability = "web_search"

    def definition(self) -> dict:
        d = {"type": "web_search_20260209", "name": "web_search", "max_uses": int(self.settings.get("max_uses", 3))}
        if self.settings.get("country"):
            d["user_location"] = {"type": "approximate", "country": self.settings["country"],
                                  **({"timezone": self.settings["timezone"]} if self.settings.get("timezone") else {})}
        return d


@TOOLS.register("claude_web_fetch")
class WebFetch(Tool):
    capability = "web_fetch"

    def definition(self) -> dict:
        return {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": int(self.settings.get("max_uses", 2))}


@TOOLS.register("contrast_check")
class ContrastCheck(Tool):
    """Lets the designer verify colour pairs while it works instead of estimating WCAG ratios."""

    def definition(self) -> dict:
        pair = {"type": "object", "properties": {"fg": {"type": "string", "description": "foreground hex, e.g. #F5F1E8"},
                                                 "bg": {"type": "string", "description": "background hex, e.g. #0B0B0B"}},
                "required": ["fg", "bg"]}
        return {"name": "contrast_check",
                "description": "WCAG contrast ratio for foreground/background colour pairs. Check text pairs (need >= 7:1 here) "
                               "and graphic/accent pairs (need >= 3:1) before you finalise a palette.",
                "input_schema": {"type": "object", "properties": {"pairs": {"type": "array", "maxItems": 12, "items": pair}},
                                 "required": ["pairs"]}}

    def run(self, payload: dict) -> str:
        from app.design.color import contrast, parse_hex
        out = []
        pairs = payload.get("pairs") if isinstance(payload, dict) else None
        if not isinstance(pairs, list):
            return json.dumps({"error": "send {\"pairs\": [{\"fg\": \"#hex\", \"bg\": \"#hex\"}]}"})
        for p in pairs[:12]:
            try:
                out.append({"fg": p["fg"], "bg": p["bg"], "ratio": round(contrast(parse_hex(p["fg"]), parse_hex(p["bg"])), 2)})
            except (KeyError, TypeError, ValueError) as e:
                out.append({"pair": p, "error": str(e)[:120]})
        return json.dumps(out)


def build(names: Iterable[str], config) -> list[Tool]:
    """Tools by config name; unknown names are skipped so a config typo never breaks a job."""
    specs = config.get("tools") or {}
    return [TOOLS.create(specs[n]["kind"], n, specs[n]) for n in names if n in specs]
