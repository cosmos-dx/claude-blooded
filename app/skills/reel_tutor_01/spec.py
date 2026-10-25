"""reel spec (spec.json): the one document that describes a reel — script, voice direction, visuals.

You (the agent) write spec.json; every other script reads it. Visuals are chosen from a fixed scene
library (see SKILL.md › Elements) so no rendering code is written per video.
"""
from __future__ import annotations

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

Speaker = Literal["N", "R", "C"]      # narrator · second voice (calm female) · third voice (young male)
Color = Literal["white", "red", "grey"]
SceneType = Literal["particle_word", "orb", "two_party", "pipeline", "checklist", "graph", "timeline",
                    "cards", "code", "compare", "waveform", "sources", "comment"]


class Line(BaseModel):
    spk: Speaker = "N"
    text: str = Field(min_length=1, max_length=400)     # exact spoken words = caption
    el: str = Field(min_length=1, max_length=500)       # ElevenLabs v3 text with [audio tags]
    emo: str = Field(default="", max_length=80)
    pace: str = Field(default="", max_length=60)
    gap: float = Field(default=0.3, ge=0.0, le=3.5)     # silence after the line (s)


class Item(BaseModel):
    name: str = Field(default="", max_length=60)
    sub: str = Field(default="", max_length=60)
    ok: Optional[bool] = None
    color: Color = "white"
    at: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    start: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    end: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    lines: List[str] = Field(default_factory=list, max_length=3)


class Marker(BaseModel):
    text: str = Field(max_length=40)
    from_index: int = 0
    to_index: Optional[int] = None
    color: Color = "red"
    note: str = Field(default="", max_length=60)


class Visual(BaseModel):
    type: SceneType
    tag: str = Field(default="", max_length=40)
    label: str = Field(default="", max_length=40)
    word: str = Field(default="", max_length=40)
    subtitle: str = Field(default="", max_length=90)
    items: List[Item] = Field(default_factory=list, max_length=6)
    code: List[str] = Field(default_factory=list, max_length=6)
    highlight: Optional[int] = None
    threshold: Optional[float] = Field(default=None, ge=0.05, le=0.95)
    conflict_at: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    countdown: int = Field(default=0, ge=0, le=5)
    left: str = Field(default="", max_length=24)
    right: str = Field(default="", max_length=24)
    marker: Optional[Marker] = None

    @field_validator("word")
    @classmethod
    def _upper(cls, v):
        return v.upper()


class Scene(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    chapter: Optional[int] = None
    visual: Visual
    lines: List[Line] = Field(min_length=1, max_length=6)


class Chapter(BaseModel):
    label: str = Field(max_length=10)
    group: str = Field(max_length=12)


class ReelSpec(BaseModel):
    title: str = Field(max_length=90)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    header: List[str] = Field(min_length=2, max_length=2)
    caption: str = Field(default="", max_length=800)
    speakers: dict = Field(default_factory=dict)          # optional display names, e.g. {"R": "AI interviewer"}
    keywords: List[str] = Field(default_factory=list, max_length=40)
    chapters: List[Chapter] = Field(default_factory=list, max_length=10)
    scenes: List[Scene] = Field(min_length=3, max_length=22)

    @model_validator(mode="after")
    def _check(self):
        ids = [s.id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("scene ids must be unique")
        for s in self.scenes:
            if s.chapter is not None and not 0 <= s.chapter < len(self.chapters):
                raise ValueError(f"scene {s.id}: chapter {s.chapter} out of range")
        return self

    def lines(self):
        for s in self.scenes:
            for ln in s.lines:
                yield s, ln
