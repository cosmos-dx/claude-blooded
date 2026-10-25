"""reel-kinetic-01: bold color-block kinetic typography (huge condensed headlines, tiny mono follow-ups, stickers)."""
from __future__ import annotations

import json
from pathlib import Path

from app.skills.base import SKILLS, Progress, Skill
from app.skills.reel_kinetic_01.renderer import PALETTES


@SKILLS.register("reel-kinetic-01")
class ReelKinetic01(Skill):
    code = "reel-kinetic-01"
    contract = "plan_kinetic"

    def validate(self, data: dict, theme: str) -> dict:
        from app.skills.reel_kinetic_01.spec import KineticSpec
        if theme not in PALETTES:
            raise ValueError(f"unknown palette '{theme}'")
        data = {**data, "palette": theme}
        spec = KineticSpec.model_validate(data).model_dump()
        pairs = PALETTES[theme]["pairs"]
        first = next(iter(pairs))
        for line in spec["lines"]:                       # repair rather than reject: unknown pairs fall back to the first
            for b in line["beats"]:
                if b["pair"] not in pairs:
                    b["pair"] = first
        return spec

    def lines(self, spec: dict) -> list[tuple[str, dict]]:
        return [(f"l{i}", ln) for i, ln in enumerate(spec["lines"])]

    def apply_line_edits(self, spec: dict, edits: dict[int, dict]) -> dict:
        for i, ln in enumerate(spec["lines"]):
            if i in edits:
                ln.update({k: v for k, v in edits[i].items() if k in ("text", "el")})
                n = len(ln["text"].split())
                for b in ln["beats"]:
                    b["word"] = min(b["word"], max(0, n - 1))
        return spec

    def music_spec(self, spec: dict) -> dict:
        return {"scenes": [{"id": f"l{i}", "chapter": 0, "visual": {"type": "kinetic"}} for i in range(len(spec["lines"]))]}

    def render(self, workdir: Path, spec: dict, theme: str, progress: Progress, processes: int) -> Path:
        from app.skills.reel_kinetic_01 import renderer
        (workdir / "spec.json").write_text(json.dumps(spec))
        renderer.render(str(workdir), progress, processes)
        return workdir / "video_silent.mp4"

    def guide(self) -> str:
        palettes = "\n".join(f"- {name}: {p['description']} Pairs: {', '.join(p['pairs'])}" for name, p in PALETTES.items() if not name.startswith("_"))
        return super().guide().replace("{palettes}", palettes)
