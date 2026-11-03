/** Types mirroring docs/api.md. All timestamps are ISO 8601 UTC strings. */

/** The JSON body HookFlow POSTs to your endpoint. */
export interface WebhookEvent<TData = Record<string, unknown>> {
  id: string;
  type: string;
  created_at: string;
  data: TData;
}

export interface EventAccepted {
  event_id: string;
  status: "accepted";
  created_at: string;
  delivery_count: number;
}

export interface DeliveryCounts {
  total: number;
  pending: number;
  processing: number;
  retrying: number;
  delivered: number;
  failed: number;
  cancelled: number;
}

export interface EventSummary {
  id: string;
  event_type: string;
  created_at: string;
  deliveries: DeliveryCounts;
}

export interface Event extends EventSummary {
  data: Record<string, unknown>;
  idempotency_key: string | null;
}

export type DeliveryStatus = "pending" | "processing" | "retrying" | "delivered" | "failed" | "cancelled";

export interface Delivery {
  id: string;
  event_id: string;
  event_type: string;
  endpoint_id: string;
  endpoint_url: string;
  status: DeliveryStatus;
  attempt_count: number;
  max_attempts: number;
  run_attempt_count: number;
  run_max_attempts: number;
  next_attempt_at: string | null;
  last_status_code: number | null;
  last_error: string | null;
  delivered_at: string | null;
  replay_count: number;
  last_replayed_at: string | null;
  replayable: boolean;
  created_at: string;
  updated_at: string;
}

export interface Attempt {
  id: string;
  attempt_number: number;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  response_status: number | null;
  response_body: string | null;
  error: string | null;
  success: boolean;
}

export interface Replay {
  id: string;
  delivery_id: string;
  previous_status: "failed" | "cancelled";
  first_attempt_number: number;
  requested_by: { type: "session" | "api_key"; api_key_id: string | null };
  created_at: string;
}

export interface ReplaySkipped {
  delivery_id: string;
  reason: string;
}

export interface DeliveryReplayed {
  replay: Replay;
  delivery: Delivery;
}

export interface EventReplayed {
  replayed: DeliveryReplayed[];
  skipped: ReplaySkipped[];
}

export interface BulkReplayResult {
  matched: number;
  /** IDs of the deliveries that were replayed (or would be, with `dry_run`). */
  replayed: string[];
  skipped: ReplaySkipped[];
  has_more: boolean;
  dry_run: boolean;
}

export interface EndpointHealth {
  state: "idle" | "healthy" | "degraded" | "failing";
  attempts: number;
  successes: number;
  success_rate: number | null;
  last_attempt_at: string | null;
  last_success: boolean | null;
  last_status_code: number | null;
  last_error: string | null;
}

export interface Endpoint {
  id: string;
  url: string;
  description: string | null;
  enabled: boolean;
  event_types: string[];
  max_attempts: number;
  /** Custom retry delays in seconds; null means the default exponential backoff. */
  retry_schedule?: number[] | null;
  previous_secret_expires_at: string | null;
  created_at: string;
  updated_at: string;
  /** Present on list and get. */
  health?: EndpointHealth;
}

export interface EndpointCreated extends Endpoint {
  signing_secret: string;
}

export interface SigningSecret {
  signing_secret: string;
  previous_secret_expires_at: string | null;
}

export type DateLike = Date | string;

export interface PageParams {
  /** 1-100, default 25. */
  limit?: number;
  cursor?: string;
}

export interface EventListParams extends PageParams {
  event_type?: string;
  created_after?: DateLike;
  created_before?: DateLike;
}

export interface DeliveryListParams extends PageParams {
  status?: DeliveryStatus;
  endpoint_id?: string;
  event_id?: string;
}

export interface BulkReplayParams {
  endpoint_id?: string;
  event_type?: string;
  /** Default `["failed"]`. */
  statuses?: Array<"failed" | "cancelled">;
  created_after?: DateLike;
  created_before?: DateLike;
  /** 1-500, default 100. */
  limit?: number;
  /** Default false: when true, nothing is replayed and the response shows what would be. */
  dry_run?: boolean;
}

export interface EndpointCreateParams {
  url: string;
  event_types: string[];
  description?: string | null;
  enabled?: boolean;
  max_attempts?: number;
  /** Retry delays in seconds. Omit for the default backoff. */
  retry_schedule?: number[];
}

export interface EndpointUpdateParams {
  url?: string;
  /** `null` clears the description. */
  description?: string | null;
  event_types?: string[];
  enabled?: boolean;
  max_attempts?: number;
  /** `null` restores the default backoff. */
  retry_schedule?: number[] | null;
}
