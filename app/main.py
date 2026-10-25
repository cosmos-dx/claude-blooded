"""ASGI entry point: uvicorn app.main:app"""
from __future__ import annotations

import html
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api
from app.core import logging as log
from app.core.config import ROOT
from app.core.container import get_container
from app.core.errors import AppError

WEB = ROOT / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.setup()
    c = get_container()
    try:
        c.plans.sync()                  # mirror config plans into the DB
    except Exception as e:  # noqa: BLE001 — pages still serve; API calls needing the DB will fail until it is reachable
        log.get("startup").error("database not ready: %s", e)
    async with app.state.mcp.session_manager.run():     # the MCP server mounted at /mcp/
        yield
    c.db.close()


@lru_cache(maxsize=None)
def page(name: str) -> str:
    """A web/ page with {{brand}} and {{contact}} filled from config (rendered once per process)."""
    cfg = get_container().config
    brand = html.escape(str(cfg.get("app.name")))
    email = html.escape(str(cfg.get("app.support_email") or ""))
    contact = f'<span>Questions? <a href="mailto:{email}">{email}</a></span>' if email else ""
    return (WEB / name).read_text().replace("{{brand}}", brand).replace("{{contact}}", contact)


def create_app() -> FastAPI:
    app = FastAPI(title=str(get_container().config.get("app.name")), docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    from app.mcp.server import build
    app.state.mcp = build(get_container())
    app.include_router(api)
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
    app.mount("/mcp", app.state.mcp.streamable_http_app())

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"error": exc.message, "code": exc.code}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.get("api").exception("unhandled error: %s", exc)
        return JSONResponse({"error": "something went wrong, please try again", "code": "server_error"}, status_code=500)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    for path, fname in (("/", "index.html"), ("/app", "app.html"), ("/admin", "admin.html")):
        app.add_api_route(path, (lambda f=fname: HTMLResponse(page(f))), methods=["GET"], include_in_schema=False)
    return app


app = create_app()
