"""ASGI entry point: uvicorn app.main:app"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api
from app.core import logging as log
from app.core.config import ROOT
from app.core.container import get_container
from app.core.errors import AppError

WEB = ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.setup()
    c = get_container()
    try:
        c.plans.sync()                  # mirror config plans into the DB
    except Exception as e:  # noqa: BLE001 — pages still serve; API calls needing the DB will fail until it is reachable
        log.get("startup").error("database not ready: %s", e)
    yield
    c.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Hireish Reels", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(api)
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

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

    for path, page in (("/", "index.html"), ("/app", "app.html"), ("/admin", "admin.html")):
        app.add_api_route(path, (lambda p=page: FileResponse(WEB / p)), methods=["GET"], include_in_schema=False)
    return app


app = create_app()
