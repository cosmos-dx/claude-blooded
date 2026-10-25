"""Session tokens (JWT in an httpOnly cookie) and OTP helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import jwt

from app.core.config import Config
from app.core.errors import Unauthorized


class TokenService:
    def __init__(self, config: Config):
        self.secret = config.require("security.jwt_secret")
        if config.is_production and len(self.secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")
        self.hours = int(config.get("security.session_hours", 72))

    def issue(self, user_id: str, email: str) -> str:
        now = int(time.time())
        return jwt.encode({"sub": user_id, "email": email, "iat": now, "exp": now + self.hours * 3600}, self.secret, algorithm="HS256")

    def verify(self, token: str) -> dict:
        try:
            return jwt.decode(token, self.secret, algorithms=["HS256"])
        except jwt.PyJWTError as e:
            raise Unauthorized("session expired, please log in again") from e


def new_otp(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(email: str, code: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
