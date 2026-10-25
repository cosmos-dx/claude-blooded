"""reel-tutor-01: monochrome point-cloud explainer style (chapter rail, bracketed panels, 13 elements)."""
from __future__ import annotations

import json
from pathlib import Path

from app.skills.base import SKILLS, Progress, Skill


@SKILLS.register("reel-tutor-01")
class ReelTutor01(Skill):
    code = "reel-tutor-01"
    contract = "plan_tutor"

    def validate(self, data: dict, theme: str) -> dict:
        from app.skills.reel_tutor_01.spec import ReelSpec
        from app.skills.reel_tutor_01 import themes
        themes.get(theme)                                   # raises for an unknown theme
        return ReelSpec.model_validate(data).model_dump()

    def lines(self, spec: dict) -> list[tuple[str, dict]]:
        return [(s["id"], ln) for s in spec["scenes"] for ln in s["lines"]]

    def apply_line_edits(self, spec: dict, edits: dict[int, dict]) -> dict:
        i = 0
        for s in spec["scenes"]:
            for ln in s["lines"]:
                if i in edits:
                    ln.update({k: v for k, v in edits[i].items() if k in ("text", "el")})
                i += 1
        return spec

    def music_spec(self, spec: dict) -> dict:
        return spec

    def render(self, workdir: Path, spec: dict, theme: str, progress: Progress, processes: int) -> Path:
        from app.skills.reel_tutor_01 import engine, themes
        (workdir / "spec.json").write_text(json.dumps(spec))
        (workdir / "theme.json").write_text(themes.get(theme).model_dump_json())
        engine.render(str(workdir), progress, procs=processes)
        return workdir / "video_silent.mp4"
