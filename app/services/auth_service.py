"""Email + one-time-code login. Codes are stored hashed; sends and attempts are rate limited."""
from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

from app.core.config import Config
from app.core.errors import AppError, TooManyRequests, Unauthorized
from app.core.security import TokenService, constant_eq, hash_otp, new_otp
from app.dao.users import OtpDAO, UserDAO
from app.db.pool import Database
from app.mail.mailers import Mailer
from app.services.plan_service import PlanService


class AuthService:
    def __init__(self, config: Config, db: Database, users: UserDAO, otps: OtpDAO, mailer: Mailer, tokens: TokenService, plans: PlanService):
        self.config, self.db, self.users, self.otps, self.mailer, self.tokens, self.plans = config, db, users, otps, mailer, tokens, plans
        self.otp_cfg = config.get("security.otp") or {}
        self.secret = config.require("security.jwt_secret")

    @staticmethod
    def normalize(email: str) -> str:
        try:
            return validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError as e:
            raise AppError("please enter a valid email address") from e

    def send_code(self, email: str) -> None:
        email = self.normalize(email)
        since = self.otps.seconds_since_last(email)
        if since is not None and since < float(self.otp_cfg.get("resend_seconds", 45)):
            raise TooManyRequests("please wait a few seconds before asking for another code")
        if self.otps.sent_since(email, 60) >= int(self.otp_cfg.get("per_email_per_hour", 5)):
            raise TooManyRequests("too many codes requested; try again in an hour")
        code = new_otp(int(self.otp_cfg.get("length", 6)))
        self.otps.create(email, hash_otp(email, code, self.secret), int(self.otp_cfg.get("ttl_minutes", 10)))
        name = self.config.get("app.name")
        self.mailer.send(email, f"{code} is your {name} login code",
                         f"Your {name} login code is {code}. It expires in {self.otp_cfg.get('ttl_minutes', 10)} minutes.\n"
                         f"If you didn't ask for it, ignore this email.")

    def verify_code(self, email: str, code: str) -> tuple[dict, str]:
        email = self.normalize(email)
        otp = self.otps.latest_active(email)
        if not otp:
            raise Unauthorized("code expired; ask for a new one")
        if otp["attempts"] >= int(self.otp_cfg.get("max_attempts", 5)):
            raise TooManyRequests("too many wrong attempts; ask for a new code")
        if not constant_eq(otp["code_hash"], hash_otp(email, code.strip(), self.secret)):
            self.otps.bump_attempts(otp["id"])
            raise Unauthorized("wrong code")
        with self.db.transaction() as conn:
            self.otps.consume(otp["id"], conn=conn)
            user = self.users.upsert_login(email, conn=conn)
            if user["created"]:
                self.plans.grant_signup(user["id"], conn=conn)
        return user, self.tokens.issue(str(user["id"]), email)

    def user_from_token(self, token: str) -> dict:
        claims = self.tokens.verify(token)
        user = self.users.by_id(claims["sub"])
        if not user:
            raise Unauthorized("account not found")
        return user

    def is_admin(self, user: dict) -> bool:
        admins = {e.strip().lower() for e in str(self.config.get("app.admin_emails") or "").split(",") if e.strip()}
        return user["email"].lower() in admins
