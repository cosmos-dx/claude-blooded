"""HTTP routes. Each handler validates input, calls one service method and shapes the response —
no business rules here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import admin_user, container, current_user
from app.core.container import Container
from app.payments.gateways import PaymentProof

api = APIRouter(prefix="/api")


# ---------------------------------------------------------------- auth
class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class VerifyIn(EmailIn):
    code: str = Field(min_length=4, max_length=10)


@api.post("/auth/code")
def send_code(body: EmailIn, c: Container = Depends(container)):
    c.auth.send_code(body.email)
    return {"sent": True}


@api.post("/auth/verify")
def verify(body: VerifyIn, response: Response, c: Container = Depends(container)):
    user, token = c.auth.verify_code(body.email, body.code)
    response.set_cookie(c.config.get("security.cookie_name", "hr_session"), token, httponly=True, samesite="lax",
                        secure=bool(c.config.get("security.cookie_secure", True)),
                        max_age=int(c.config.get("security.session_hours", 72)) * 3600)
    return {"email": user["email"]}


@api.post("/auth/logout")
def logout(response: Response, c: Container = Depends(container)):
    response.delete_cookie(c.config.get("security.cookie_name", "hr_session"))
    return {"ok": True}


@api.get("/me")
def me(user: dict = Depends(current_user), c: Container = Depends(container)):
    return {"email": user["email"], "is_admin": c.auth.is_admin(user), "credits": c.credits.summary(user["id"])}


# ---------------------------------------------------------------- catalog
@api.get("/catalog")
def catalog(c: Container = Depends(container)):
    return {"app": c.config.get("app.name"), "plans": c.plans.public(), "options": c.job_service.options(),
            "signup_grant": c.config.get("signup_grant"), "payments": c.gateway.name}


# ---------------------------------------------------------------- payments
class CheckoutIn(BaseModel):
    plan: str = Field(max_length=32)


class ConfirmIn(BaseModel):
    order_id: str = Field(max_length=80)
    payment_id: str = Field(max_length=80)
    signature: str = Field(max_length=200)


@api.post("/checkout")
def checkout(body: CheckoutIn, user: dict = Depends(current_user), c: Container = Depends(container)):
    return c.payments.start_checkout(user, body.plan)


@api.post("/checkout/confirm")
def confirm(body: ConfirmIn, user: dict = Depends(current_user), c: Container = Depends(container)):
    return c.payments.confirm(user, PaymentProof(body.order_id, body.payment_id, body.signature))


@api.post("/webhooks/{gateway}")
async def webhook(gateway: str, request: Request, c: Container = Depends(container)):
    if gateway != c.gateway.name:
        return {"status": "ignored"}
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature") or request.headers.get("x-signature") or ""
    return c.payments.webhook(body, signature)


# ---------------------------------------------------------------- jobs
class JobIn(BaseModel):
    problem: str = Field(max_length=2000)
    details: str = Field(default="", max_length=2000)
    voice_prompt: str = Field(default="", max_length=2000)
    language: str = Field(default="en-IN", max_length=10)
    skill: str = Field(default="", max_length=40)
    theme: str = Field(default="", max_length=40)
    seconds: int = Field(default=30, ge=10, le=600)
    narrator: str = Field(default="female", max_length=10)


@api.post("/jobs")
def create_job(body: JobIn, user: dict = Depends(current_user), c: Container = Depends(container)):
    return c.job_service.create(user, body.model_dump())


@api.get("/jobs")
def list_jobs(user: dict = Depends(current_user), c: Container = Depends(container)):
    return c.job_service.list(user)


@api.get("/jobs/{job_id}")
def get_job(job_id: str, user: dict = Depends(current_user), c: Container = Depends(container)):
    show = c.auth.is_admin(user) or bool(c.config.get("ui.show_costs_to_users"))
    return c.job_service.get(user, job_id, show)


@api.get("/jobs/{job_id}/files/{name}")
def job_file(job_id: str, name: str, request: Request, user: dict = Depends(current_user), c: Container = Depends(container)):
    path, job = c.job_service.file(user, job_id, name)
    slug = (job.get("title") or "reel").lower().replace(" ", "-")[:40]
    inline = request.query_params.get("inline") == "1"
    return FileResponse(path, filename=None if inline else f"{slug}-{name}", headers={"Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- developers (personal access tokens, skill packs)
class TokenIn(BaseModel):
    name: str = Field(default="", max_length=60)


@api.get("/tokens")
def list_tokens(user: dict = Depends(current_user), c: Container = Depends(container)):
    return {"tokens": c.developers.list_tokens(user), "mcp_url": f"{str(c.config.get('app.base_url')).rstrip('/')}/mcp/"}


@api.post("/tokens")
def create_token(body: TokenIn, user: dict = Depends(current_user), c: Container = Depends(container)):
    return c.developers.create_token(user, body.name)


@api.delete("/tokens/{token_id}")
def revoke_token(token_id: str, user: dict = Depends(current_user), c: Container = Depends(container)):
    c.developers.revoke(user, token_id)
    return {"ok": True}


@api.get("/skill-packs")
def my_packs(user: dict = Depends(current_user), c: Container = Depends(container)):
    return {"packs": c.catalog.mine(user)}


# ---------------------------------------------------------------- admin
class ReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|retire)$")
    note: str = Field(default="", max_length=500)


@api.get("/admin/summary")
def admin_summary(days: int = 30, _: dict = Depends(admin_user), c: Container = Depends(container)):
    return c.admin.summary(days)


@api.get("/admin/skill-packs")
def pack_queue(status: str = "pending", _: dict = Depends(admin_user), c: Container = Depends(container)):
    return {"packs": c.catalog.queue(status)}


@api.post("/admin/skill-packs/{pack_id}/review")
def review_pack(pack_id: str, body: ReviewIn, admin: dict = Depends(admin_user), c: Container = Depends(container)):
    return c.catalog.review(admin, pack_id, body.decision, body.note)


@api.get("/healthz")
def health():
    return {"ok": True}
