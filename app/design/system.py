"""DesignSystem: turns the Design Director's raw brief into one the renderers can trust. Every rule comes
from config (design.*): the 60-30-10 colour and type splits, WCAG contrast floors, the font catalog and the
allowed type-scale ratios. Fixes are applied, never silently: each one is listed in `adjustments`.
Raises ValueError for a brief that cannot be repaired, so the agent gets one repair turn."""
from __future__ import annotations

from typing import Any

from app.design.color import contrast, ensure_contrast, is_dark, parse_hex, to_hex

ROLES = ("dominant", "secondary", "accent")
TYPE_ROLES = ("display", "text", "accent")


class DesignSystem:
    def __init__(self, config):
        d = config.get("design") or {}
        self.color_split = [int(x) for x in d.get("color_split", [60, 30, 10])]
        self.type_split = [int(x) for x in d.get("type_split", [60, 30, 10])]
        self.min_text = float(d.get("min_text_contrast", 7.0))
        self.min_accent = float(d.get("min_accent_contrast", 3.0))
        self.scales = sorted(float(x) for x in d.get("type_scales", [1.25, 1.333, 1.5]))
        self.base_px = {k: int(v) for k, v in (d.get("base_text_px") or {"9:16": 24, "16:9": 26}).items()}
        self.fonts = {f["family"]: f for f in d.get("fonts") or []}

    # ---- what the agent is told
    def catalog_text(self) -> str:
        return "\n".join(f"- {f['family']} (weights {', '.join(map(str, f['weights']))}; roles {', '.join(f['roles'])}): {f['voice']}"
                         for f in self.fonts.values())

    def rules(self) -> dict[str, Any]:
        return {"color_split": self.color_split, "type_split": self.type_split, "min_text_contrast": self.min_text,
                "min_accent_contrast": self.min_accent, "type_scales": self.scales}

    # ---- validation and repair
    def finalize(self, raw: dict, sources: list[dict], researched: bool) -> dict:
        notes: list[str] = []
        palette = self._palette(raw.get("palette") or {}, notes)
        type_ = self._type(raw.get("type") or {}, notes)
        retrieved = {s["url"] for s in sources}
        findings = []
        for f in (raw.get("findings") or [])[:10]:
            if not isinstance(f, dict) or not str(f.get("insight", "")).strip():
                continue
            url = str(f.get("source_url") or "").strip()
            findings.append({"insight": str(f["insight"])[:400], "source_url": url[:500], "source_title": str(f.get("source_title") or "")[:200],
                             "confidence": f.get("confidence") if f.get("confidence") in ("high", "medium", "low") else "medium",
                             "verified": bool(url) and url in retrieved})
        motion = raw.get("motion") or {}
        return {
            "positioning": str(raw.get("positioning", ""))[:300], "audience": str(raw.get("audience", ""))[:300],
            "mood": [str(m)[:30] for m in (raw.get("mood") or [])][:5],
            "palette": palette, "type": type_,
            "motion": {"pace": motion.get("pace") if motion.get("pace") in ("calm", "steady", "punchy") else "steady",
                       "cuts": str(motion.get("cuts", ""))[:200], "notes": str(motion.get("notes", ""))[:300]},
            "layout": {k: str(v)[:300] for k, v in (raw.get("layout") or {}).items() if k in self.base_px},
            "do": [str(x)[:160] for x in (raw.get("do") or [])][:6], "dont": [str(x)[:160] for x in (raw.get("dont") or [])][:6],
            "findings": findings, "sources": sources[:20],
            "research_mode": "web" if researched else "offline", "adjustments": notes,
        }

    def _palette(self, raw: dict, notes: list[str]) -> dict:
        swatches = {}
        for role, share in zip(ROLES, self.color_split):
            sw = raw.get(role)
            if not isinstance(sw, dict) or not sw.get("hex"):
                raise ValueError(f"palette.{role}.hex is required")
            swatches[role] = {"hex": to_hex(parse_hex(sw["hex"])), "name": str(sw.get("name", ""))[:40],
                              "why": str(sw.get("why", ""))[:240], "share": share}
        d, s, a = (parse_hex(swatches[r]["hex"]) for r in ROLES)
        s2 = ensure_contrast(s, d, self.min_text)
        if s2 != s:
            notes.append(f"secondary {to_hex(s)} → {to_hex(s2)}: {contrast(s, d):.1f}:1 on the dominant colour is below {self.min_text:g}:1")
            swatches["secondary"]["hex"] = to_hex(s2)
        a2 = ensure_contrast(a, d, self.min_accent)
        if a2 != a:
            notes.append(f"accent {to_hex(a)} → {to_hex(a2)}: {contrast(a, d):.1f}:1 on the dominant colour is below {self.min_accent:g}:1")
            swatches["accent"]["hex"] = to_hex(a2)
        d, s, a = (parse_hex(swatches[r]["hex"]) for r in ROLES)
        return {"name": str(raw.get("name", ""))[:40] or "Designer's pick", "rationale": str(raw.get("rationale", ""))[:400],
                **swatches, "dark": is_dark(d),
                "contrast": {"secondary_on_dominant": round(contrast(s, d), 2), "accent_on_dominant": round(contrast(a, d), 2),
                             "secondary_on_accent": round(contrast(s, a), 2), "dominant_on_accent": round(contrast(d, a), 2)}}

    def _type(self, raw: dict, notes: list[str]) -> dict:
        out: dict[str, Any] = {}
        for role, share in zip(TYPE_ROLES, self.type_split):
            want = raw.get(role) if isinstance(raw.get(role), dict) else {}
            fam = str(want.get("family", "")).strip().lower().replace(" ", "-")
            if fam not in self.fonts or role not in self.fonts[fam]["roles"]:
                fallback = next((f for f, spec in self.fonts.items() if role in spec["roles"]), None)
                if fallback is None:
                    raise ValueError(f"no font in the catalog can play the {role} role")
                notes.append(f"{role} font '{fam or '?'}' is not installed for that role → {fallback}")
                fam = fallback
            weights = self.fonts[fam]["weights"]
            try:
                asked = int(want.get("weight", weights[0]))
            except (TypeError, ValueError):
                asked = weights[0]
            weight = min(weights, key=lambda w: abs(w - asked))
            out[role] = {"family": fam, "weight": weight, "share": share, "why": str(want.get("why", ""))[:200]}
        try:
            asked_ratio = float(raw.get("scale_ratio", 1.333))
        except (TypeError, ValueError):
            asked_ratio = 1.333
        ratio = min(self.scales, key=lambda r: abs(r - asked_ratio))
        out["scale_ratio"] = ratio
        out["sizes"] = {fmt: {"label": round(base / ratio), "caption": base, "subhead": round(base * ratio ** 2),
                              "headline_min": round(base * ratio ** 4)} for fmt, base in self.base_px.items()}
        out["rationale"] = str(raw.get("rationale", ""))[:400]
        return out
