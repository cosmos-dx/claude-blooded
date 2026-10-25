"""Community skill packs: data-only styles on top of a built-in engine (no uploaded code runs on the server).
A pack brings 60-30-10 themes, a font trio from the catalog and planner notes; `PackSkill` renders it through
the engine's designed-palette path, so it gets the same 60-30-10 beat colouring and both formats."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

from pydantic import BaseModel, Field

from app.skills.base import Look, Progress, Skill

HEX = r"^#[0-9A-Fa-f]{6}$"


class PackTheme(BaseModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,24}$")
    name: str = Field(min_length=2, max_length=40)
    description: str = Field(default="", max_length=300)
    dominant: str = Field(pattern=HEX)          # ~60%: grounds
    secondary: str = Field(pattern=HEX)         # ~30%: type, inverse frames
    accent: str = Field(pattern=HEX)            # ~10%: punchlines, stickers, CTA


class PackFont(BaseModel):
    family: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    weight: int = Field(default=400, ge=100, le=900)


class SkillPack(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,30}-[0-9]{2}$", description="e.g. chai-minimal-01")
    name: str = Field(min_length=3, max_length=40)
    engine: str = Field(description="built-in skill that renders it: reel-kinetic-01 or reel-tutor-01")
    description: str = Field(min_length=10, max_length=400)
    themes: List[PackTheme] = Field(min_length=1, max_length=6)
    fonts: Dict[str, PackFont] = Field(description="display, text and accent faces from the font catalog")
    scale_ratio: float = Field(default=1.333, ge=1.1, le=1.7)
    planner_notes: str = Field(default="", max_length=1500, description="tone, pacing and copy rules for the scriptwriter")


class PackSkill(Skill):
    """A skill pack as a Skill: delegates to its engine with the pack theme turned into a designed look."""

    def __init__(self, pack: dict, engine: Skill, to_brief: Callable[[dict, dict], dict]):
        super().__init__({})
        self.pack, self.engine = pack, engine
        self.code, self.contract = pack["code"], engine.contract
        self._briefs = {t["slug"]: to_brief(pack, t) for t in pack["themes"]}

    @property
    def themes(self) -> list[str]:
        return list(self._briefs)

    def builtin_theme(self, theme: str) -> str:
        return theme if theme in self._briefs else self.themes[0]

    def _look(self, look: Look) -> Look:
        if look.designed:                                  # "auto": the Design Director's palette wins
            return look
        return Look(theme="auto", format=look.format, brief=self._briefs[self.builtin_theme(look.theme)])

    def guide(self, look: Look) -> str:
        notes = self.pack.get("planner_notes", "").strip()
        extra = f"\n\n# Style notes from the skill author ({self.pack['name']})\n{notes}" if notes else ""
        return self.engine.guide(self._look(look)) + extra

    def validate(self, data: dict, look: Look) -> dict:
        return self.engine.validate(data, self._look(look))

    def lines(self, spec: dict):
        return self.engine.lines(spec)

    def apply_line_edits(self, spec: dict, edits: dict) -> dict:
        return self.engine.apply_line_edits(spec, edits)

    def music_spec(self, spec: dict) -> dict:
        return self.engine.music_spec(spec)

    def render(self, workdir: Path, spec: dict, look: Look, progress: Progress, processes: int) -> Path:
        return self.engine.render(workdir, spec, self._look(look), progress, processes)

    def title(self, spec: dict) -> str:
        return self.engine.title(spec)

    def spec_schema(self) -> dict:
        return self.engine.spec_schema()
