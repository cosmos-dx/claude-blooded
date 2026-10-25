"""Personal access tokens and community skill packs (SQL only)."""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from app.dao.base import BaseDAO


class ApiTokenDAO(BaseDAO):
    def create(self, user_id: str, name: str, prefix: str, token_hash: str, conn=None) -> dict:
        return self.one("""INSERT INTO api_tokens (user_id, name, prefix, token_hash) VALUES (%s, %s, %s, %s)
                           RETURNING id, name, prefix, created_at""", (user_id, name, prefix, token_hash), conn)

    def for_user(self, user_id: str, conn=None) -> list[dict]:
        return self.all("""SELECT id, name, prefix, created_at, last_used_at FROM api_tokens
                           WHERE user_id = %s AND revoked_at IS NULL ORDER BY created_at DESC""", (user_id,), conn)

    def user_for_hash(self, token_hash: str, conn=None) -> Optional[dict]:
        """The token's user (and marks the token used); None for unknown or revoked tokens."""
        return self.one("""WITH t AS (UPDATE api_tokens SET last_used_at = now() WHERE token_hash = %s AND revoked_at IS NULL
                                      RETURNING user_id)
                           SELECT u.* FROM users u JOIN t ON t.user_id = u.id""", (token_hash,), conn)

    def revoke(self, user_id: str, token_id: str, conn=None) -> int:
        return self.run("UPDATE api_tokens SET revoked_at = now() WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
                        (token_id, user_id), conn)


class SkillPackDAO(BaseDAO):
    def upsert_pending(self, owner_id: str, code: str, engine: str, name: str, pack: dict, conn=None) -> Optional[dict]:
        """Create a pack, or replace the owner's own pack with the same code (back to pending). None if another owner has the code."""
        return self.one("""INSERT INTO skill_packs (code, owner_id, engine, name, pack) VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (code) DO UPDATE SET engine = EXCLUDED.engine, name = EXCLUDED.name, pack = EXCLUDED.pack,
                               status = 'pending', review_note = NULL, reviewed_by = NULL, reviewed_at = NULL, updated_at = now()
                           WHERE skill_packs.owner_id = EXCLUDED.owner_id
                           RETURNING id, code, status, updated_at""", (code, owner_id, engine, name, Jsonb(pack)), conn)

    def approved(self, conn=None) -> list[dict]:
        return self.all("SELECT code, engine, pack FROM skill_packs WHERE status = 'approved' ORDER BY code", (), conn)

    def for_owner(self, owner_id: str, conn=None) -> list[dict]:
        return self.all("""SELECT id, code, name, engine, status, review_note, updated_at FROM skill_packs
                           WHERE owner_id = %s ORDER BY updated_at DESC""", (owner_id,), conn)

    def by_status(self, status: str, conn=None) -> list[dict]:
        return self.all("""SELECT p.id, p.code, p.name, p.engine, p.status, p.pack, p.updated_at, u.email AS owner_email
                           FROM skill_packs p JOIN users u ON u.id = p.owner_id WHERE p.status = %s ORDER BY p.updated_at""", (status,), conn)

    def review(self, pack_id: str, status: str, note: str, reviewer_id: str, conn=None) -> Optional[dict]:
        return self.one("""UPDATE skill_packs SET status = %s, review_note = %s, reviewed_by = %s, reviewed_at = now(), updated_at = now()
                           WHERE id = %s RETURNING id, code, status""", (status, note, reviewer_id, pack_id), conn)
