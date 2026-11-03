/** Reasons a webhook can fail verification. */
export type WebhookVerificationReason =
  | "missing_header"
  | "invalid_timestamp"
  | "timestamp_out_of_tolerance"
  | "no_signatures"
  | "signature_mismatch"
  | "invalid_payload";

/** A webhook request could not be verified. Respond with 400 and do not process it. */
export class WebhookVerificationError extends Error {
  override readonly name = "WebhookVerificationError";
  readonly reason: WebhookVerificationReason;

  constructor(message: string, reason: WebhookVerificationReason) {
    super(message);
    this.reason = reason;
  }
}

export interface HookFlowErrorInit {
  status?: number | null;
  code?: string | null;
  details?: unknown;
  headers?: Record<string, string>;
  body?: unknown;
  retryAfter?: number | null;
  cause?: unknown;
}

/**
 * Base class for every error returned by (or while talking to) the HookFlow API. The API always answers
 * errors with `{ "error": { "code", "message", "details" } }`; those are exposed as properties.
 * `status` is `null` when no HTTP response was received.
 */
export class HookFlowError extends Error {
  override name = "HookFlowError";
  readonly status: number | null;
  readonly code: string | null;
  readonly details: unknown;
  readonly headers: Record<string, string>;
  readonly body: unknown;

  constructor(message: string, init: HookFlowErrorInit = {}) {
    super(message, init.cause === undefined ? undefined : { cause: init.cause });
    this.status = init.status ?? null;
    this.code = init.code ?? null;
    this.details = init.details ?? null;
    this.headers = init.headers ?? {};
    this.body = init.body ?? null;
  }
}

/** The request never got an HTTP response (DNS failure, connection refused, reset...). */
export class APIConnectionError extends HookFlowError {
  override name = "APIConnectionError";
}
/** The request took longer than the configured timeout. */
export class APITimeoutError extends APIConnectionError {
  override name = "APITimeoutError";
}
/** 400 */
export class BadRequestError extends HookFlowError {
  override name = "BadRequestError";
}
/** 401: missing, invalid or revoked API key. Also the base class of PermissionDeniedError. */
export class AuthenticationError extends HookFlowError {
  override name = "AuthenticationError";
}
/** 403: the key is valid but not allowed to do this. */
export class PermissionDeniedError extends AuthenticationError {
  override name = "PermissionDeniedError";
}
/** 404. Also returned for resources that belong to another account. */
export class NotFoundError extends HookFlowError {
  override name = "NotFoundError";
}
/** 409: conflict, idempotency_key_reused, not_replayable, nothing_to_replay... */
export class ConflictError extends HookFlowError {
  override name = "ConflictError";
}
/** 413: the request body exceeds the 1 MiB limit. */
export class PayloadTooLargeError extends HookFlowError {
  override name = "PayloadTooLargeError";
}
/** 422: `details` holds a list of `{ loc, msg, type }` field errors. */
export class ValidationError extends HookFlowError {
  override name = "ValidationError";
}
/** 429: `rate_limited` or `quota_exceeded`. `retryAfter` is in seconds (or null). */
export class RateLimitError extends HookFlowError {
  override name = "RateLimitError";
  readonly retryAfter: number | null;
  constructor(message: string, init: HookFlowErrorInit = {}) {
    super(message, init);
    this.retryAfter = init.retryAfter ?? null;
  }
}
/** 5xx, including 503 service_unavailable (temporary; `retryAfter` may be set). */
export class InternalServerError extends HookFlowError {
  override name = "InternalServerError";
  readonly retryAfter: number | null;
  constructor(message: string, init: HookFlowErrorInit = {}) {
    super(message, init);
    this.retryAfter = init.retryAfter ?? null;
  }
}

const BY_STATUS: Record<number, typeof HookFlowError> = {
  400: BadRequestError,
  401: AuthenticationError,
  403: PermissionDeniedError,
  404: NotFoundError,
  409: ConflictError,
  413: PayloadTooLargeError,
  422: ValidationError,
};

export function parseRetryAfter(value: string | null | undefined): number | null {
  if (value == null || value.trim() === "") return null;
  const seconds = Number(value.trim());
  return Number.isFinite(seconds) ? Math.max(seconds, 0) : null; // HookFlow always sends seconds
}

/** @internal */
export function errorFromResponse(
  status: number,
  headers: Record<string, string>,
  body: unknown,
  text: string,
): HookFlowError {
  let code: string | null = null;
  let message = text.trim().slice(0, 500) || `HTTP ${status}`;
  let details: unknown = null;
  const err = body && typeof body === "object" ? (body as { error?: unknown }).error : undefined;
  if (err && typeof err === "object") {
    const e = err as { code?: string; message?: string; details?: unknown };
    code = e.code ?? null;
    message = e.message || message;
    details = e.details ?? null;
  }
  const init: HookFlowErrorInit = {
    status,
    code,
    details,
    headers,
    body,
    retryAfter: parseRetryAfter(headers["retry-after"]),
  };
  if (status === 429) return new RateLimitError(message, init);
  if (status >= 500) return new InternalServerError(message, init);
  const Cls = BY_STATUS[status] ?? HookFlowError;
  return new Cls(message, init);
}
