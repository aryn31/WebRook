import { APIConnectionError, APITimeoutError, HookFlowError, errorFromResponse } from "./errors.js";
import type {
  Attempt,
  BulkReplayParams,
  BulkReplayResult,
  Delivery,
  DeliveryListParams,
  DeliveryReplayed,
  Endpoint,
  EndpointCreateParams,
  EndpointCreated,
  EndpointUpdateParams,
  Event,
  EventAccepted,
  EventListParams,
  EventReplayed,
  EventSummary,
  PageParams,
  Replay,
  SigningSecret,
} from "./types.js";

export const VERSION = "0.1.0";
export const DEFAULT_BASE_URL = "http://localhost:8000";
export const DEFAULT_TIMEOUT_MS = 30_000;
export const DEFAULT_MAX_RETRIES = 2;
/** Never sleep longer than this for one retry (e.g. a daily-quota Retry-After). */
const MAX_RETRY_WAIT_MS = 30_000;

type FetchLike = typeof fetch;

export interface HookFlowOptions {
  /** `hf_<prefix>_<secret>`. Defaults to `process.env.HOOKFLOW_API_KEY`. */
  apiKey?: string;
  /** API origin, e.g. `https://hookflow.example.com`. Defaults to `HOOKFLOW_BASE_URL` or `http://localhost:8000`. */
  baseUrl?: string;
  /** Milliseconds per HTTP request. Default 30000. */
  timeout?: number;
  /**
   * Retries for safe requests on connection errors, 429 and 5xx (default 2; 0 disables). Safe means GET and
   * DELETE, and `POST /v1/events` only when an idempotency key is given. Other POST and PATCH requests are
   * never retried.
   */
  maxRetries?: number;
  /** Custom fetch implementation (defaults to the global `fetch`). */
  fetch?: FetchLike;
}

export interface RequestOptions {
  query?: Record<string, unknown>;
  body?: unknown;
  headers?: Record<string, string>;
  /** Override whether this request may be retried. Defaults to true for GET/HEAD/DELETE. */
  retryable?: boolean;
}

type Query = Record<string, unknown>;

function env(name: string): string | undefined {
  return typeof process !== "undefined" ? process.env?.[name] : undefined;
}

/** Drop undefined/null values and convert Dates to ISO 8601. */
function clean(params: Query | undefined): Query {
  const out: Query = {};
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === null) continue;
    out[k] = v instanceof Date ? v.toISOString() : v;
  }
  return out;
}

function seg(id: string): string {
  if (typeof id !== "string" || id === "") throw new TypeError("id must be a non-empty string");
  return encodeURIComponent(id);
}

/** One page of a cursor-paginated list. `for await` over a page walks it and every later page. */
export class Page<T> implements AsyncIterable<T> {
  constructor(
    readonly data: T[],
    readonly nextCursor: string | null,
    private readonly fetchNext: (cursor: string) => Promise<Page<T>>,
  ) {}

  get hasMore(): boolean {
    return this.nextCursor !== null;
  }

  async getNextPage(): Promise<Page<T> | null> {
    return this.nextCursor ? this.fetchNext(this.nextCursor) : null;
  }

  async *[Symbol.asyncIterator](): AsyncIterator<T> {
    let page: Page<T> | null = this;
    while (page) {
      yield* page.data;
      page = await page.getNextPage();
    }
  }
}

/** Lazily iterate every item of a paginated list, fetching pages as needed. */
async function* iterateAll<T>(first: () => Promise<Page<T>>): AsyncGenerator<T, void, undefined> {
  yield* await first();
}

export class HookFlow {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly timeout: number;
  readonly maxRetries: number;
  readonly events: Events;
  readonly deliveries: Deliveries;
  readonly endpoints: Endpoints;
  private readonly fetchImpl: FetchLike;

  constructor(options: HookFlowOptions = {}) {
    const apiKey = options.apiKey ?? env("HOOKFLOW_API_KEY");
    if (!apiKey) throw new TypeError("An API key is required: pass { apiKey } or set HOOKFLOW_API_KEY.");
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new TypeError("No fetch implementation found (Node 18+ required).");
    this.apiKey = apiKey;
    this.baseUrl = (options.baseUrl ?? env("HOOKFLOW_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = Math.max(0, Math.floor(options.maxRetries ?? DEFAULT_MAX_RETRIES));
    this.fetchImpl = fetchImpl;
    this.events = new Events(this);
    this.deliveries = new Deliveries(this);
    this.endpoints = new Endpoints(this);
  }

  /** Send a request to `${baseUrl}${path}` and return the decoded JSON (`undefined` for 204). */
  async request<T = unknown>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    method = method.toUpperCase();
    let url = this.baseUrl + path;
    const query = clean(options.query);
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      for (const item of Array.isArray(v) ? v : [v]) qs.append(k, String(item));
    }
    if ([...qs.keys()].length) url += `?${qs}`;

    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      Accept: "application/json",
      "User-Agent": `hookflow-node/${VERSION}`,
    };
    let body: string | undefined;
    if (options.body !== undefined) {
      body = JSON.stringify(options.body);
      headers["Content-Type"] = "application/json";
    }
    Object.assign(headers, options.headers);
    const retryable = options.retryable ?? ["GET", "HEAD", "DELETE"].includes(method);

    for (let attempt = 0; ; attempt++) {
      try {
        return (await this.sendOnce(method, url, headers, body)) as T;
      } catch (err) {
        const wait =
          retryable && attempt < this.maxRetries && err instanceof HookFlowError ? retryWait(err, attempt) : null;
        if (wait === null) throw err;
        await this.sleep(wait);
      }
    }
  }

  /** @internal overridable for tests */
  protected sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async sendOnce(method: string, url: string, headers: Record<string, string>, body?: string) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let res: Response;
    let text: string;
    try {
      res = await this.fetchImpl(url, { method, headers, body, signal: controller.signal, redirect: "manual" });
      text = await res.text();
    } catch (err) {
      if (controller.signal.aborted) {
        throw new APITimeoutError(`Request timed out after ${this.timeout}ms.`, { cause: err });
      }
      const reason = (err as { cause?: { message?: string } })?.cause?.message ?? (err as Error)?.message;
      throw new APIConnectionError(`Could not reach HookFlow at ${this.baseUrl}: ${reason}`, { cause: err });
    } finally {
      clearTimeout(timer);
    }

    const resHeaders: Record<string, string> = {};
    res.headers.forEach((value, key) => {
      resHeaders[key.toLowerCase()] = value;
    });
    let parsed: unknown = undefined;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = undefined;
      }
    }
    if (res.status >= 200 && res.status < 300) {
      if (res.status === 204 || !text) return undefined;
      if (parsed === undefined) {
        throw new HookFlowError("The API returned a non-JSON response.", { status: res.status, headers: resHeaders });
      }
      return parsed;
    }
    throw errorFromResponse(res.status, resHeaders, parsed ?? null, text);
  }

  /** @internal */
  async page<T>(path: string, params: Query = {}): Promise<Page<T>> {
    const { cursor, ...rest } = clean(params);
    const fetchPage = async (c: unknown): Promise<Page<T>> => {
      const res = await this.request<{ data: T[]; next_cursor?: string | null }>("GET", path, {
        query: { ...rest, cursor: c },
      });
      return new Page(res.data ?? [], res.next_cursor ?? null, fetchPage);
    };
    return fetchPage(cursor);
  }
}

function retryWait(err: HookFlowError, attempt: number): number | null {
  if (!(err instanceof APIConnectionError)) {
    if (!(err.status === 429 || (err.status !== null && err.status >= 500))) return null;
    const retryAfter = (err as { retryAfter?: number | null }).retryAfter;
    if (retryAfter != null) return retryAfter * 1000 <= MAX_RETRY_WAIT_MS ? retryAfter * 1000 : null;
  }
  return Math.min(500 * 2 ** attempt, 8000) * (0.75 + Math.random() / 2);
}

abstract class Resource {
  constructor(protected readonly client: HookFlow) {}
}

export interface SendEventOptions {
  /** Makes the request safe to retry; it is then retried automatically on 429/5xx. */
  idempotencyKey?: string;
}

export class Events extends Resource {
  /** `POST /v1/events`. */
  send(eventType: string, data: Record<string, unknown>, options: SendEventOptions = {}): Promise<EventAccepted> {
    const key = options.idempotencyKey;
    return this.client.request("POST", "/v1/events", {
      body: { event_type: eventType, data },
      headers: key !== undefined ? { "Idempotency-Key": key } : undefined,
      retryable: key !== undefined,
    });
  }

  /** `GET /v1/events` (newest first). */
  list(params: EventListParams = {}): Promise<Page<EventSummary>> {
    return this.client.page("/v1/events", { ...params });
  }

  /** Iterate every matching event, fetching pages lazily: `for await (const e of hf.events.listAll())`. */
  listAll(params: EventListParams = {}): AsyncGenerator<EventSummary, void, undefined> {
    return iterateAll(() => this.list(params));
  }

  get(eventId: string): Promise<Event> {
    return this.client.request("GET", `/v1/events/${seg(eventId)}`);
  }

  /** `GET /v1/events/{id}/deliveries`: every delivery of the event (not paginated). */
  async deliveries(eventId: string): Promise<Delivery[]> {
    const res = await this.client.request<{ data: Delivery[] }>("GET", `/v1/events/${seg(eventId)}/deliveries`);
    return res.data;
  }

  /** `POST /v1/events/{id}/replay`: replay the event's failed/cancelled deliveries. */
  replay(eventId: string, endpointIds?: string[]): Promise<EventReplayed> {
    return this.client.request("POST", `/v1/events/${seg(eventId)}/replay`, {
      body: endpointIds ? { endpoint_ids: endpointIds } : {},
    });
  }
}

export class Deliveries extends Resource {
  /** `GET /v1/deliveries` (newest first). */
  list(params: DeliveryListParams = {}): Promise<Page<Delivery>> {
    return this.client.page("/v1/deliveries", { ...params });
  }

  listAll(params: DeliveryListParams = {}): AsyncGenerator<Delivery, void, undefined> {
    return iterateAll(() => this.list(params));
  }

  get(deliveryId: string): Promise<Delivery> {
    return this.client.request("GET", `/v1/deliveries/${seg(deliveryId)}`);
  }

  /** `GET /v1/deliveries/{id}/attempts` (oldest first). */
  async attempts(deliveryId: string): Promise<Attempt[]> {
    const res = await this.client.request<{ data: Attempt[] }>("GET", `/v1/deliveries/${seg(deliveryId)}/attempts`);
    return res.data;
  }

  /** `GET /v1/deliveries/{id}/replays` (oldest first). */
  async replays(deliveryId: string): Promise<Replay[]> {
    const res = await this.client.request<{ data: Replay[] }>("GET", `/v1/deliveries/${seg(deliveryId)}/replays`);
    return res.data;
  }

  /** `POST /v1/deliveries/{id}/replay`. */
  replay(deliveryId: string): Promise<DeliveryReplayed> {
    return this.client.request("POST", `/v1/deliveries/${seg(deliveryId)}/replay`);
  }

  /**
   * `POST /v1/deliveries/replay`: replay many failed/cancelled deliveries at once. Omitted fields use the
   * server defaults (`statuses: ["failed"]`, `limit: 100` (max 500), `dry_run: false`).
   */
  bulkReplay(params: BulkReplayParams = {}): Promise<BulkReplayResult> {
    return this.client.request("POST", "/v1/deliveries/replay", { body: clean({ ...params }) });
  }
}

export class Endpoints extends Resource {
  /** `GET /v1/endpoints` (each with `health`). */
  list(params: PageParams = {}): Promise<Page<Endpoint>> {
    return this.client.page("/v1/endpoints", { ...params });
  }

  listAll(params: PageParams = {}): AsyncGenerator<Endpoint, void, undefined> {
    return iterateAll(() => this.list(params));
  }

  get(endpointId: string): Promise<Endpoint> {
    return this.client.request("GET", `/v1/endpoints/${seg(endpointId)}`);
  }

  /** `POST /v1/endpoints`. The response includes `signing_secret` (`whsec_...`). */
  create(params: EndpointCreateParams): Promise<EndpointCreated> {
    return this.client.request("POST", "/v1/endpoints", { body: clean({ ...params }) });
  }

  /** `PATCH /v1/endpoints/{id}`. Only the fields you pass are sent; `description: null` clears it. */
  update(endpointId: string, params: EndpointUpdateParams): Promise<Endpoint> {
    const body = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined));
    return this.client.request("PATCH", `/v1/endpoints/${seg(endpointId)}`, { body });
  }

  /** `DELETE /v1/endpoints/{id}`: archive the endpoint (its unsent deliveries are cancelled). */
  async delete(endpointId: string): Promise<void> {
    await this.client.request("DELETE", `/v1/endpoints/${seg(endpointId)}`);
  }

  /** `GET /v1/endpoints/{id}/secret`. */
  secret(endpointId: string): Promise<SigningSecret> {
    return this.client.request("GET", `/v1/endpoints/${seg(endpointId)}/secret`);
  }

  /** `POST /v1/endpoints/{id}/rotate-secret` (default grace period: 24 hours). */
  rotateSecret(endpointId: string, gracePeriodSeconds?: number): Promise<SigningSecret> {
    return this.client.request("POST", `/v1/endpoints/${seg(endpointId)}/rotate-secret`, {
      body: gracePeriodSeconds !== undefined ? { grace_period_seconds: gracePeriodSeconds } : {},
    });
  }
}
