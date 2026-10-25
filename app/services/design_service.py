"""Design briefs and research findings: applies the DesignSystem rules to what the agents return and stores
the results per job, so a later analysis agent can query them across jobs."""
from __future__ import annotations

from typing import Optional

from app.dao.design import DesignBriefDAO, FindingDAO
from app.db.pool import Database
from app.design.system import DesignSystem


class DesignService:
    def __init__(self, db: Database, system: DesignSystem, briefs: DesignBriefDAO, findings: FindingDAO):
        self.db, self.system, self.briefs, self.findings = db, system, briefs, findings

    def finalize(self, raw: dict, sources: list[dict], researched: bool) -> dict:
        return self.system.finalize(raw, sources, researched)

    def save_brief(self, job_id: str, request: dict, fmt: str, brief: dict) -> None:
        with self.db.transaction() as conn:
            self.briefs.save(job_id, request["skill"], fmt, brief, conn)
            self.findings.add_many(job_id, "design_director", request["problem"], brief["findings"], conn)

    def save_research(self, job_id: str, request: dict, research: dict, sources: list[dict]) -> int:
        """The Researcher's facts as findings; a fact is verified when its URL was actually retrieved."""
        retrieved = {s["url"] for s in sources}
        rows = []
        for f in research.get("facts") or []:
            if not isinstance(f, dict) or not str(f.get("fact", "")).strip():
                continue
            url = str(f.get("source_url") or "").strip()
            rows.append({"insight": str(f["fact"])[:400], "source_url": url[:500], "source_title": str(f.get("source_title") or "")[:200],
                         "confidence": f.get("confidence") if f.get("confidence") in ("high", "medium", "low") else "medium",
                         "verified": bool(url) and url in retrieved})
        self.findings.add_many(job_id, "researcher", request["problem"], rows)
        return len(rows)

    def for_job(self, job_id: str) -> Optional[dict]:
        brief = self.briefs.for_job(job_id)
        if brief is not None:
            brief = {**brief, "research": [f for f in self.findings.for_job(job_id) if f["agent"] == "researcher"]}
        return brief
