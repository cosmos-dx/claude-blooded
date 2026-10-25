"""Themes for reel-tutor-01.

The renderer draws everything in one semantic language — luminance "ink" plus a single accent
channel (errors / the wrong path). A theme recolors that at the end of every frame:
  stops       gradient map: ink luminance 0..1 -> color (dark->light, or light->dark for paper looks)
  accent      color of the accent channel
  background  solid | vignette | grid | dots | gradient
  glow, grain, sans/mono font families, voice_tone (hint for the script)
so every element works in every theme. Built-ins live here; custom themes are JSON files in
../themes/<slug>.json (same fields).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Literal, Tuple

from pydantic import BaseModel, Field, field_validator

THEMES_DIR = Path(__file__).resolve().parent / "themes"


class Theme(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")
    name: str = Field(max_length=40)
    description: str = Field(default="", max_length=400)
    stops: List[Tuple[float, List[int]]] = Field(min_length=2, max_length=5)
    accent: List[int]
    background: Literal["solid", "vignette", "grid", "dots", "gradient"] = "solid"
    glow: float = Field(default=0.32, ge=0.0, le=0.8)
    grain: float = Field(default=0.0, ge=0.0, le=1.0)
    sans: str = Field(default="inter", pattern=r"^[a-z0-9-]{2,40}$")             # a font family folder in REEL_FONT_DIR
    mono: str = Field(default="jetbrains-mono", pattern=r"^[a-z0-9-]{2,40}$")
    voice_tone: str = Field(default="", max_length=200)

    @field_validator("stops")
    @classmethod
    def _stops(cls, v):
        v = sorted(v, key=lambda s: s[0])
        if v[0][0] != 0.0 or v[-1][0] != 1.0:
            raise ValueError("stops must start at 0.0 and end at 1.0")
        for _, c in v:
            if len(c) != 3 or not all(0 <= x <= 255 for x in c):
                raise ValueError("colors are [r,g,b] 0-255")
        return v

    @field_validator("accent")
    @classmethod
    def _accent(cls, v):
        if len(v) != 3 or not all(0 <= x <= 255 for x in v):
            raise ValueError("accent is [r,g,b] 0-255")
        return v


BUILTIN = {
    "mono": Theme(slug="mono", name="Mono Point-Cloud", background="solid", glow=0.32,
                  description="Pure black, white point clouds and hairline wireframes, red only for errors. Premium, minimal, technical. The default.",
                  stops=[(0.0, [2, 2, 3]), (1.0, [250, 250, 248])], accent=[232, 84, 76]),
    "paper": Theme(slug="paper", name="Paper Editorial", background="grid", glow=0.04, grain=0.25,
                   sans="space-grotesk", mono="ibm-plex-mono",
                   description="Warm off-white paper, ink-black diagrams, vermilion accent. Calm, editorial, magazine-explainer feel.",
                   stops=[(0.0, [241, 237, 227]), (0.55, [118, 110, 100]), (1.0, [22, 22, 26])], accent=[214, 64, 36]),
    "ocean": Theme(slug="ocean", name="Deep Ocean", background="vignette", glow=0.42, sans="space-grotesk",
                   description="Midnight navy through teal to ice-white highlights, coral accent. Moody and cinematic, still minimal.",
                   stops=[(0.0, [3, 8, 20]), (0.45, [22, 92, 122]), (1.0, [224, 246, 250])], accent=[255, 122, 92]),
}


def from_brief(brief: dict) -> Theme:
    """The Design Director's palette as a theme: dominant = ground (ink 0), secondary = ink (1), accent = accent;
    the text face drives the sans and the accent face the mono."""
    p, t = brief["palette"], brief["type"]
    rgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    dark = bool(p.get("dark", True))
    return Theme(slug="brief", name=(p.get("name") or "Designer's pick")[:40], description=(p.get("rationale") or "")[:400],
                 stops=[(0.0, rgb(p["dominant"]["hex"])), (1.0, rgb(p["secondary"]["hex"]))], accent=rgb(p["accent"]["hex"]),
                 background="vignette" if dark else "grid", glow=0.3 if dark else 0.04, grain=0.0 if dark else 0.2,
                 sans=t["text"]["family"], mono=t["accent"]["family"])


def all_themes() -> dict:
    out = dict(BUILTIN)
    for p in sorted(THEMES_DIR.glob("*.json")):
        t = Theme.model_validate(json.loads(p.read_text()))
        out[t.slug] = t
    return out


def get(slug: str) -> Theme:
    themes = all_themes()
    if slug not in themes:
        raise SystemExit(f"unknown theme '{slug}'. Available: {', '.join(themes)}")
    return themes[slug]


def contrast(a, b) -> float:
    """WCAG contrast ratio between two [r,g,b] colors (captions need >= 7 between stop 0.0 and 1.0)."""
    def lum(c):
        c = [x / 255 for x in c]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)
