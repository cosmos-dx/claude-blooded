"""Reel jobs: validate a request, take one credit atomically, queue it; expose progress, stage costs and files."""
from __future__ import annotations

from app.core.config import Config
from app.core.errors import AppError, NotFound, PaymentRequired, TooManyRequests
from app.dao.commerce import CreditDAO
from app.dao.jobs import JobDAO, JobEventDAO, UsageDAO
from app.db.pool import Database
from app.services.design_service import DesignService
from app.services.skill_catalog import SkillCatalog
from app.storage.stores import Storage


class JobService:
    def __init__(self, config: Config, db: Database, jobs: JobDAO, events: JobEventDAO, usage: UsageDAO, credits: CreditDAO,
                 storage: Storage, catalog: SkillCatalog, design: DesignService):
        self.config, self.db, self.jobs, self.events, self.usage, self.credits, self.storage = config, db, jobs, events, usage, credits, storage
        self.catalog, self.design = catalog, design
        self.formats = [f["code"] for f in config.get("formats") or []] or ["9:16"]
        self.languages = {l["code"] for l in (config.get("tts.languages") or [])}
        self.max_chars = int(config.get("limits.prompt_max_chars", 1500))
        self.max_running = int(config.get("limits.jobs_running_per_user", 2))

    def options(self) -> dict:
        return {"skills": self.catalog.options(), "themes": self.catalog.themes(), "languages": self.config.get("tts.languages") or [],
                "formats": self.config.get("formats") or [],
                "lengths": sorted({int(p["max_seconds"]) for p in (self.config.get("plans") or [])})}

    def _clean(self, req: dict) -> dict:
        problem = (req.get("problem") or "").strip()
        if len(problem) < 10:
            raise AppError("describe the topic or problem in at least a sentence")
        for k in ("problem", "details", "voice_prompt"):
            if len(req.get(k) or "") > self.max_chars:
                raise AppError(f"{k.replace('_', ' ')} is too long (max {self.max_chars} characters)")
        skill = req.get("skill") or self.config.get("skills.default")
        themes = self.catalog.themes()
        if skill not in self.catalog.all():
            raise AppError("unknown style")
        theme = req.get("theme") or (themes.get(skill) or [None])[0]
        if theme not in (themes.get(skill) or [theme]):
            raise AppError("unknown theme for this style")
        language = req.get("language") or "en-IN"
        if language not in self.languages:
            raise AppError("unsupported language")
        seconds = int(req.get("seconds") or 30)
        fmt = req.get("format") or self.formats[0]
        if fmt not in self.formats:
            raise AppError("unsupported format")
        return {"problem": problem, "details": (req.get("details") or "").strip(), "voice_prompt": (req.get("voice_prompt") or "").strip(),
                "language": language, "skill": skill, "theme": theme, "format": fmt, "seconds": seconds,
                "narrator": "male" if req.get("narrator") == "male" else "female"}

    def create(self, user: dict, req: dict) -> dict:
        clean = self._clean(req)
        if self.jobs.running_count(user["id"]) >= self.max_running:
            raise TooManyRequests(f"you already have {self.max_running} videos in progress")
        with self.db.transaction() as conn:
            pack = self.credits.reserve(user["id"], clean["seconds"], conn)
            if not pack:
                raise PaymentRequired(f"no credits left for a {clean['seconds']}-second video; pick a plan to continue")
            job = self.jobs.create(user["id"], pack, clean, conn=conn)
        return self.view(job, with_events=False)

    def list(self, user: dict) -> list[dict]:
        return [self.view(j, with_events=False) for j in self.jobs.for_user(user["id"])]

    def get(self, user: dict, job_id: str, show_costs: bool) -> dict:
        job = self.jobs.get(job_id)
        if not job or str(job["user_id"]) != str(user["id"]):
            raise NotFound("video not found")
        return self.view(job, with_events=True, show_costs=show_costs)

    def file(self, user: dict, job_id: str, name: str):
        job = self.jobs.get(job_id)
        if not job or str(job["user_id"]) != str(user["id"]) or job["status"] != "done":
            raise NotFound("file not found")
        path = self.storage.output(job_id, name)
        if not path:
            raise NotFound("file expired or not found")
        return path, job

    def view(self, job: dict, with_events: bool, show_costs: bool = False) -> dict:
        out = {k: job[k] for k in ("status", "stage", "progress", "title", "duration_s", "error", "tier", "max_seconds")}
        out.update(id=str(job["id"]), request=job["request"], publish_pack=job.get("publish_pack"),
                   created_at=job["created_at"].isoformat(), expires_at=job["expires_at"].isoformat() if job.get("expires_at") else None,
                   files=self.config.get("storage.files") if job["status"] == "done" else [])
        if with_events:
            out["design"] = self.design.for_job(str(job["id"]))
            events = self.events.for_job(job["id"])
            out["events"] = [{"stage": e["stage"], "message": e["message"], "at": e["created_at"].isoformat(),
                              **({"input_tokens": e["input_tokens"], "output_tokens": e["output_tokens"], "characters": e["characters"],
                                  "cost_inr": float(e["cost_inr"])} if show_costs else {})} for e in events]
            if show_costs:
                out["cost"] = self.usage.job_total(job["id"])
        return out
