"use client";

// The customer portal's API client. It authenticates with the portal token from the link (never the dashboard
// session cookie), and never redirects to the log-in page: portal visitors don't have HookFlow accounts.

import { ApiError, type Attempt, type Delivery, type Endpoint, type EndpointWithHealth, type List, type Page,
  type Replay } from "./api";

const KEY = "hf_portal_token";

/** Take the token from the URL fragment (#token=…) and keep it for this tab, so a reload still works. */
export function takeToken(): string | null {
  if (typeof window === "undefined") return null;
  const m = window.location.hash.match(/token=([^&]+)/);
  if (m) {
    const token = decodeURIComponent(m[1]);
    try {
      window.sessionStorage.setItem(KEY, token);
    } catch {
      /* storage unavailable: works until the page is reloaded */
    }
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return token;
  }
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export type PortalMe = {
  consumer: { id: string; uid: string; name: string | null };
  brand_name: string | null;
  expires_at: string;
  event_types: string[];
};

async function call<T>(token: string, method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/v1/portal${path}`, {
      method,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "omit",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Couldn't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const e = json?.error;
    const ra = Number(res.headers.get("Retry-After"));
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? `Request failed (HTTP ${res.status}).`,
      e?.details ?? null, Number.isFinite(ra) && ra > 0 ? Math.ceil(ra) : null);
  }
  return json as T;
}

export function portalApi(token: string) {
  const id = encodeURIComponent;
  return {
    me: () => call<PortalMe>(token, "GET", "/me"),
    listEndpoints: () => call<List<EndpointWithHealth>>(token, "GET", "/endpoints"),
    getEndpoint: (e: string) => call<EndpointWithHealth>(token, "GET", `/endpoints/${id(e)}`),
    createEndpoint: (body: { url: string; description: string | null; event_types: string[] }) =>
      call<Endpoint & { signing_secret: string }>(token, "POST", "/endpoints", body),
    updateEndpoint: (e: string, body: Partial<{ url: string; description: string | null; event_types: string[];
      enabled: boolean }>) => call<Endpoint>(token, "PATCH", `/endpoints/${id(e)}`, body),
    deleteEndpoint: (e: string) => call<void>(token, "DELETE", `/endpoints/${id(e)}`),
    getSecret: (e: string) => call<{ signing_secret: string }>(token, "GET", `/endpoints/${id(e)}/secret`),
    securityCheck: (e: string) => call<Endpoint>(token, "POST", `/endpoints/${id(e)}/security-check`),
    listDeliveries: (e: string, cursor?: string | null) =>
      call<Page<Delivery>>(token, "GET", `/endpoints/${id(e)}/deliveries${cursor ? `?cursor=${id(cursor)}` : ""}`),
    listAttempts: (d: string) => call<List<Attempt>>(token, "GET", `/deliveries/${id(d)}/attempts`),
    replay: (d: string) => call<{ replay: Replay; delivery: Delivery }>(token, "POST", `/deliveries/${id(d)}/replay`),
  };
}

export type PortalApi = ReturnType<typeof portalApi>;
