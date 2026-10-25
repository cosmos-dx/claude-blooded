"""The reel agents. Each one is a role in config (llm.roles) with its own prompt file."""
from __future__ import annotations

import json
from typing import Optional

import httpx

from app.agents.base import AGENTS, Agent
from app.core.errors import AppError
from app.skills.base import Skill


@AGENTS.register("moderator")
class Moderator(Agent):
    role = "moderator"

    def check(self, request: dict) -> dict:
        system = self.system_prompt(allow_profanity="allowed" if self.config.get("moderation.allow_profanity") else "not allowed")
        convo = self.router.conversation(self.role, system, tier="free")
        text = json.dumps({k: request.get(k) for k in ("problem", "details", "voice_prompt", "language")}, ensure_ascii=False)
        return self.ask_json(convo, text, lambda d: {"allow": bool(d["allow"]), "reason": str(d.get("reason", ""))[:200]}, max_tokens=2000)


@AGENTS.register("researcher")
class Researcher(Agent):
    role = "researcher"

    def research(self, request: dict, tier: str, trends: list[dict]) -> dict:
        convo = self.router.conversation(self.role, self.system_prompt(), tier=tier)
        payload = {"problem": request["problem"], "details": request.get("details", ""), "language": request["language"],
                   "seconds": request["seconds"], "trend_digest": trends[:3]}

        def ok(d):
            if not isinstance(d.get("key_points"), list) or not d.get("angle"):
                raise ValueError("needs angle and key_points")
            return d
        return self.ask_json(convo, json.dumps(payload, ensure_ascii=False, default=str), ok)


@AGENTS.register("planner")
class Planner(Agent):
    """Writes the skill's spec. Keeps its conversation so the shorten pass reuses the cached prefix."""
    role = "planner"

    def start(self, skill: Skill, tier: str, seconds: int):
        wps = float(self.config.get("tts.words_per_second", 2.3))
        guide = skill.guide()
        for k, v in {"target_seconds": seconds, "word_budget": int(seconds * wps * 0.92),
                     "min_scenes": max(3, seconds // 12), "max_scenes": max(4, seconds // 8)}.items():
            guide = guide.replace("{" + k + "}", str(v))
        system = self.system_prompt(skill_guide=guide, contract=skill.contract)
        return self.router.conversation(self.role, system, tier=tier)

    def plan(self, convo, skill: Skill, request: dict, research: dict, theme: str) -> dict:
        brief = {"problem": request["problem"], "emotions_and_details": request.get("details", ""),
                 "voice_direction": request.get("voice_prompt", ""), "language": request["language"],
                 "target_seconds": request["seconds"], "research": research}
        return self.ask_json(convo, "Write the reel for this brief:\n" + json.dumps(brief, ensure_ascii=False, default=str),
                             lambda d: skill.validate(d, theme))

    def shorten(self, convo, skill: Skill, spec: dict, timeline: dict, max_seconds: float) -> dict:
        rows = [f"{i} ({l['end'] - l['start']:.1f}s): {l['text']}" for i, l in enumerate(timeline["lines"])]
        ask = (f"CONTRACT:shorten The recorded voiceover is {timeline['duration']:.1f}s; it must be at most {max_seconds:.0f}s. "
               f"Cut at least {timeline['duration'] - max_seconds + 2:.0f}s by tightening wording; keep the story.\n" + "\n".join(rows) +
               '\nReturn only JSON: {"edits":[{"line":<index>,"text":"...","el":"..."}]}')

        def ok(d):
            edits = {int(e["line"]): e for e in d.get("edits", []) if e.get("text") and e.get("el")}
            return edits
        edits = self.ask_json(convo, ask, ok, max_tokens=8000)
        return skill.apply_line_edits(spec, edits)


@AGENTS.register("voice_director")
class VoiceDirector(Agent):
    role = "voice_director"

    def cast(self, request: dict, voices: list[dict], defaults: dict) -> dict:
        codes = {v["code"] for v in voices}
        convo = self.router.conversation(self.role, self.system_prompt(), tier="free")
        payload = {"language": request["language"], "narrator": request.get("narrator", "female"),
                   "voice_prompt": request.get("voice_prompt", ""), "catalog": [{k: v[k] for k in ("code", "language", "gender", "persona")} for v in voices]}

        def ok(d):
            out = {}
            for role in ("N", "R", "C"):
                out[role] = d.get(role) if d.get(role) in codes else defaults[role]
            return out
        try:
            return self.ask_json(convo, json.dumps(payload, ensure_ascii=False), ok, max_tokens=2000)
        except AppError:
            return dict(defaults)


@AGENTS.register("publisher")
class Publisher(Agent):
    role = "publisher"

    def pack(self, spec: dict, request: dict, trends: list[dict]) -> dict:
        convo = self.router.conversation(self.role, self.system_prompt(), tier="free")
        script = " ".join(l["text"] for l in (spec.get("lines") or [ln for s in spec.get("scenes", []) for ln in s["lines"]]))
        payload = {"title": spec.get("title"), "script": script[:3000], "language": request["language"], "trend_digest": trends[:2]}

        def ok(d):
            for k in ("title", "instagram", "youtube"):
                if k not in d:
                    raise ValueError(f"missing {k}")
            return d
        return self.ask_json(convo, json.dumps(payload, ensure_ascii=False, default=str), ok, max_tokens=4000)


@AGENTS.register("trend_scout")
class TrendScout(Agent):
    role = "trend_scout"

    def youtube_popular(self) -> list[dict]:
        key = self.config.get("trends.youtube_api_key")
        if not key:
            return []
        r = httpx.get("https://www.googleapis.com/youtube/v3/videos", timeout=20,
                      params={"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": self.config.get("trends.region", "IN"),
                              "videoCategoryId": "28", "maxResults": 25, "key": key})
        if r.status_code != 200:
            return []
        return [{"title": i["snippet"]["title"], "channel": i["snippet"]["channelTitle"], "views": i["statistics"].get("viewCount"),
                 "duration": i["contentDetails"]["duration"]} for i in r.json().get("items", [])]

    def digest(self, niche: str, popular: Optional[list] = None) -> dict:
        convo = self.router.conversation(self.role, self.system_prompt(), tier="standard")
        payload = {"niche": niche, "region": self.config.get("trends.region", "IN"), "youtube_most_popular_science_tech": popular or []}

        def ok(d):
            if not isinstance(d.get("topics"), list):
                raise ValueError("needs topics")
            return d
        return self.ask_json(convo, json.dumps(payload, ensure_ascii=False), ok)
