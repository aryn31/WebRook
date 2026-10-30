import type { Delivery, DeliveryCounts, DeliveryStatus } from "./api";

// Times: shown in the viewer's local time everywhere; full UTC is in the title attribute.

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** "14:35:02" today, "Oct 29, 14:35" this year, "Oct 29 2025, 14:35" otherwise. */
export function formatLocal(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return "—";
  const now = new Date();
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  if (sameDay(d, now)) return `Today ${time}`;
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return `${d.toLocaleDateString(undefined, opts)}, ${time}`;
}

/** Full UTC timestamp for title attributes: "2026-10-30 14:35:02 UTC". */
export function formatUtc(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return "";
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}

/** Short local time with zone for sentences: "14:35 (GMT+1)". */
export function formatClock(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return "—";
  const now = new Date();
  const parts = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short",
    ...(sameDay(d, now) ? {} : { month: "short", day: "numeric" }),
  }).format(d);
  return parts;
}

/** "in 3m", "5m ago", etc. */
export function relative(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return "";
  const diff = d.getTime() - Date.now();
  const abs = Math.abs(diff);
  const s = Math.round(abs / 1000);
  let v: string;
  if (s < 60) v = `${s}s`;
  else if (s < 3600) v = `${Math.round(s / 60)}m`;
  else if (s < 86400) v = `${Math.round(s / 3600)}h`;
  else v = `${Math.round(s / 86400)}d`;
  if (s < 5) return "now";
  return diff > 0 ? `in ${v}` : `${v} ago`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatNumber(n: number): string {
  return n.toLocaleString();
}

function lcFirst(s: string): string {
  return s ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

function stripPeriod(s: string): string {
  return s.replace(/[.\s]+$/, "");
}

/** What went wrong, as a lower-case clause: "destination returned HTTP 503". */
function failureReason(d: Delivery): string | null {
  if (d.last_error) return lcFirst(stripPeriod(d.last_error));
  if (d.last_status_code != null) return `destination returned HTTP ${d.last_status_code}`;
  return null;
}

export type Explanation = { tone: DeliveryStatus; text: string; hint?: string };

/** Human-readable, actionable explanation of a delivery's state. */
export function explainDelivery(d: Delivery): Explanation {
  const reason = failureReason(d);
  const attempts = `${d.attempt_count} of ${d.max_attempts} attempt${d.max_attempts === 1 ? "" : "s"}`;
  switch (d.status) {
    case "delivered":
      return {
        tone: "delivered",
        text: `Delivered${d.last_status_code != null ? ` (HTTP ${d.last_status_code})` : ""} on attempt ${d.attempt_count}${
          d.delivered_at ? ` at ${formatClock(d.delivered_at)}` : ""
        }.`,
      };
    case "failed": {
      const code = d.last_status_code;
      const nonRetryable4xx = code != null && code >= 400 && code < 500 && code !== 408 && code !== 429;
      return {
        tone: "failed",
        text: `Delivery failed${reason ? `: ${reason}` : ""}. Gave up after ${attempts}.`,
        hint: nonRetryable4xx
          ? `HTTP ${code} is not retried. Check that your endpoint accepts POST requests at this URL and verifies the signature correctly, then send the event again.`
          : "Check that your endpoint is reachable and returns a 2xx status within 10 seconds, then send the event again.",
      };
    }
    case "retrying":
      return {
        tone: "retrying",
        text: `Attempt ${d.attempt_count} failed${reason ? `: ${reason}` : ""}.${
          d.next_attempt_at
            ? ` Next retry scheduled for ${formatClock(d.next_attempt_at)} (${relative(d.next_attempt_at)}).`
            : " A retry is scheduled."
        }`,
        hint: `${d.max_attempts - d.attempt_count} attempt${d.max_attempts - d.attempt_count === 1 ? "" : "s"} left.`,
      };
    case "pending":
      return {
        tone: "pending",
        text: d.next_attempt_at
          ? `Waiting to be sent — first attempt scheduled for ${formatClock(d.next_attempt_at)}.`
          : "Waiting to be sent.",
      };
    case "processing":
      return { tone: "processing", text: `Sending now (attempt ${d.attempt_count + 1} of ${d.max_attempts}).` };
    case "cancelled":
      return {
        tone: "cancelled",
        text: `Cancelled before it was delivered${reason ? ` (last error: ${reason})` : ""}. This happens when the endpoint is archived.`,
      };
  }
}

export const STATUS_LABEL: Record<DeliveryStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  retrying: "Retrying",
  delivered: "Delivered",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function countsEntries(c: DeliveryCounts): [DeliveryStatus, number][] {
  const order: DeliveryStatus[] = ["delivered", "failed", "retrying", "processing", "pending", "cancelled"];
  return order.map((s) => [s, c[s]] as [DeliveryStatus, number]).filter(([, n]) => n > 0);
}

export function shortId(id: string, n = 14): string {
  return id.length > n + 1 ? id.slice(0, n) + "…" : id;
}

/** localStorage flag set when the user opens an event detail page (onboarding step 4). */
export const INSPECTED_KEY = "hf_inspected_event";
