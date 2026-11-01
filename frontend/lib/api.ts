// Typed client for the HookFlow API (see docs/api.md).
// All requests go to /api/v1/... on the dashboard's own origin; next.config.ts
// rewrites /api/* to the backend so the HttpOnly hf_session cookie works.

// ---------- Types (copied from the contract) ----------

export type User = { id: string; email: string; created_at: string };

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type Endpoint = {
  id: string;
  url: string;
  description: string | null;
  enabled: boolean;
  event_types: string[];
  /** Attempts per delivery, including the first (1–10). Only affects new deliveries. */
  max_attempts: number;
  /** While in the future, the previous secret still signs alongside the new one. */
  previous_secret_expires_at: string | null;
  created_at: string;
  updated_at: string;
};

export const MAX_ATTEMPTS_MIN = 1;
export const MAX_ATTEMPTS_MAX = 10;
export const MAX_ATTEMPTS_DEFAULT = 5;

export type SigningSecret = { signing_secret: string; previous_secret_expires_at: string | null };

export type EndpointWithSecret = Endpoint & { signing_secret: string };

export type DeliveryCounts = {
  total: number;
  pending: number;
  processing: number;
  retrying: number;
  delivered: number;
  failed: number;
  cancelled: number;
};

export type EventSummary = {
  id: string;
  event_type: string;
  created_at: string;
  deliveries: DeliveryCounts;
};

export type HookEvent = EventSummary & { data: Record<string, unknown>; idempotency_key: string | null };

export type EventAccepted = {
  event_id: string;
  status: "accepted";
  created_at: string;
  delivery_count: number;
};

export type DeliveryStatus =
  | "pending"
  | "processing"
  | "retrying"
  | "delivered"
  | "failed"
  | "cancelled";

export const DELIVERY_STATUSES: DeliveryStatus[] = [
  "pending",
  "processing",
  "retrying",
  "delivered",
  "failed",
  "cancelled",
];

export type Delivery = {
  id: string;
  event_id: string;
  event_type: string;
  endpoint_id: string;
  endpoint_url: string;
  status: DeliveryStatus;
  /** Totals over the delivery's life; they keep growing with each manual replay. */
  attempt_count: number;
  max_attempts: number;
  /** Counted from the last manual replay (or creation). Use these for "x of y" displays. */
  run_attempt_count: number;
  run_max_attempts: number;
  next_attempt_at: string | null;
  last_status_code: number | null;
  last_error: string | null;
  delivered_at: string | null;
  replay_count: number;
  last_replayed_at: string | null;
  /** True when a replay would be accepted now (failed/cancelled, endpoint enabled and not archived). */
  replayable: boolean;
  created_at: string;
  updated_at: string;
};

export type Actor = { type: "session" | "api_key"; api_key_id: string | null };

export type Replay = {
  id: string;
  delivery_id: string;
  previous_status: DeliveryStatus;
  /** Attempts with attempt_number >= this came after the replay. */
  first_attempt_number: number;
  requested_by: Actor;
  created_at: string;
};

export type DeliveryReplayed = { replay: Replay; delivery: Delivery };

export type ReplaySkipped = { delivery_id: string; reason: string };

export type EventReplayed = { replayed: DeliveryReplayed[]; skipped: ReplaySkipped[] };

export type AuditAction =
  | "auth.registered"
  | "auth.login"
  | "api_key.created"
  | "api_key.revoked"
  | "endpoint.created"
  | "endpoint.updated"
  | "endpoint.archived"
  | "endpoint.secret_viewed"
  | "endpoint.secret_rotated"
  | "delivery.replayed"
  | "event.replayed";

export const AUDIT_ACTIONS: AuditAction[] = [
  "auth.registered",
  "auth.login",
  "api_key.created",
  "api_key.revoked",
  "endpoint.created",
  "endpoint.updated",
  "endpoint.archived",
  "endpoint.secret_viewed",
  "endpoint.secret_rotated",
  "delivery.replayed",
  "event.replayed",
];

export type AuditLog = {
  id: string;
  /** Usually an AuditAction; kept as string so unknown future actions still render. */
  action: string;
  actor: Actor;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
};

export type Attempt = {
  id: string;
  attempt_number: number;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  response_status: number | null;
  response_body: string | null;
  error: string | null;
  success: boolean;
};

export type StatsRange = "24h" | "7d" | "30d";

export type Stats = {
  range: StatsRange;
  events_total: number;
  deliveries_total: number;
  deliveries_by_status: Omit<DeliveryCounts, "total">;
  series: { bucket: string; events: number; delivered: number; failed: number }[];
};

export type Page<T> = { data: T[]; next_cursor: string | null };
export type List<T> = { data: T[] };

// ---------- Errors ----------

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  /** Seconds from the Retry-After header (429 responses), if any. */
  readonly retryAfter: number | null;

  constructor(status: number, code: string, message: string, details: unknown = null, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfter = retryAfter;
  }
}

/** Turn validation `details` (shape not fixed by the contract) into readable lines. */
export function describeDetails(details: unknown): string[] {
  if (!details) return [];
  const out: string[] = [];
  const fieldName = (loc: unknown): string => {
    if (Array.isArray(loc)) {
      const parts = loc.filter((p) => p !== "body" && p !== "query" && p !== "path");
      return parts.join(".");
    }
    return String(loc ?? "");
  };
  if (Array.isArray(details)) {
    for (const d of details) {
      if (d && typeof d === "object") {
        const o = d as Record<string, unknown>;
        const field = fieldName(o.loc ?? o.field);
        const msg = String(o.msg ?? o.message ?? JSON.stringify(o));
        out.push(field ? `${field}: ${msg}` : msg);
      } else if (d != null) {
        out.push(String(d));
      }
    }
  } else if (typeof details === "object") {
    for (const [k, v] of Object.entries(details as Record<string, unknown>)) {
      const msg = Array.isArray(v) ? v.map(String).join(", ") : typeof v === "string" ? v : JSON.stringify(v);
      out.push(`${k}: ${msg}`);
    }
  } else {
    out.push(String(details));
  }
  return out;
}

/** Human-readable message for any thrown value. Never exposes stack traces. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "rate_limited": {
        const base = err.message || "Too many attempts. Wait a minute and try again.";
        return err.retryAfter != null && !/\d+\s*s/.test(base) ? `${base} Try again in ${err.retryAfter}s.` : base;
      }
      case "not_replayable":
        return err.message || "This delivery can't be replayed right now.";
      case "nothing_to_replay":
        return err.message || "None of this event's deliveries can be replayed.";
      case "payload_too_large":
        return err.message || "Payload is too large (limit is 1 MiB).";
      default:
        return err.message || `Request failed (HTTP ${err.status}).`;
    }
  }
  return "Something went wrong. Please try again.";
}

// ---------- Core request ----------

const BASE = "/api/v1";

// Auth routes where a 401 is a normal answer (wrong password, not logged in)
// and must not trigger the redirect to /login.
const NO_REDIRECT_401 = ["/auth/login", "/auth/register", "/auth/logout"];

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  let url = BASE + path;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += "?" + s;
  }
  return url;
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  const { pathname, search } = window.location;
  if (pathname === "/login" || pathname === "/register") return;
  const next = encodeURIComponent(pathname + search);
  window.location.assign(`/login?next=${next}`);
}

export async function request<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  opts: { query?: Query; body?: unknown } = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Couldn't reach HookFlow. Check your connection and try again.");
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let json: unknown = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = null;
    }
  }

  if (!res.ok) {
    const e = (json as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    if (res.status === 401 && !NO_REDIRECT_401.includes(path)) {
      redirectToLogin();
    }
    if (e && typeof e === "object") {
      const ra = Number(res.headers.get("Retry-After"));
      throw new ApiError(
        res.status,
        e.code ?? "error",
        e.message ?? `Request failed (HTTP ${res.status}).`,
        e.details ?? null,
        Number.isFinite(ra) && ra > 0 ? Math.ceil(ra) : null,
      );
    }
    if (res.status === 502 || res.status === 503 || res.status === 504 || res.status === 500) {
      throw new ApiError(
        res.status,
        "unavailable",
        `The HookFlow API is unavailable right now (HTTP ${res.status}). Try again in a moment.`,
      );
    }
    throw new ApiError(res.status, "error", `Request failed (HTTP ${res.status}).`);
  }

  return json as T;
}

// ---------- Endpoints of the API ----------

export const api = {
  // Auth (session only)
  register: (email: string, password: string) =>
    request<{ user: User }>("POST", "/auth/register", { body: { email, password } }),
  login: (email: string, password: string) =>
    request<{ user: User }>("POST", "/auth/login", { body: { email, password } }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<{ user: User }>("GET", "/auth/me"),

  // API keys (session only)
  listApiKeys: () => request<List<ApiKey>>("GET", "/api-keys"),
  createApiKey: (name: string) =>
    request<{ api_key: ApiKey; key: string }>("POST", "/api-keys", { body: { name } }),
  revokeApiKey: (id: string) =>
    request<{ api_key: ApiKey }>("DELETE", `/api-keys/${encodeURIComponent(id)}`),

  // Endpoints
  listEndpoints: (q: { limit?: number; cursor?: string | null } = {}) =>
    request<Page<Endpoint>>("GET", "/endpoints", { query: q }),
  createEndpoint: (body: {
    url: string;
    description?: string;
    event_types: string[];
    enabled?: boolean;
    max_attempts?: number;
  }) =>
    request<EndpointWithSecret>("POST", "/endpoints", { body }),
  getEndpoint: (id: string) => request<Endpoint>("GET", `/endpoints/${encodeURIComponent(id)}`),
  updateEndpoint: (
    id: string,
    body: Partial<{
      url: string;
      description: string | null;
      event_types: string[];
      enabled: boolean;
      max_attempts: number;
    }>,
  ) => request<Endpoint>("PATCH", `/endpoints/${encodeURIComponent(id)}`, { body }),
  archiveEndpoint: (id: string) => request<void>("DELETE", `/endpoints/${encodeURIComponent(id)}`),
  /** Writes an `endpoint.secret_viewed` audit entry — only call on an explicit "Reveal". */
  getEndpointSecret: (id: string) =>
    request<SigningSecret>("GET", `/endpoints/${encodeURIComponent(id)}/secret`),
  /** grace_period_seconds: 0–604800; the API defaults to 86400 (24h) when omitted. */
  rotateEndpointSecret: (id: string, grace_period_seconds?: number) =>
    request<SigningSecret>("POST", `/endpoints/${encodeURIComponent(id)}/rotate-secret`, {
      body: grace_period_seconds === undefined ? {} : { grace_period_seconds },
    }),

  // Events
  sendEvent: (event_type: string, data: Record<string, unknown>) =>
    request<EventAccepted>("POST", "/events", { body: { event_type, data } }),
  listEvents: (
    q: {
      limit?: number;
      cursor?: string | null;
      event_type?: string;
      created_after?: string;
      created_before?: string;
    } = {},
  ) => request<Page<EventSummary>>("GET", "/events", { query: q }),
  getEvent: (id: string) => request<HookEvent>("GET", `/events/${encodeURIComponent(id)}`),
  getEventDeliveries: (id: string) =>
    request<List<Delivery>>("GET", `/events/${encodeURIComponent(id)}/deliveries`),
  /** Replays the event's failed/cancelled deliveries (optionally only to some endpoints). */
  replayEvent: (id: string, endpoint_ids?: string[]) =>
    request<EventReplayed>("POST", `/events/${encodeURIComponent(id)}/replay`, {
      body: endpoint_ids ? { endpoint_ids } : {},
    }),

  // Deliveries
  listDeliveries: (
    q: {
      limit?: number;
      cursor?: string | null;
      status?: DeliveryStatus;
      endpoint_id?: string;
      event_id?: string;
    } = {},
  ) => request<Page<Delivery>>("GET", "/deliveries", { query: q }),
  getDelivery: (id: string) => request<Delivery>("GET", `/deliveries/${encodeURIComponent(id)}`),
  getAttempts: (id: string) =>
    request<List<Attempt>>("GET", `/deliveries/${encodeURIComponent(id)}/attempts`),
  replayDelivery: (id: string) =>
    request<DeliveryReplayed>("POST", `/deliveries/${encodeURIComponent(id)}/replay`),
  /** Oldest first. */
  getReplays: (id: string) => request<List<Replay>>("GET", `/deliveries/${encodeURIComponent(id)}/replays`),

  // Audit log
  listAuditLogs: (
    q: { limit?: number; cursor?: string | null; action?: string; resource_id?: string } = {},
  ) => request<Page<AuditLog>>("GET", "/audit-logs", { query: q }),

  // Stats
  stats: (range: StatsRange) => request<Stats>("GET", "/stats", { query: { range } }),
};

/** Public URL of the API, used in copy-paste examples (curl). */
export const API_PUBLIC_URL = (process.env.NEXT_PUBLIC_API_PUBLIC_URL ?? "http://localhost:8000").replace(/\/+$/, "");
