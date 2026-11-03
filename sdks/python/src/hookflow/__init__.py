"""Official Python SDK for HookFlow."""

__version__ = "0.1.0"

from .errors import (  # noqa: E402
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    HookFlowError,
    InternalServerError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    WebhookVerificationError,
)
from .webhooks import DEFAULT_TOLERANCE_SECONDS, compute_signature, sign, verify, verify_signature  # noqa: E402
from .client import NOT_GIVEN, HookFlow, Page  # noqa: E402

__all__ = [
    "__version__",
    "HookFlow",
    "Page",
    "NOT_GIVEN",
    "verify",
    "verify_signature",
    "sign",
    "compute_signature",
    "DEFAULT_TOLERANCE_SECONDS",
    "WebhookVerificationError",
    "HookFlowError",
    "APIConnectionError",
    "APITimeoutError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "PayloadTooLargeError",
    "ValidationError",
    "RateLimitError",
    "InternalServerError",
]
