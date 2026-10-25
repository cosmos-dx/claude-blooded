"""Design briefs and research findings (SQL only)."""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from app.dao.base import BaseDAO


class DesignBriefDAO(BaseDAO):
    def save(self, job_id: str, skill: str, fmt: str, brief: dict, conn=None) -> None:
        p, t = brief["palette"], brief["type"]
        self.run("""INSERT INTO design_briefs (job_id, skill, format, research_mode, dominant_hex, secondary_hex, accent_hex,
                                               display_font, text_font, accent_font, brief)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id) DO UPDATE SET brief = EXCLUDED.brief, research_mode = EXCLUDED.research_mode,
                        dominant_hex = EXCLUDED.dominant_hex, secondary_hex = EXCLUDED.secondary_hex, accent_hex = EXCLUDED.accent_hex,
                        display_font = EXCLUDED.display_font, text_font = EXCLUDED.text_font, accent_font = EXCLUDED.accent_font""",
                 (job_id, skill, fmt, brief["research_mode"], p["dominant"]["hex"], p["secondary"]["hex"], p["accent"]["hex"],
                  t["display"]["family"], t["text"]["family"], t["accent"]["family"], Jsonb(brief)), conn)

    def for_job(self, job_id: str, conn=None) -> Optional[dict]:
        row = self.one("SELECT brief FROM design_briefs WHERE job_id = %s", (job_id,), conn)
        return row["brief"] if row else None


class FindingDAO(BaseDAO):
    def add_many(self, job_id: Optional[str], agent: str, topic: str, findings: list[dict], conn=None) -> None:
        for f in findings:
            self.run("""INSERT INTO research_findings (job_id, agent, topic, insight, source_url, source_title, confidence, verified)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                     (job_id, agent, topic[:500], f["insight"], f.get("source_url") or None, f.get("source_title") or None,
                      f.get("confidence", "medium"), bool(f.get("verified"))), conn)

    def for_job(self, job_id: str, conn=None) -> list[dict]:
        return self.all("""SELECT agent, insight, source_url, source_title, confidence, verified FROM research_findings
                           WHERE job_id = %s ORDER BY agent, created_at""", (job_id,), conn)
