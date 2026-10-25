"""reel-tutor-01: monochrome point-cloud explainer style (chapter rail, bracketed panels, 13 elements)."""
from __future__ import annotations

import json
from pathlib import Path

from app.skills.base import SKILLS, Look, Progress, Skill


@SKILLS.register("reel-tutor-01")
class ReelTutor01(Skill):
    code = "reel-tutor-01"
    contract = "plan_tutor"

    def builtin_theme(self, theme: str) -> str:
        from app.skills.reel_tutor_01 import themes
        return theme if theme in themes.all_themes() else next(iter(themes.BUILTIN))

    def theme(self, look: Look):
        from app.skills.reel_tutor_01 import themes
        return themes.from_brief(look.brief) if look.designed else themes.get(self.builtin_theme(look.theme))

    def validate(self, data: dict, look: Look) -> dict:
        from app.skills.reel_tutor_01.spec import ReelSpec
        self.theme(look)                                    # raises for a theme that cannot be built
        return ReelSpec.model_validate(data).model_dump()

    def spec_schema(self) -> dict:
        from app.skills.reel_tutor_01.spec import ReelSpec
        return ReelSpec.model_json_schema()

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

    def render(self, workdir: Path, spec: dict, look: Look, progress: Progress, processes: int) -> Path:
        from app.skills.reel_tutor_01 import engine, landscape
        theme = self.theme(look)
        (workdir / "spec.json").write_text(json.dumps(spec))
        (workdir / "theme.json").write_text(theme.model_dump_json())
        landscape_out = look.format == "16:9"
        engine.render(str(workdir), (lambda f: progress(f * 0.9)) if landscape_out else progress, procs=processes)
        if landscape_out:                                   # composed: vertical stage + typeset side column
            landscape.compose(workdir, spec, theme)
            progress(1.0)
        return workdir / "video_silent.mp4"
