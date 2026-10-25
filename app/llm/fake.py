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


def _lines(n):
    return [{"spk": "N", "text": f"Line {i + 1}: here is a clear point about the topic.",
             "el": f"Line {i + 1}: here is a clear point about the topic.", "emo": "calm", "pace": "medium", "gap": 0.3} for i in range(n)]


_ANSWERS = {
    "moderation": lambda p: {"allow": True, "reason": "fine"},
    "research": lambda p: {"angle": "Explain the core idea with one real example", "key_points": ["what it is", "why it matters", "how to use it"],
                           "facts": [], "hook": "There's a really interesting problem here."},
    "voice": lambda p: {"N": "creator-f-in", "R": "calm-f-in", "C": "young-m-in", "reason": "default voices"},
    "publish": lambda p: {"title": "A topic explained in seconds", "instagram": {"caption": "Learn it fast.", "hashtags": ["#tech", "#learn"]},
                          "youtube": {"title": "Explained fast #shorts", "description": "A quick explainer.", "tags": ["tech"], "hashtags": ["#shorts"]},
                          "linkedin": {"post": "A short explainer."}, "posting_time_ist": "19:00", "pinned_comment": "How would you explain it?"},
    "trends": lambda p: {"topics": [{"topic": "system design basics", "why": "steady interest", "hook": "Most people get this wrong"}], "hashtags": ["#systemdesign"]},
    "plan_tutor": lambda p: {
        "title": "Topic explained", "slug": "topic-explained", "header": ["TOPIC · EXPLAINED", "SYSTEM DESIGN · INTERVIEW"],
        "caption": "Quick explainer", "keywords": ["topic"], "chapters": [{"label": "IDEA", "group": "PROBLEM"}, {"label": "FIX", "group": "SOLUTION"}],
        "scenes": [
            {"id": "hook", "chapter": None, "visual": {"type": "particle_word", "word": "TOPIC"}, "lines": _lines(1)},
            {"id": "idea", "chapter": 0, "visual": {"type": "checklist", "tag": "01 · IDEA", "label": "basics",
                                                     "items": [{"name": "First point", "ok": True}, {"name": "Second point", "ok": True}]}, "lines": _lines(1)},
            {"id": "fix", "chapter": 1, "visual": {"type": "pipeline", "tag": "02 · FIX", "label": "flow",
                                                    "items": [{"name": "CLIENT", "sub": "asks"}, {"name": "SERVER", "sub": "answers"}]}, "lines": _lines(1)},
            {"id": "outro", "chapter": None, "visual": {"type": "orb", "word": "FOLLOW FOR MORE"}, "lines": _lines(1)}]},
    "plan_kinetic": lambda p: {
        "title": "Topic explained", "slug": "topic-explained", "brand": "HIREISH REELS", "palette": "poster", "caption": "Quick explainer",
        "lines": [{**_lines(1)[0], "beats": [{"word": 0, "big": "LINE\nONE", "pair": "yk", "sticker": "star", "label": "go"}]},
                  {**_lines(1)[0], "beats": [{"word": 0, "big": "LINE\nTWO", "pair": "ky", "sticker": "check", "label": ""}]}]},
    "shorten": lambda p: {"edits": []},
}
