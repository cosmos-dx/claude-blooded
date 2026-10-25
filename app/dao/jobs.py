"""Jobs (the work queue), their per-stage events, provider usage and trend digests."""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from app.dao.base import BaseDAO


class JobDAO(BaseDAO):
    def create(self, user_id: str, pack: dict, request: dict, conn=None) -> dict:
        return self.one("""INSERT INTO jobs (user_id, pack_id, request, tier, max_seconds)
                           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                        (user_id, pack["id"], Jsonb(request), pack["tier"], pack["max_seconds"]), conn)

    def get(self, job_id: str, conn=None) -> Optional[dict]:
        return self.one("SELECT * FROM jobs WHERE id = %s", (job_id,), conn)

    def for_user(self, user_id: str, limit: int = 30, conn=None) -> list[dict]:
        return self.all("SELECT * FROM jobs WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user_id, limit), conn)

    def running_count(self, user_id: str, conn=None) -> int:
        return int(self.scalar("SELECT count(*) FROM jobs WHERE user_id = %s AND status IN ('queued','running')", (user_id,), conn) or 0)

    def claim_next(self, worker_id: str, conn=None) -> Optional[dict]:
        """Atomically take the oldest queued job (safe with many workers)."""
        return self.one("""UPDATE jobs SET status = 'running', stage = 'starting', started_at = now(), locked_by = %s, attempts = attempts + 1
                           WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at
                                       FOR UPDATE SKIP LOCKED LIMIT 1)
                           RETURNING *""", (worker_id,), conn)

    def set_stage(self, job_id: str, stage: str, progress: float, conn=None) -> None:
        self.run("UPDATE jobs SET stage = %s, progress = %s WHERE id = %s", (stage, progress, job_id), conn)

    def finish(self, job_id: str, title: str, duration_s: float, publish_pack: dict, retention_minutes: int, conn=None) -> None:
        self.run("""UPDATE jobs SET status = 'done', stage = 'done', progress = 1, title = %s, duration_s = %s, publish_pack = %s,
                    finished_at = now(), expires_at = now() + make_interval(mins => %s) WHERE id = %s""",
                 (title, duration_s, Jsonb(publish_pack), retention_minutes, job_id), conn)

    def fail(self, job_id: str, error: str, conn=None) -> None:
        self.run("UPDATE jobs SET status = 'failed', stage = 'failed', error = %s, finished_at = now() WHERE id = %s",
                 (error[:500], job_id), conn)

    def requeue_stale(self, timeout_minutes: int, conn=None) -> list[dict]:
        """Jobs whose worker died: mark failed so their credit can be refunded."""
        return self.all("""UPDATE jobs SET status = 'failed', stage = 'failed', error = 'worker timeout', finished_at = now()
                           WHERE status = 'running' AND started_at < now() - make_interval(mins => %s) RETURNING *""",
                        (timeout_minutes,), conn)

    def expired_outputs(self, conn=None) -> list[dict]:
        return self.all("SELECT id FROM jobs WHERE status = 'done' AND expires_at < now()", (), conn)

    def mark_expired(self, job_id: str, conn=None) -> None:
        self.run("UPDATE jobs SET status = 'expired' WHERE id = %s", (job_id,), conn)

    def stats(self, days: int, conn=None) -> list[dict]:
        return self.all("""SELECT status, count(*)::int AS n FROM jobs WHERE created_at > now() - make_interval(days => %s)
                           GROUP BY status""", (days,), conn)


class JobEventDAO(BaseDAO):
    def add(self, job_id: str, stage: str, message: str = "", input_tokens: int = 0, output_tokens: int = 0,
            characters: int = 0, cost_inr: float = 0.0, conn=None) -> None:
        self.run("""INSERT INTO job_events (job_id, stage, message, input_tokens, output_tokens, characters, cost_inr)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (job_id, stage, message[:300], input_tokens, output_tokens, characters, round(cost_inr, 2)), conn)

    def for_job(self, job_id: str, conn=None) -> list[dict]:
        return self.all("SELECT stage, message, input_tokens, output_tokens, characters, cost_inr, created_at FROM job_events WHERE job_id = %s ORDER BY id",
                        (job_id,), conn)


class UsageDAO(BaseDAO):
    def add(self, row: dict, conn=None) -> None:
        self.run("""INSERT INTO usage_ledger (job_id, kind, provider, model, role, input_tokens, output_tokens, cache_read, cache_write,
                    characters, cost_usd, cost_inr) VALUES (%(job_id)s, %(kind)s, %(provider)s, %(model)s, %(role)s, %(input_tokens)s,
                    %(output_tokens)s, %(cache_read)s, %(cache_write)s, %(characters)s, %(cost_usd)s, %(cost_inr)s)""",
                 {"job_id": None, "role": None, "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0,
                  "characters": 0, **row}, conn)

    def job_total(self, job_id: str, conn=None) -> dict:
        return self.one("""SELECT coalesce(sum(cost_inr), 0)::float AS inr, coalesce(sum(cost_usd), 0)::float AS usd,
                           coalesce(sum(input_tokens), 0)::int AS input_tokens, coalesce(sum(output_tokens), 0)::int AS output_tokens,
                           coalesce(sum(characters), 0)::int AS characters FROM usage_ledger WHERE job_id = %s""", (job_id,), conn)

    def spend_by_provider(self, days: int, conn=None) -> list[dict]:
        return self.all("""SELECT kind, provider, model, count(*)::int AS calls, sum(input_tokens)::int AS input_tokens,
                           sum(output_tokens)::int AS output_tokens, sum(characters)::int AS characters, sum(cost_inr)::float AS inr
                           FROM usage_ledger WHERE created_at > now() - make_interval(days => %s)
                           GROUP BY kind, provider, model ORDER BY inr DESC""", (days,), conn)

    def spend_today(self, conn=None) -> float:
        return float(self.scalar("SELECT coalesce(sum(cost_inr), 0) FROM usage_ledger WHERE created_at > date_trunc('day', now())", (), conn) or 0)


class TrendDAO(BaseDAO):
    def add(self, niche: str, digest: dict, conn=None) -> None:
        self.run("INSERT INTO trend_digests (niche, digest) VALUES (%s, %s)", (niche, Jsonb(digest)), conn)

    def latest(self, conn=None) -> list[dict]:
        return self.all("""SELECT DISTINCT ON (niche) niche, digest, created_at FROM trend_digests
                           WHERE created_at > now() - interval '3 days' ORDER BY niche, created_at DESC""", (), conn)

    def ran_today(self, conn=None) -> bool:
        return bool(self.scalar("SELECT count(*) FROM trend_digests WHERE created_at > date_trunc('day', now())", (), conn))
