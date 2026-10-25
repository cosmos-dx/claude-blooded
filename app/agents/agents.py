"""The reel agents. Each one is a role in config (llm.roles) with its own prompt file."""
from __future__ import annotations

import json
from typing import Callable, Optional

import httpx

from app.agents.base import AGENTS, Agent
from app.core.errors import AppError
from app.skills.base import Look, Skill


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

    def research(self, request: dict, tier: str, trends: list[dict]) -> tuple[dict, list[dict]]:
        """(research, sources): sources are the URLs actually retrieved when web research ran."""
        convo = self.router.conversation(self.role, self.system_prompt(), tier=tier, tools=self.tools(request, tier))
        payload = {"problem": request["problem"], "details": request.get("details", ""), "language": request["language"],
                   "seconds": request["seconds"], "trend_digest": trends[:3], "web_research": convo.researched}

        def ok(d):
            if not isinstance(d.get("key_points"), list) or not d.get("angle"):
                raise ValueError("needs angle and key_points")
            return d
        return self.ask_json(convo, json.dumps(payload, ensure_ascii=False, default=str), ok), convo.sources


@AGENTS.register("planner")
class Planner(Agent):
    """Writes the skill's spec. Keeps its conversation so the shorten pass reuses the cached prefix."""
    role = "planner"

    def start(self, skill: Skill, tier: str, seconds: int, look: Look):
        wps = float(self.config.get("tts.words_per_second", 2.3))
        guide = skill.guide(look)
        for k, v in {"target_seconds": seconds, "word_budget": int(seconds * wps * 0.92),
                     "min_scenes": max(3, seconds // 12), "max_scenes": max(4, seconds // 8)}.items():
            guide = guide.replace("{" + k + "}", str(v))
        system = self.system_prompt(skill_guide=guide, contract=skill.contract)
        return self.router.conversation(self.role, system, tier=tier)

    def plan(self, convo, skill: Skill, request: dict, research: dict, look: Look) -> dict:
        brief = {"problem": request["problem"], "emotions_and_details": request.get("details", ""),
                 "voice_direction": request.get("voice_prompt", ""), "language": request["language"],
                 "target_seconds": request["seconds"], "format": look.format, "research": research}
        if look.brief:                                    # the Design Director's direction for tone and pacing
            b = look.brief
            brief["design"] = {"positioning": b["positioning"], "mood": b["mood"], "motion": b["motion"],
                               "layout": b["layout"].get(look.format, ""), "do": b["do"], "dont": b["dont"]}
        return self.ask_json(convo, "Write the reel for this brief:\n" + json.dumps(brief, ensure_ascii=False, default=str),
                             lambda d: skill.validate(d, look))

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


@AGENTS.register("design_director")
class DesignDirector(Agent):
    """A senior brand designer: researches the audience and category (web tools when available), then writes a
    strict 60-30-10 design brief. `finalize` (DesignSystem rules) validates and repairs it inside the repair loop."""
    role = "design_director"

    def design(self, request: dict, research: dict, skill_code: str, fmt: str, tier: str, trends: list[dict],
               catalog: str, rules: dict, finalize: Callable[[dict, list, bool], dict]) -> dict:
        system = self.system_prompt(fonts=catalog, **{k: (", ".join(map(str, v)) if isinstance(v, list) else v) for k, v in rules.items()})
        convo = self.router.conversation(self.role, system, tier=tier, tools=self.tools(request, tier))
        payload = {"topic": request["problem"], "emotions_and_details": request.get("details", ""), "voice_direction": request.get("voice_prompt", ""),
                   "language": request["language"], "seconds": request["seconds"], "style": skill_code, "format": fmt,
                   "research": {k: research.get(k) for k in ("angle", "hook", "audience", "key_points") if research.get(k)},
                   "trend_digest": trends[:2], "web_research": convo.researched}
        return self.ask_json(convo, json.dumps(payload, ensure_ascii=False, default=str),
                             lambda d: finalize(d, convo.sources, convo.researched), max_tokens=12000)


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
