from __future__ import annotations

from typing import Optional

from app.dao.base import BaseDAO


class UserDAO(BaseDAO):
    def by_email(self, email: str, conn=None) -> Optional[dict]:
        return self.one("SELECT * FROM users WHERE email = %s", (email.lower(),), conn)

    def by_id(self, user_id: str, conn=None) -> Optional[dict]:
        return self.one("SELECT * FROM users WHERE id = %s", (user_id,), conn)

    def upsert_login(self, email: str, conn=None) -> dict:
        return self.one(
            """INSERT INTO users (email, last_login_at) VALUES (%s, now())
               ON CONFLICT (email) DO UPDATE SET last_login_at = now()
               RETURNING *, (xmax = 0) AS created""", (email.lower(),), conn)

    def count(self, conn=None) -> int:
        return int(self.scalar("SELECT count(*) FROM users", (), conn) or 0)


class OtpDAO(BaseDAO):
    def create(self, email: str, code_hash: str, ttl_minutes: int, conn=None) -> None:
        self.run("INSERT INTO otp_codes (email, code_hash, expires_at) VALUES (%s, %s, now() + make_interval(mins => %s))",
                 (email.lower(), code_hash, ttl_minutes), conn)

    def latest_active(self, email: str, conn=None) -> Optional[dict]:
        return self.one("""SELECT * FROM otp_codes WHERE email = %s AND consumed_at IS NULL AND expires_at > now()
                           ORDER BY created_at DESC LIMIT 1""", (email.lower(),), conn)

    def sent_since(self, email: str, minutes: int, conn=None) -> int:
        return int(self.scalar("SELECT count(*) FROM otp_codes WHERE email = %s AND created_at > now() - make_interval(mins => %s)",
                               (email.lower(), minutes), conn) or 0)

    def seconds_since_last(self, email: str, conn=None) -> Optional[float]:
        return self.scalar("SELECT extract(epoch FROM now() - max(created_at)) FROM otp_codes WHERE email = %s", (email.lower(),), conn)

    def bump_attempts(self, otp_id: int, conn=None) -> None:
        self.run("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s", (otp_id,), conn)

    def consume(self, otp_id: int, conn=None) -> None:
        self.run("UPDATE otp_codes SET consumed_at = now() WHERE id = %s", (otp_id,), conn)
