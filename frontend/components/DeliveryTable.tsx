"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, type Attempt, type Delivery } from "@/lib/api";
import { explainDelivery, formatDuration } from "@/lib/format";
import { ErrorBox, Loading, StatusPill, Time } from "./ui";

export function DeliveryExplanation({ delivery, compact }: { delivery: Delivery; compact?: boolean }) {
  const ex = explainDelivery(delivery);
  return (
    <div className={`explain explain-${ex.tone}${compact ? " explain-compact" : ""}`}>
      <span>{ex.text}</span>
      {!compact && ex.hint && <span className="explain-hint">{ex.hint}</span>}
    </div>
  );
}

export function AttemptHistory({ deliveryId }: { deliveryId: string }) {
  const [attempts, setAttempts] = useState<Attempt[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await api.getAttempts(deliveryId);
      setAttempts(res.data);
    } catch (e) {
      setError(e);
    }
  }, [deliveryId]);

  useEffect(() => {
    setAttempts(null);
    void load();
  }, [load]);

  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!attempts) return <Loading label="Loading attempts…" />;
  if (attempts.length === 0) return <div className="muted small pad">No attempts yet — this delivery hasn&apos;t been sent.</div>;

  return (
    <div className="attempts">
      <div className="attempts-head">
        <span>Attempt history</span>
        <button type="button" className="btn btn-sm btn-ghost" onClick={load}>
          Refresh
        </button>
      </div>
      {attempts.map((a) => (
        <div key={a.id} className={`attempt ${a.success ? "attempt-ok" : "attempt-fail"}`}>
          <div className="attempt-meta">
            <span className="attempt-num">#{a.attempt_number}</span>
            <span className={`code-badge ${a.success ? "ok" : "bad"}`}>
              {a.response_status != null ? `HTTP ${a.response_status}` : a.success ? "OK" : "No response"}
            </span>
            <Time iso={a.started_at} />
            <span className="muted">{formatDuration(a.duration_ms)}</span>
          </div>
          {a.error && <div className="attempt-error">{a.error}</div>}
          {a.response_body != null && a.response_body !== "" ? (
            <pre className="mono response-body">{a.response_body}</pre>
          ) : (
            <div className="muted small">No response body.</div>
          )}
        </div>
      ))}
    </div>
  );
}

type Column = "event" | "endpoint";

/** Table of deliveries; click a row to expand its attempt history. */
export function DeliveryTable({
  deliveries,
  show = ["event", "endpoint"],
}: {
  deliveries: Delivery[];
  show?: Column[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  const colCount = 4 + show.length;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Status</th>
            {show.includes("event") && <th>Event</th>}
            {show.includes("endpoint") && <th>Endpoint</th>}
            <th>Attempts</th>
            <th>Last code</th>
            <th>Next retry / updated</th>
          </tr>
        </thead>
        <tbody>
          {deliveries.map((d) => {
            const isOpen = open === d.id;
            const bad = d.status === "failed";
            return (
              <Fragment key={d.id}>
                <tr
                  className={`row-click${isOpen ? " row-open" : ""}${bad ? " row-failed" : ""}`}
                  onClick={() => setOpen(isOpen ? null : d.id)}
                  aria-expanded={isOpen}
                >
                  <td>
                    <span className="caret" aria-hidden>{isOpen ? "▾" : "▸"}</span> <StatusPill status={d.status} />
                  </td>
                  {show.includes("event") && (
                    <td>
                      <Link href={`/events/${d.event_id}`} onClick={(e) => e.stopPropagation()} className="mono">
                        {d.event_type}
                      </Link>
                      <div className="mono muted tiny">{d.event_id}</div>
                    </td>
                  )}
                  {show.includes("endpoint") && (
                    <td className="mono url-cell" title={d.endpoint_url}>
                      <Link href={`/endpoints/${d.endpoint_id}`} onClick={(e) => e.stopPropagation()}>
                        {d.endpoint_url}
                      </Link>
                    </td>
                  )}
                  <td className="mono nowrap">
                    {d.attempt_count}/{d.max_attempts}
                  </td>
                  <td className="mono">
                    {d.last_status_code != null ? (
                      <span className={`code-badge ${d.last_status_code < 300 ? "ok" : "bad"}`}>{d.last_status_code}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {d.next_attempt_at && (d.status === "retrying" || d.status === "pending") ? (
                      <Time iso={d.next_attempt_at} withRelative />
                    ) : (
                      <Time iso={d.updated_at} />
                    )}
                  </td>
                </tr>
                <tr className={`row-explain${bad ? " row-failed" : ""}`}>
                  <td colSpan={colCount}>
                    <DeliveryExplanation delivery={d} compact={!isOpen} />
                  </td>
                </tr>
                {isOpen && (
                  <tr className="row-detail">
                    <td colSpan={colCount}>
                      <div className="mono tiny muted">Delivery {d.id}</div>
                      <AttemptHistory deliveryId={d.id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
