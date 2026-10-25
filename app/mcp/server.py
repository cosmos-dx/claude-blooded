"""MCP server for creators and developers: streamable HTTP at /mcp/, authenticated with a personal access token
(Authorization: Bearer <token>, created in the dashboard). Tools let a client browse the styles and design rules,
validate and submit data-only skill packs, review them (admins) and make reels with the caller's own credits."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.core.container import Container
from app.core.errors import AppError, Forbidden, Unauthorized
from app.skills.base import Look
from app.skills.packs import SkillPack

INSTRUCTIONS = """Make short explainer videos and add new visual styles.
Styles (skills) are listed by list_skills; get_skill shows the plan format and writing guide. New styles are
data-only skill packs on a built-in engine: read design_rules, check colours with check_contrast, run
validate_skill_pack until it returns ok, then submit_skill_pack. An admin reviews packs before they go live.
create_reel spends one of the caller's credits; poll get_reel until status is done."""


class _TokenVerifier:
    def __init__(self, c: Container):
        self.c = c

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        user = await anyio.to_thread.run_sync(self.c.developers.user_for_token, token)
        if not user:
            return None
        scopes = ["reels", "skills"] + (["admin"] if self.c.auth.is_admin(user) else [])
        return AccessToken(token=token, client_id=str(user["id"]), scopes=scopes, subject=user["email"])


def build(c: Container) -> FastMCP:
    cfg = c.config
    base = str(cfg.get("app.base_url")).rstrip("/")
    host = urlparse(base).netloc
    hosts = sorted({host, "127.0.0.1:*", "localhost:*", *(cfg.get("developers.mcp_extra_hosts") or [])})
    mcp = FastMCP(str(cfg.get("app.name")), instructions=INSTRUCTIONS, token_verifier=_TokenVerifier(c),
                  auth=AuthSettings(issuer_url=base, resource_server_url=f"{base}/mcp"),
                  stateless_http=True, json_response=True, streamable_http_path="/",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                                               allowed_origins=[base, "http://localhost:*", "http://127.0.0.1:*"]))

    def caller() -> tuple[dict, bool]:
        tok = get_access_token()
        if tok is None:
            raise Unauthorized("missing access token")
        user = c.users.by_id(tok.client_id)
        if not user:
            raise Unauthorized("unknown user")
        return user, "admin" in tok.scopes

    async def run(fn, *args) -> Any:
        """DB and service calls are synchronous: keep them off the event loop; errors become readable tool errors."""
        try:
            return await anyio.to_thread.run_sync(lambda: fn(*args))
        except AppError as e:
            raise ValueError(e.message) from e

    @mcp.tool()
    async def list_skills() -> dict:
        """All styles a reel can use (built-in and approved community packs), their themes ("auto" = the Design
        Director's palette for that reel), output formats and languages."""
        opts = await run(c.job_service.options)
        return {"skills": opts["skills"], "themes": opts["themes"], "formats": opts["formats"], "languages": opts["languages"],
                "lengths_seconds": opts["lengths"]}

    @mcp.tool()
    async def get_skill(code: str) -> dict:
        """One style in detail: its planner guide (the writing rules the scriptwriter follows) and the JSON schema of its plan."""
        skill = await run(c.catalog.get, code)
        look = Look(theme=skill.builtin_theme(""), format="9:16")
        return {"code": code, "contract": skill.contract, "guide": skill.guide(look), "spec_schema": skill.spec_schema(),
                "pack": getattr(skill, "pack", None)}

    @mcp.tool()
    async def design_rules() -> dict:
        """The design system every style follows: 60-30-10 colour and type splits, WCAG contrast floors, the installed
        font catalog with roles, the allowed type-scale ratios, the canvases, and the skill-pack JSON schema."""
        system = c.design.system
        return {**system.rules(), "fonts": list(system.fonts.values()), "formats": cfg.get("formats"),
                "skill_pack_schema": SkillPack.model_json_schema()}

    @mcp.tool()
    async def check_contrast(pairs: list[dict]) -> list[dict]:
        """WCAG contrast for [{"fg": "#hex", "bg": "#hex"}, ...]. Text needs 7:1 on its background here, accents 3:1."""
        from app.design.color import contrast, parse_hex
        out = []
        for p in pairs[:24]:
            try:
                out.append({**p, "ratio": round(contrast(parse_hex(p["fg"]), parse_hex(p["bg"])), 2)})
            except (KeyError, TypeError, ValueError) as e:
                out.append({**(p if isinstance(p, dict) else {}), "error": str(e)})
        return out

    @mcp.tool()
    async def validate_skill_pack(pack: dict) -> dict:
        """Check a skill pack without saving it. Returns ok, errors (with suggested fixes for contrast) and warnings."""
        caller()
        return await run(c.catalog.validate_pack, pack)

    @mcp.tool()
    async def submit_skill_pack(pack: dict) -> dict:
        """Submit (or update your own) skill pack for review. It goes live for everyone once an admin approves it."""
        user, _ = caller()
        return await run(c.catalog.submit, user, pack)

    @mcp.tool()
    async def my_skill_packs() -> list[dict]:
        """Your submitted skill packs and their review status."""
        user, _ = caller()
        return await run(c.catalog.mine, user)

    @mcp.tool()
    async def review_skill_packs(status: str = "pending") -> list[dict]:
        """Admins: skill packs waiting for review (or with another status: approved, rejected, retired)."""
        _, admin = caller()
        if not admin:
            raise ValueError(Forbidden("admins only").message)
        return await run(c.catalog.queue, status)

    @mcp.tool()
    async def review_skill_pack(pack_id: str, decision: str, note: str = "") -> dict:
        """Admins: approve, reject or retire a skill pack. Approved packs appear in every user's style list."""
        user, admin = caller()
        if not admin:
            raise ValueError(Forbidden("admins only").message)
        return await run(c.catalog.review, user, pack_id, decision, note)

    @mcp.tool()
    async def create_reel(problem: str, details: str = "", voice_prompt: str = "", language: str = "en-IN", seconds: int = 30,
                          skill: str = "", theme: str = "auto", format: str = "9:16") -> dict:
        """Queue a reel. Uses one of your credits that covers `seconds`. Returns the job; poll get_reel for progress."""
        user, _ = caller()
        req = {"problem": problem, "details": details, "voice_prompt": voice_prompt, "language": language, "seconds": seconds,
               "skill": skill or None, "theme": theme, "format": format}
        return await run(c.job_service.create, user, req)

    @mcp.tool()
    async def get_reel(job_id: str) -> dict:
        """A reel's status, stage log, design brief and, when done, download links (send the same bearer token)."""
        user, admin = caller()
        job = await run(c.job_service.get, user, job_id, admin)
        job["download_urls"] = {n: f"{base}/api/jobs/{job_id}/files/{n}" for n in job.get("files", [])}
        return job

    return mcp
