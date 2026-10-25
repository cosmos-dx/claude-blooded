"""Background worker: claims queued jobs (FOR UPDATE SKIP LOCKED, so several workers can run), runs the
reel workflow, refunds the credit on failure, deletes outputs after the retention window and runs the
daily Trend Scout.

usage: python -m app.workers.worker
"""
from __future__ import annotations

import os
import shutil
import socket
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core import logging as log
from app.core.container import get_container
from app.core.errors import AppError
from app.workflows.base import ReelContext, Workflow

logger = log.get("worker")


class Worker:
    def __init__(self):
        self.c = get_container()
        self.cfg = self.c.config
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self.retention = int(self.cfg.get("storage.retention_minutes", 30))
        self._last_maintenance = 0.0

    def process(self, job: dict) -> None:
        c = self.c
        jid = str(job["id"])
        req = job["request"]
        workdir = c.storage.workdir(jid)
        skill = c.catalog.get(req["skill"])
        ctx = ReelContext(job=job, request=req, tier=job["tier"], workdir=workdir, skill=skill, theme=req["theme"],
                          format=req.get("format", "9:16"))

        def on_event(stage, note, tally):
            c.job_events.add(jid, stage, note, tally.input_tokens, tally.output_tokens, tally.characters, tally.cost_inr)

        wf = Workflow(self.cfg.get("workflows.reel"), c.step_deps, lambda st, p: c.jobs.set_stage(jid, st, p), on_event)
        try:
            wf.run(ctx)
            for p in workdir.iterdir():                     # keep only the deliverables
                if p.name != "out":
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
            c.jobs.finish(jid, ctx.publish.get("title") or skill.title(ctx.spec), ctx.duration, ctx.publish, self.retention)
            logger.info("job %s done (%.1fs)", jid, ctx.duration)
        except Exception as e:  # noqa: BLE001 — any failure refunds the credit
            msg = e.message if isinstance(e, AppError) else "something went wrong while making the video"
            logger.error("job %s failed: %s\n%s", jid, e, traceback.format_exc())
            c.jobs.fail(jid, msg)
            c.credits.refund(job["pack_id"])
            c.job_events.add(jid, "failed", str(e)[:300])
            c.storage.delete(jid)

    def maintenance(self) -> None:
        c = self.c
        for job in c.jobs.expired_outputs():
            c.storage.delete(str(job["id"]))
            c.jobs.mark_expired(job["id"])
        for job in c.jobs.requeue_stale(int(self.cfg.get("worker.job_timeout_minutes", 60))):
            c.credits.refund(job["pack_id"])
            c.storage.delete(str(job["id"]))
        if self.cfg.get("trends.enabled"):
            now = datetime.now(ZoneInfo(self.cfg.get("app.timezone", "Asia/Kolkata")))
            if now.hour >= int(self.cfg.get("trends.run_hour_ist", 6)) and not c.trends.ran_today():
                self.run_trends()

    def run_trends(self) -> None:
        scout = self.c.agents["trend_scout"]
        popular = scout.youtube_popular()
        for niche in self.cfg.get("trends.niches") or []:
            try:
                with self.c.cost.scope(None):
                    self.c.trends.add(niche, scout.digest(niche, popular))
            except Exception as e:  # noqa: BLE001
                logger.warning("trend digest for %s failed: %s", niche, e)

    def loop(self) -> None:
        logger.info("worker %s started; LLM providers available: %s", self.id, self.c.router.available())
        poll = float(self.cfg.get("worker.poll_seconds", 3))
        while True:
            if time.time() - self._last_maintenance > 60:
                self._last_maintenance = time.time()
                try:
                    self.maintenance()
                except Exception as e:  # noqa: BLE001
                    logger.warning("maintenance failed: %s", e)
            job = self.c.jobs.claim_next(self.id)
            if job:
                self.process(job)
            else:
                time.sleep(poll)


if __name__ == "__main__":
    log.setup()
    Worker().loop()
