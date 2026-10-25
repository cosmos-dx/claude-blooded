"""Personal access tokens for the MCP server and the REST API. Tokens are random, shown once, stored as sha256."""
from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from app.core.config import Config
from app.core.errors import AppError, NotFound
from app.dao.developers import ApiTokenDAO


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DeveloperService:
    def __init__(self, config: Config, tokens: ApiTokenDAO):
        self.tokens = tokens
        self.prefix = str(config.get("developers.token_prefix", "rk_"))
        self.max_tokens = int(config.get("developers.max_tokens_per_user", 10))

    def create_token(self, user: dict, name: str) -> dict:
        name = (name or "").strip()[:60] or "token"
        if len(self.tokens.for_user(str(user["id"]))) >= self.max_tokens:
            raise AppError(f"you can have at most {self.max_tokens} tokens; revoke one first")
        token = self.prefix + secrets.token_urlsafe(32)
        row = self.tokens.create(str(user["id"]), name, token[: len(self.prefix) + 6], _hash(token))
        return {"id": str(row["id"]), "name": row["name"], "prefix": row["prefix"], "token": token}

    def list_tokens(self, user: dict) -> list[dict]:
        return [{"id": str(r["id"]), "name": r["name"], "prefix": r["prefix"], "created_at": r["created_at"].isoformat(),
                 "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None} for r in self.tokens.for_user(str(user["id"]))]

    def revoke(self, user: dict, token_id: str) -> None:
        if not self.tokens.revoke(str(user["id"]), token_id):
            raise NotFound("token not found")

    def user_for_token(self, token: str) -> Optional[dict]:
        if not token or not token.startswith(self.prefix):
            return None
        return self.tokens.user_for_hash(_hash(token))
