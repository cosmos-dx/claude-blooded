from __future__ import annotations

from fastapi import Request

from app.core.container import Container, get_container
from app.core.errors import Forbidden, Unauthorized


def container() -> Container:
    return get_container()


def current_user(request: Request) -> dict:
    """The browser session cookie, or a personal access token (Authorization: Bearer ...) for scripts and MCP clients."""
    c = get_container()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = c.developers.user_for_token(auth[7:].strip())
        if not user:
            raise Unauthorized("invalid or revoked access token")
        return user
    token = request.cookies.get(c.config.get("security.cookie_name", "hr_session"))
    if not token:
        raise Unauthorized("please log in")
    return c.auth.user_from_token(token)


def admin_user(request: Request) -> dict:
    user = current_user(request)
    if not get_container().auth.is_admin(user):
        raise Forbidden("admins only")
    return user
