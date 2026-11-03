"""Exception types raised by the HookFlow SDK."""

from __future__ import annotations

from typing import Any, Mapping


class WebhookVerificationError(Exception):
    """A webhook request could not be verified. Respond with 400 and do not process it.

    ``reason`` is a stable machine-readable string: ``missing_header``, ``invalid_timestamp``,
    ``timestamp_out_of_tolerance``, ``no_signatures``, ``signature_mismatch`` or ``invalid_payload``.
    """

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.message = message
        self.reason = reason


class HookFlowError(Exception):
    """Base class for every error returned by (or while talking to) the HookFlow API.

    The API always answers errors with ``{"error": {"code", "message", "details"}}``; those fields are
    exposed as attributes. ``status`` is ``None`` when no HTTP response was received.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        details: Any = None,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details
        self.headers = dict(headers or {})
        self.body = body

    def __str__(self) -> str:
        prefix = f"[{self.status} {self.code}] " if self.status is not None else ""
        return prefix + self.message


class APIConnectionError(HookFlowError):
    """The request never got an HTTP response (DNS failure, connection refused, reset...)."""


class APITimeoutError(APIConnectionError):
    """The request took longer than the configured timeout."""


class BadRequestError(HookFlowError):
    """400."""


class AuthenticationError(HookFlowError):
    """401: missing, invalid or revoked API key. Also the base class of :class:`PermissionDeniedError`."""


class PermissionDeniedError(AuthenticationError):
    """403: the key is valid but not allowed to do this (for example a session-only route)."""


class NotFoundError(HookFlowError):
    """404. Also returned for resources that belong to another account."""


class ConflictError(HookFlowError):
    """409: ``conflict``, ``idempotency_key_reused``, ``not_replayable``, ``nothing_to_replay``..."""


class PayloadTooLargeError(HookFlowError):
    """413: the request body exceeds the 1 MiB limit."""


class ValidationError(HookFlowError):
    """422: ``details`` holds a list of ``{"loc", "msg", "type"}`` field errors."""


class RateLimitError(HookFlowError):
    """429: ``rate_limited`` or ``quota_exceeded``. ``retry_after`` is in seconds (or ``None``)."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class InternalServerError(HookFlowError):
    """5xx, including ``503 service_unavailable`` (temporary; ``retry_after`` may be set)."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


_BY_STATUS: dict[int, type[HookFlowError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    422: ValidationError,
    429: RateLimitError,
}


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None  # HTTP-date form; HookFlow always sends seconds
    return max(seconds, 0.0)


def error_from_response(status: int, headers: Mapping[str, str], body: Any, text: str) -> HookFlowError:
    code: str | None = None
    message = text.strip()[:500] or f"HTTP {status}"
    details: Any = None
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        code = err.get("code")
        message = err.get("message") or message
        details = err.get("details")

    kwargs: dict[str, Any] = dict(status=status, code=code, details=details, headers=headers, body=body)
    lower = {k.lower(): v for k, v in headers.items()}
    if status == 429:
        return RateLimitError(message, retry_after=parse_retry_after(lower.get("retry-after")), **kwargs)
    if status >= 500:
        return InternalServerError(message, retry_after=parse_retry_after(lower.get("retry-after")), **kwargs)
    cls = _BY_STATUS.get(status, HookFlowError)
    return cls(message, **kwargs)
