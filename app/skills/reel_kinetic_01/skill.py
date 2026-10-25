"""reel-kinetic-01: bold color-block kinetic typography (huge condensed headlines, tiny mono follow-ups, stickers)."""
from __future__ import annotations

import json
from pathlib import Path

from app.design.color import contrast, parse_hex
from app.skills.base import SKILLS, Look, Progress, Skill
from app.skills.reel_kinetic_01.renderer import PALETTES

DEFAULT_PALETTE = next(name for name in PALETTES if not name.startswith("_"))


def brief_palette(brief: dict) -> dict:
    """The Design Director's 60-30-10 colours as kinetic pairs [background, foreground, accent]:
    ds = dominant ground + secondary type (the default), sd = the inverse, ad = accent ground for punchlines,
    typed in whichever of the other two reads better on it."""
    p = brief["palette"]
    d, s, a = (list(parse_hex(p[r]["hex"])) for r in ("dominant", "secondary", "accent"))
    on_a, other = (d, s) if contrast(d, a) >= contrast(s, a) else (s, d)
    return {"description": f"{p['name']}: designed for this reel", "pairs": {"ds": [d, s, a], "sd": [s, d, a], "ad": [a, on_a, other]}}


@SKILLS.register("reel-kinetic-01")
class ReelKinetic01(Skill):
    code = "reel-kinetic-01"
    contract = "plan_kinetic"

    def builtin_theme(self, theme: str) -> str:
        return theme if theme in PALETTES and not theme.startswith("_") else DEFAULT_PALETTE

    def validate(self, data: dict, look: Look) -> dict:
        from app.skills.reel_kinetic_01.spec import KineticSpec
        if look.designed:
            name, palette = "brief", brief_palette(look.brief)
        else:
            name = self.builtin_theme(look.theme)
            palette = PALETTES[name]
        spec = KineticSpec.model_validate({**data, "palette": name}).model_dump()
        codes = list(palette["pairs"])
        beats = [b for line in spec["lines"] for b in line["beats"]]
        for i, b in enumerate(beats):                   # repair rather than reject: unknown pairs cycle the palette
            if b["pair"] not in codes:
                b["pair"] = codes[i % len(codes)]
        spec["format"] = look.format
        if look.designed:
            t = look.brief["type"]
            spec["custom_palette"] = palette
            spec["split"] = [look.brief["palette"][r]["share"] for r in ("dominant", "secondary", "accent")]
            face = lambda role: f"{t[role]['family']}/{t[role]['weight']}"
            spec["fonts"] = {"display": face("display"), "text": face("text"), "label": face("accent"), "sticker": face("accent")}
            sizes = (t.get("sizes") or {}).get(look.format) or {}
            spec["sizes"] = {k: sizes[k] for k in ("caption", "label") if k in sizes}
        return spec

    def spec_schema(self) -> dict:
        from app.skills.reel_kinetic_01.spec import KineticSpec
        return KineticSpec.model_json_schema()

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

    def render(self, workdir: Path, spec: dict, look: Look, progress: Progress, processes: int) -> Path:
        from app.skills.reel_kinetic_01 import renderer
        (workdir / "spec.json").write_text(json.dumps({**spec, "format": look.format}))
        renderer.render(str(workdir), progress, processes)
        return workdir / "video_silent.mp4"

    def guide(self, look: Look) -> str:
        if look.designed:
            p = look.brief["palette"]
            sw = lambda r: f"{p[r]['name']} {p[r]['hex']}"
            palettes = (f"- brief ({p['name']}): dominant {sw('dominant')}, secondary {sw('secondary')}, accent {sw('accent')}.\n"
                        "  Pairs: ds (dominant ground, secondary type: most beats), sd (secondary ground, dominant type), "
                        "ad (accent ground: only the punchline or the call to action). The renderer balances them 60-30-10 by screen time.")
        else:
            palettes = "\n".join(f"- {name}: {p['description']} Pairs: {', '.join(p['pairs'])}" for name, p in PALETTES.items() if not name.startswith("_"))
        return super().guide(look).replace("{palettes}", palettes)
