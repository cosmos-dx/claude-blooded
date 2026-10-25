"""Deterministic offline provider for tests and local runs without keys (llm.providers.fake.enabled).
It answers each agent's JSON contract with a small valid payload so the whole pipeline can run."""
from __future__ import annotations

import json
import re

from app.llm.base import PROVIDERS, LLMProvider, LLMRequest, LLMResponse, LLMUsage


@PROVIDERS.register("fake")
class FakeProvider(LLMProvider):
    def available(self) -> bool:
        return bool(self.settings.get("enabled"))

    def model_for(self, alias: str) -> str:
        return f"fake-{alias}"

    def complete(self, req: LLMRequest) -> LLMResponse:
        prompt = json.dumps(req.messages)[-4000:]
        marker = re.search(r"CONTRACT:(\w+)", req.system)
        contract = marker.group(1) if marker else "text"
        payload = _ANSWERS.get(contract, lambda p: {"text": "ok"})(prompt)
        text = json.dumps(payload)
        usage = LLMUsage(input_tokens=len(req.system + prompt) // 4, output_tokens=len(text) // 4)
        return LLMResponse(text=text, assistant_content=[{"type": "text", "text": text}], usage=usage,
                           provider=self.name, model=self.model_for(req.model_alias), model_alias=req.model_alias, stop_reason="end_turn")


def _line(text: str, emo: str = "calm") -> dict:
    return {"spk": "N", "text": text, "el": text, "emo": emo, "pace": "medium", "gap": 0.3}


def _lines(n):
    return [_line(f"Line {i + 1}: here is a clear point about the topic.") for i in range(n)]


_KINETIC = [  # sample copy so local runs and preview renders look like a real reel
    ("Two servers get the same request.", [("TWO\nSERVERS", "none", "")]),
    ("Both let it through, and your limit breaks.", [("LIMIT\nBROKEN", "cross", "")]),
    ("Fix it with one atomic counter.", [("ATOMIC\nCOUNTER", "check", "redis incr")]),
    ("Check and increment in one step. No race.", [("NO\nRACE", "star", "WIN")]),
    ("Follow for the next one.", [("FOLLOW\nFOR MORE", "tape", "")]),
]

_ANSWERS = {
    "moderation": lambda p: {"allow": True, "reason": "fine"},
    "research": lambda p: {"angle": "Explain the core idea with one real example", "key_points": ["what it is", "why it matters", "how to use it"],
                           "facts": [{"fact": "Redis INCR is atomic", "confidence": "high", "source_url": ""}], "hook": "There's a really interesting problem here."},
    "design_brief": lambda p: {
        "positioning": "Calm authority for young engineers preparing for interviews",
        "audience": "Indian CS students and early-career developers on Reels and Shorts",
        "mood": ["confident", "warm", "precise"],
        "palette": {"name": "Midnight Saffron",
                    "dominant": {"hex": "#120E1F", "name": "midnight plum", "why": "dark, premium ground that keeps type crisp"},
                    "secondary": {"hex": "#F5EFE6", "name": "warm paper", "why": "soft white that reads at 7:1 without glare"},
                    "accent": {"hex": "#FF7A1A", "name": "saffron", "why": "warm Indian accent reserved for the punchline"},
                    "rationale": "Plum grounds most frames, paper inverts the key beats, saffron only on the payoff."},
        "type": {"display": {"family": "bebas-neue", "weight": 400, "why": "tall caps fill vertical frames"},
                 "text": {"family": "inter", "weight": 500, "why": "neutral and legible at caption size"},
                 "accent": {"family": "jetbrains-mono", "weight": 600, "why": "technical labels"},
                 "scale_ratio": 1.333, "rationale": "condensed display against a neutral sans, mono for small labels"},
        "motion": {"pace": "steady", "cuts": "on nouns and verdicts", "notes": "hold the payoff a beat longer"},
        "layout": {"9:16": "headline in the centre third", "16:9": "headline left, sticker right"},
        "do": ["one idea per frame", "accent only on the payoff"], "dont": ["neon glow", "more than three colours"],
        "findings": [{"insight": "Dark grounds with one warm accent read as premium in tech explainers", "source_url": "", "confidence": "medium"}]},
    "voice": lambda p: {"N": "creator-f-in", "R": "calm-f-in", "C": "young-m-in", "reason": "default voices"},
    "publish": lambda p: {"title": "A topic explained in seconds", "instagram": {"caption": "Learn it fast.", "hashtags": ["#tech", "#learn"]},
                          "youtube": {"title": "Explained fast #shorts", "description": "A quick explainer.", "tags": ["tech"], "hashtags": ["#shorts"]},
                          "linkedin": {"post": "A short explainer."}, "posting_time_ist": "19:00", "pinned_comment": "How would you explain it?"},
    "trends": lambda p: {"topics": [{"topic": "system design basics", "why": "steady interest", "hook": "Most people get this wrong"}], "hashtags": ["#systemdesign"]},
    "plan_tutor": lambda p: {
        "title": "How a rate limiter stops a race", "slug": "rate-limiter-race", "header": ["RATE LIMITING · EXPLAINED", "SYSTEM DESIGN · INTERVIEW"],
        "caption": "Quick explainer", "keywords": ["atomic", "redis"],
        "chapters": [{"label": "RACE", "group": "PROBLEM"}, {"label": "ATOMIC", "group": "SOLUTION"}],
        "scenes": [
            {"id": "hook", "chapter": None, "visual": {"type": "particle_word", "word": "RACE"},
             "lines": [_line("Two servers, one request, and both say yes.", "curious")]},
            {"id": "idea", "chapter": 0, "visual": {"type": "checklist", "tag": "01 · RACE", "label": "what breaks",
                                                     "items": [{"name": "Read the count", "ok": True}, {"name": "Write it back", "ok": False}]},
             "lines": [_line("Each reads the count before the other writes it back.")]},
            {"id": "fix", "chapter": 1, "visual": {"type": "pipeline", "tag": "02 · ATOMIC", "label": "one step",
                                                    "items": [{"name": "CLIENT", "sub": "asks"}, {"name": "REDIS", "sub": "INCR"}, {"name": "API", "sub": "allows"}]},
             "lines": [_line("Make it one atomic step in Redis, and the race is gone.", "confident")]},
            {"id": "outro", "chapter": None, "visual": {"type": "orb", "word": "FOLLOW FOR MORE"}, "lines": [_line("Follow for the next one.", "warm")]}]},
    "plan_kinetic": lambda p: {
        "title": "How a rate limiter stops a race", "slug": "rate-limiter-race", "brand": "SYSTEM DESIGN · 60 SEC", "palette": "poster",
        "caption": "Quick explainer",
        "lines": [{**_line(text), "beats": [{"word": 0, "big": big, "pair": "?", "sticker": st, "label": lb} for big, st, lb in beats]}
                  for text, beats in _KINETIC]},
    "shorten": lambda p: {"edits": []},
}
