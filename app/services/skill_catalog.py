"""Every skill a job can use: the built-ins enabled in config plus approved community skill packs (re-read
from the database at most once a minute). Also validates, submits and reviews packs."""
from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from app.core.config import Config
from app.core.errors import AppError, Conflict, NotFound
from app.dao.developers import SkillPackDAO
from app.design.color import contrast, ensure_contrast, parse_hex, to_hex
from app.design.system import TYPE_ROLES, DesignSystem
from app.skills.base import AUTO, Skill
from app.skills.packs import PackSkill, SkillPack

REVIEW = {"approve": "approved", "reject": "rejected", "retire": "retired"}


class SkillCatalog:
    def __init__(self, config: Config, builtins: dict[str, Skill], packs: SkillPackDAO, design: DesignSystem):
        self.config, self.builtins, self.packs, self.design = config, builtins, packs, design
        self.ttl = float(config.get("developers.catalog_ttl_seconds", 60))
        self._community: dict[str, PackSkill] = {}
        self._loaded = 0.0

    # ---- lookup
    def _refresh(self) -> None:
        if time.time() - self._loaded < self.ttl:
            return
        community = {}
        for row in self.packs.approved():
            engine = self.builtins.get(row["engine"])
            if engine:
                community[row["code"]] = PackSkill(row["pack"], engine, self.pack_brief)
        self._community, self._loaded = community, time.time()

    def invalidate(self) -> None:
        self._loaded = 0.0

    def all(self) -> dict[str, Skill]:
        self._refresh()
        return {**self.builtins, **self._community}

    def get(self, code: str) -> Skill:
        skill = self.all().get(code)
        if not skill:
            raise NotFound(f"unknown style '{code}'")
        return skill

    def themes(self) -> dict[str, list[str]]:
        configured = self.config.get("skills.themes") or {}
        out = {code: list(configured.get(code) or [AUTO]) for code in self.builtins}
        out.update({code: [AUTO, *s.themes] for code, s in self._community.items()})
        return out

    def options(self) -> list[dict]:
        self._refresh()
        out = [{"code": c, "name": c, "community": False, "engine": c} for c in self.builtins]
        out += [{"code": c, "name": s.pack["name"], "community": True, "engine": s.engine.code, "description": s.pack["description"]}
                for c, s in self._community.items()]
        return out

    # ---- packs
    def pack_brief(self, pack: dict, theme: dict) -> dict:
        """A pack theme in the design-brief shape the engines render (palette + fonts + type scale)."""
        raw = {"palette": {"name": theme["name"], "rationale": theme.get("description", ""),
                           **{r: {"hex": theme[r], "name": r} for r in ("dominant", "secondary", "accent")}},
               "type": {**{r: dict(pack["fonts"][r]) for r in TYPE_ROLES}, "scale_ratio": pack.get("scale_ratio", 1.333)},
               "positioning": pack["description"], "do": [], "dont": []}
        return self.design.finalize(raw, [], False)

    def validate_pack(self, raw: Any) -> dict:
        """{"ok", "errors", "warnings", "pack"}: contrast failures come with a suggested hex that passes."""
        errors: list[str] = []
        warnings: list[str] = []
        try:
            pack = SkillPack.model_validate(raw).model_dump()
        except ValidationError as e:
            return {"ok": False, "errors": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()][:20], "warnings": [], "pack": None}
        if pack["engine"] not in self.builtins:
            errors.append(f"engine must be one of: {', '.join(self.builtins)}")
        if pack["code"] in self.builtins:
            errors.append("code is taken by a built-in style")
        if len({t["slug"] for t in pack["themes"]}) != len(pack["themes"]):
            errors.append("theme slugs must be unique")
        for role in TYPE_ROLES:
            f = pack["fonts"].get(role)
            spec = self.design.fonts.get(f["family"]) if f else None
            if not f:
                errors.append(f"fonts.{role} is required")
            elif not spec or role not in spec["roles"]:
                ok = [n for n, s in self.design.fonts.items() if role in s["roles"]]
                errors.append(f"fonts.{role}: '{f['family']}' is not in the catalog for that role (use one of: {', '.join(ok)})")
            elif f["weight"] not in spec["weights"]:
                warnings.append(f"fonts.{role}: weight {f['weight']} is not installed; the nearest of {spec['weights']} will be used")
        lo_text, lo_acc = self.design.min_text, self.design.min_accent
        for t in pack["themes"]:
            d, s, a = (parse_hex(t[r]) for r in ("dominant", "secondary", "accent"))
            if contrast(s, d) < lo_text:
                errors.append(f"themes.{t['slug']}: secondary on dominant is {contrast(s, d):.1f}:1, needs {lo_text:g}:1 "
                              f"(try secondary {to_hex(ensure_contrast(s, d, lo_text))})")
            if contrast(a, d) < lo_acc:
                errors.append(f"themes.{t['slug']}: accent on dominant is {contrast(a, d):.1f}:1, needs {lo_acc:g}:1 "
                              f"(try accent {to_hex(ensure_contrast(a, d, lo_acc))})")
            if len({t['dominant'].upper(), t['secondary'].upper(), t['accent'].upper()}) < 3:
                errors.append(f"themes.{t['slug']}: dominant, secondary and accent must be three different colours")
        if not pack["planner_notes"].strip():
            warnings.append("planner_notes is empty: the style will use the engine's default writing rules")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "pack": pack}

    def submit(self, user: dict, raw: Any) -> dict:
        result = self.validate_pack(raw)
        if not result["ok"]:
            raise AppError("the skill pack has problems: " + "; ".join(result["errors"][:8]), code="invalid_pack")
        p = result["pack"]
        row = self.packs.upsert_pending(str(user["id"]), p["code"], p["engine"], p["name"], p)
        if not row:
            raise Conflict(f"the code '{p['code']}' belongs to another creator")
        return {"id": str(row["id"]), "code": row["code"], "status": row["status"], "warnings": result["warnings"]}

    def mine(self, user: dict) -> list[dict]:
        return [{**r, "id": str(r["id"]), "updated_at": r["updated_at"].isoformat()} for r in self.packs.for_owner(str(user["id"]))]

    def queue(self, status: str = "pending") -> list[dict]:
        return [{**r, "id": str(r["id"]), "updated_at": r["updated_at"].isoformat()} for r in self.packs.by_status(status)]

    def review(self, admin: dict, pack_id: str, decision: str, note: str = "") -> dict:
        if decision not in REVIEW:
            raise AppError(f"decision must be one of: {', '.join(REVIEW)}")
        row = self.packs.review(pack_id, REVIEW[decision], note[:500], str(admin["id"]))
        if not row:
            raise NotFound("skill pack not found")
        self.invalidate()
        return {**row, "id": str(row["id"])}
