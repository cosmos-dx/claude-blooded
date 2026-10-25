from __future__ import annotations

from fastapi import Request

from app.core.container import Container, get_container
from app.core.errors import Forbidden, Unauthorized


def container() -> Container:
    return get_container()


def current_user(request: Request) -> dict:
    c = get_container()
    token = request.cookies.get(c.config.get("security.cookie_name", "hr_session"))
    if not token:
        raise Unauthorized("please log in")
    return c.auth.user_from_token(token)


def admin_user(request: Request) -> dict:
    user = current_user(request)
    if not get_container().auth.is_admin(user):
        raise Forbidden("admins only")
    return user
