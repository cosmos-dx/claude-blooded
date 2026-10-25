"""reel-kinetic-01 spec: spoken lines, each with 1–3 beats (a headline that lands on a spoken word)."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

STICKERS = ("none", "zzz", "cross", "check", "star", "circle", "ring", "arrow", "burst", "tape", "stack")


class Beat(BaseModel):
    word: int = Field(default=0, ge=0)                 # index of the spoken word where this beat lands
    big: str = Field(min_length=1, max_length=40)       # headline, "\n" for line breaks, ≤ 3 lines
    pair: str = Field(min_length=1, max_length=4)       # palette pair code
    sticker: Literal[STICKERS] = "none"
    label: str = Field(default="", max_length=40)

    @field_validator("big")
    @classmethod
    def _lines(cls, v):
        rows = v.split("\n")
        if len(rows) > 3 or any(len(r) > 14 for r in rows):
            raise ValueError("big: at most 3 lines of 14 characters")
        return v.upper()


class KLine(BaseModel):
    spk: Literal["N", "R", "C"] = "N"
    text: str = Field(min_length=1, max_length=300)
    el: str = Field(min_length=1, max_length=400)
    emo: str = Field(default="", max_length=80)
    pace: str = Field(default="", max_length=60)
    gap: float = Field(default=0.3, ge=0, le=3.0)
    beats: List[Beat] = Field(min_length=1, max_length=3)


class KineticSpec(BaseModel):
    title: str = Field(max_length=90)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    brand: str = Field(default="", max_length=40)
    palette: str = "poster"
    caption: str = Field(default="", max_length=800)
    lines: List[KLine] = Field(min_length=2, max_length=24)
