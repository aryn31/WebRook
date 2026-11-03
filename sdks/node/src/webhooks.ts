/**
 * Verify webhook requests sent by HookFlow.
 *
 *   HookFlow-Timestamp: 1793361600
 *   HookFlow-Signature: v1=<hex hmac_sha256(secret, "{timestamp}." + rawBody)>
 *
 * During a signing-secret rotation grace period the header carries two values, `v1=<new>,v1=<old>`;
 * a request is valid if any one of them matches.
 *
 * Always pass the RAW request body (the exact bytes received). Parsing the JSON and serializing it again
 * changes the bytes and the signature will not match. In Express use `express.raw({ type: "application/json" })`.
 */
import { createHmac, timingSafeEqual } from "node:crypto";
import { WebhookVerificationError } from "./errors.js";
import type { WebhookEvent } from "./types.js";

export const DEFAULT_TOLERANCE_SECONDS = 300;

export const HEADER_EVENT_ID = "HookFlow-Event-Id";
export const HEADER_EVENT_TYPE = "HookFlow-Event-Type";
export const HEADER_DELIVERY_ID = "HookFlow-Delivery-Id";
export const HEADER_ATTEMPT = "HookFlow-Attempt";
export const HEADER_TIMESTAMP = "HookFlow-Timestamp";
export const HEADER_SIGNATURE = "HookFlow-Signature";

/** Raw request body: a Buffer / Uint8Array, or a string (encoded as UTF-8). */
export type RawPayload = string | Uint8Array | ArrayBuffer;

/**
 * Request headers in any common shape: Node's `IncomingHttpHeaders` (Express `req.headers`), a Fetch
 * `Headers` object, a `Map`, a plain object, or an array of `[name, value]` pairs. Lookup is case-insensitive.
 */
export type HeadersLike =
  | { get(name: string): string | null | undefined }
  | Iterable<readonly [string, string]>
  | Record<string, string | string[] | number | undefined | null>;

export interface VerifyOptions {
  /** Reject requests whose timestamp is further than this from now. Default 300. `null` disables the check. */
  toleranceSeconds?: number | null;
  /** Override the current Unix time in seconds (for tests). */
  now?: number;
}

function toBuffer(payload: RawPayload): Buffer {
  if (typeof payload === "string") return Buffer.from(payload, "utf8");
  if (Buffer.isBuffer(payload)) return payload;
  if (payload instanceof Uint8Array) return Buffer.from(payload.buffer, payload.byteOffset, payload.byteLength);
  if (payload instanceof ArrayBuffer) return Buffer.from(payload);
  throw new TypeError(
    `payload must be the raw request body as a Buffer or string, not ${
      payload === null ? "null" : typeof payload
    }. Do not pass parsed JSON: in Express use express.raw({ type: "application/json" }).`,
  );
}

function headerLookup(headers: HeadersLike): (name: string) => string | undefined {
  if (headers && typeof (headers as { get?: unknown }).get === "function" && !(headers instanceof Map)) {
    const h = headers as { get(name: string): string | null | undefined };
    return (name) => h.get(name) ?? h.get(name.toLowerCase()) ?? undefined;
  }
  const map = new Map<string, string>();
  const entries: Iterable<readonly [string, unknown]> =
    headers instanceof Map || Array.isArray(headers)
      ? (headers as Iterable<readonly [string, unknown]>)
      : Object.entries(headers as Record<string, unknown>);
  for (const [key, value] of entries) {
    if (value == null) continue;
    const v = Array.isArray(value) ? value.join(",") : String(value);
    const k = String(key).toLowerCase();
    if (!map.has(k)) map.set(k, v);
  }
  return (name) => map.get(name.toLowerCase());
}

/** Hex HMAC-SHA256 of `"{timestamp}." + payload` keyed with `secret` (no `v1=` prefix). */
export function computeSignature(secret: string, timestamp: number | string, payload: RawPayload): string {
  return createHmac("sha256", Buffer.from(secret, "utf8"))
    .update(`${timestamp}.`)
    .update(toBuffer(payload))
    .digest("hex");
}

/** A `HookFlow-Signature` value (`v1=<hex>`). Useful for testing your receiver. */
export function sign(secret: string, timestamp: number | string, payload: RawPayload): string {
  return `v1=${computeSignature(secret, timestamp, payload)}`;
}

function normalizeOptions(options?: VerifyOptions | number | null): VerifyOptions {
  if (options === null) return { toleranceSeconds: null };
  if (typeof options === "number") return { toleranceSeconds: options };
  return options ?? {};
}

/**
 * Check the signature and timestamp without parsing the body.
 * @throws {WebhookVerificationError}
 */
export function verifySignature(
  payload: RawPayload,
  headers: HeadersLike,
  secret: string,
  options?: VerifyOptions | number | null,
): void {
  const body = toBuffer(payload);
  if (!secret) throw new TypeError("secret must be your endpoint's signing secret (whsec_...).");
  const opts = normalizeOptions(options);
  const tolerance = opts.toleranceSeconds === undefined ? DEFAULT_TOLERANCE_SECONDS : opts.toleranceSeconds;

  const get = headerLookup(headers);
  const rawTimestamp = get(HEADER_TIMESTAMP);
  const signatureHeader = get(HEADER_SIGNATURE);
  if (rawTimestamp === undefined) {
    throw new WebhookVerificationError(`Missing ${HEADER_TIMESTAMP} header.`, "missing_header");
  }
  if (signatureHeader === undefined) {
    throw new WebhookVerificationError(`Missing ${HEADER_SIGNATURE} header.`, "missing_header");
  }

  const timestamp = rawTimestamp.trim();
  if (!/^[0-9]+$/.test(timestamp)) {
    throw new WebhookVerificationError(`${HEADER_TIMESTAMP} is not a Unix timestamp.`, "invalid_timestamp");
  }
  if (tolerance !== null) {
    const now = opts.now ?? Date.now() / 1000;
    if (Math.abs(now - Number(timestamp)) > tolerance) {
      throw new WebhookVerificationError(
        `${HEADER_TIMESTAMP} is more than ${tolerance} seconds from the current time.`,
        "timestamp_out_of_tolerance",
      );
    }
  }

  const candidates = signatureHeader
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.startsWith("v1="))
    .map((part) => Buffer.from(part.slice(3), "utf8"));
  if (candidates.length === 0) {
    throw new WebhookVerificationError(`${HEADER_SIGNATURE} has no v1= signature.`, "no_signatures");
  }

  const expected = Buffer.from(computeSignature(secret, timestamp, body), "utf8");
  // Check every candidate (no early exit) with a constant-time comparison.
  let matched = false;
  for (const candidate of candidates) {
    if (candidate.length === expected.length && timingSafeEqual(candidate, expected)) matched = true;
  }
  if (!matched) {
    throw new WebhookVerificationError(
      "No signature matches. Check the signing secret, and make sure you pass the raw request body.",
      "signature_mismatch",
    );
  }
}

/**
 * Verify a HookFlow webhook request and return the parsed event.
 *
 * @param payload  the RAW request body exactly as received (Buffer, or string decoded as UTF-8)
 * @param headers  the request headers (case-insensitive lookup)
 * @param secret   the endpoint's full signing secret, including the `whsec_` prefix
 * @param options  `{ toleranceSeconds = 300, now }`, or just the tolerance in seconds
 * @throws {WebhookVerificationError} on missing headers, a malformed or stale timestamp, or no matching signature
 */
export function verify<TData = Record<string, unknown>>(
  payload: RawPayload,
  headers: HeadersLike,
  secret: string,
  options?: VerifyOptions | number | null,
): WebhookEvent<TData> {
  const body = toBuffer(payload);
  verifySignature(body, headers, secret, options);
  let event: unknown;
  try {
    event = JSON.parse(body.toString("utf8"));
  } catch {
    throw new WebhookVerificationError("Payload is not valid JSON.", "invalid_payload");
  }
  if (event === null || typeof event !== "object" || Array.isArray(event)) {
    throw new WebhookVerificationError("Payload is not a JSON object.", "invalid_payload");
  }
  return event as WebhookEvent<TData>;
}
