"""Application errors. Services raise these; the API layer maps them to HTTP responses."""
from __future__ import annotations


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status


class NotFound(AppError):
    status, code = 404, "not_found"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class Conflict(AppError):
    status, code = 409, "conflict"


class TooManyRequests(AppError):
    status, code = 429, "rate_limited"


class PaymentRequired(AppError):
    status, code = 402, "no_credits"


class ProviderError(AppError):
    """An upstream provider (LLM, TTS, payment) failed. `retryable` lets routers fall back."""
    status, code = 502, "provider_error"

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
