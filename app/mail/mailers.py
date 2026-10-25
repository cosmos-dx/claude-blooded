"""Outgoing mail (mail.provider in config): SMTP in production, console in development."""
from __future__ import annotations

import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage

from app.core import logging as log
from app.core.errors import ProviderError
from app.core.registry import Registry

logger = log.get("mail")


class Mailer(ABC):
    def __init__(self, settings: dict):
        self.settings = settings

    @abstractmethod
    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None: ...


MAILERS: Registry[Mailer] = Registry("mailer")


@MAILERS.register("smtp")
class SmtpMailer(Mailer):
    def send(self, to, subject, text, html=None):
        s = self.settings
        if not s.get("host") or not s.get("from_email"):
            raise ProviderError("SMTP is not configured (SMTP_HOST / SMTP_FROM_EMAIL)")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s["from_email"], to, subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        port = int(s.get("port") or 587)
        try:
            if port == 465:
                with smtplib.SMTP_SSL(s["host"], port, context=ssl.create_default_context(), timeout=20) as smtp:
                    smtp.login(str(s["user"]), str(s["password"]))
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(s["host"], port, timeout=20) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    if s.get("user"):
                        smtp.login(str(s["user"]), str(s["password"]))
                    smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise ProviderError(f"could not send email: {e.__class__.__name__}") from e


@MAILERS.register("console")
class ConsoleMailer(Mailer):
    def send(self, to, subject, text, html=None):
        logger.warning("MAIL to=%s subject=%s\n%s", to, subject, text)
