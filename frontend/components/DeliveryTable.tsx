"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Attempt, type Delivery, type Replay } from "@/lib/api";
import { actorLabel, explainDelivery, formatDuration, formatLocal, formatUtc, STATUS_LABEL } from "@/lib/format";
import { ErrorBox, Loading, StatusPill, Time } from "./ui";
import { useMe } from "./MeContext";

const NEEDS_EXPLAINING = new Set(["failed", "retrying", "cancelled"]);

export function DeliveryExplanation({ delivery, compact }: { delivery: Delivery; compact?: boolean }) {
  const ex = explainDelivery(delivery);
  return (
    <div className={`explain explain-${ex.tone}${compact ? " explain-compact" : ""}`}>
      <span>{ex.text}</span>
      {!compact && ex.hint && <span className="explain-hint">{ex.hint}</span>}
    </div>
  );
}

function ReplayMarker({ replay }: { replay: Replay }) {
  const who = replay.requested_by.type === "api_key" ? `via ${actorLabel(replay.requested_by)}` : "from dashboard";
  return (
    <div className="replay-marker" title={formatUtc(replay.created_at)}>
      <span className="replay-marker-line" aria-hidden />
      <span className="replay-marker-text">
        ↻ Replayed {who} · {formatLocal(replay.created_at)} (was {STATUS_LABEL[replay.previous_status]?.toLowerCase() ?? replay.previous_status})
      </span>
      <span className="replay-marker-line" aria-hidden />
    </div>
  );
}

/**
 * Attempts, oldest first, with a "Replayed" divider before the first attempt
 * that followed each replay. `replayCount` avoids fetching /replays when there are none
 * and reloads the history when it changes (i.e. after a replay).
 */
export function AttemptHistory({ deliveryId, replayCount = 0 }: { deliveryId: string; replayCount?: number }) {
  const [attempts, setAttempts] = useState<Attempt[] | null>(null);
  const [replays, setReplays] = useState<Replay[]>([]);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [a, r] = await Promise.all([
        api.getAttempts(deliveryId),
        replayCount > 0 ? api.getReplays(deliveryId) : Promise.resolve({ data: [] as Replay[] }),
      ]);
      setAttempts([...a.data].sort((x, y) => x.attempt_number - y.attempt_number));
      setReplays(r.data);
    } catch (e) {
      setError(e);
    }
  }, [deliveryId, replayCount]);

  useEffect(() => {
    setAttempts(null);
    void load();
  }, [load]);

  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!attempts) return <Loading label="Loading attempts…" />;
  if (attempts.length === 0 && replays.length === 0)
    return <div className="muted small pad">No attempts yet — this delivery hasn&apos;t been sent.</div>;

  // Replays that come before attempt `n` (and after the previous attempt shown).
  let prev = 0;
  const before = (n: number) => {
    const out = replays.filter((r) => r.first_attempt_number > prev && r.first_attempt_number <= n);
    prev = n;
    return out;
  };
  const lastNum = attempts.length ? attempts[attempts.length - 1].attempt_number : 0;
  const trailing = replays.filter((r) => r.first_attempt_number > lastNum);

  return (
    <div className="attempts">
      <div className="attempts-head">
        <span>
          Attempt history
          {replays.length > 0 && (
            <span className="muted"> · replayed {replays.length} time{replays.length === 1 ? "" : "s"}</span>
          )}
        </span>
        <button type="button" className="btn btn-sm btn-ghost" onClick={load}>
          Refresh
        </button>
      </div>
      {attempts.map((a) => (
        <Fragment key={a.id}>
          {before(a.attempt_number).map((r) => (
            <ReplayMarker key={r.id} replay={r} />
          ))}
          <div className={`attempt ${a.success ? "attempt-ok" : "attempt-fail"}`}>
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
        </Fragment>
      ))}
      {trailing.map((r) => (
        <Fragment key={r.id}>
          <ReplayMarker replay={r} />
          <div className="muted small">Waiting for attempt #{r.first_attempt_number}…</div>
        </Fragment>
      ))}
    </div>
  );
}

/** "Replay" with an inline confirm; reports the updated delivery or shows the API's error. */
export function ReplayButton({
  delivery,
  onReplayed,
}: {
  delivery: Delivery;
  onReplayed: (d: Delivery, r: Replay) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const { can } = useMe();

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.replayDelivery(delivery.id);
      setAsking(false);
      onReplayed(res.delivery, res.replay);
    } catch (e) {
      setErr(e);
      setAsking(false);
    } finally {
      setBusy(false);
    }
  }

  if (!can("deliveries:replay")) return null;

  return (
    <span className="replay-action" onClick={(e) => e.stopPropagation()}>
      {asking ? (
        <span className="confirm">
          <span className="confirm-prompt confirm-prompt-neutral">Send again?</span>
          <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={go}>
            {busy ? "Replaying…" : "Replay"}
          </button>
          <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => setAsking(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button type="button" className="btn btn-sm" onClick={() => setAsking(true)} title="Queue this delivery to be sent again">
          ↻ Replay
        </button>
      )}
      {err != null && (
        <span className="replay-error" role="alert">
          {errorMessage(err)}
        </span>
      )}
    </span>
  );
}

type Column = "event" | "endpoint";

/**
 * Table of deliveries; click a row to expand its attempt history.
 * Rows with `replayable` get a Replay action; replayed rows update in place and
 * `onReplayed` lets the page refresh anything else (counts, polling).
 */
export function DeliveryTable({
  deliveries,
  show = ["event", "endpoint"],
  onReplayed,
}: {
  deliveries: Delivery[];
  show?: Column[];
  onReplayed?: (d: Delivery) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Record<string, Delivery>>({});
  const [notice, setNotice] = useState<string | null>(null);

  // Fresh data from the parent wins over local updates.
  useEffect(() => setUpdated({}), [deliveries]);

  const rows = deliveries.map((d) => updated[d.id] ?? d);
  const anyReplayable = rows.some((d) => d.replayable);
  const colCount = 4 + show.length + (anyReplayable ? 1 : 0);

  function replayed(d: Delivery, r: Replay) {
    setUpdated((u) => ({ ...u, [d.id]: d }));
    setNotice(`Replay queued for ${d.endpoint_url}. It will be sent again shortly as attempt #${r.first_attempt_number}.`);
    onReplayed?.(d);
  }

  return (
    <div className="table-wrap">
      {notice && (
        <div className="alert alert-success table-notice" role="status">
          <span>{notice}</span>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </div>
      )}
      <table className="table">
        <thead>
          <tr>
            <th>Status</th>
            {show.includes("event") && <th>Event</th>}
            {show.includes("endpoint") && <th>Endpoint</th>}
            <th>Attempts</th>
            <th>Last code</th>
            <th>Next retry / updated</th>
            {anyReplayable && <th className="right"><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const isOpen = open === d.id;
            const bad = d.status === "failed";
            return (
              <Fragment key={d.id}>
                <tr
                  className={`row-click${isOpen ? " row-open" : ""}${bad ? " row-failed" : ""}`}
                  onClick={() => setOpen(isOpen ? null : d.id)}
                  aria-expanded={isOpen}
                >
                  <td className="nowrap">
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
                  <td
                    className="mono nowrap"
                    title={d.replay_count > 0 ? `${d.attempt_count} attempts in total, including earlier runs` : undefined}
                  >
                    {d.run_attempt_count}/{d.run_max_attempts}
                    {d.replay_count > 0 && (
                      <span
                        className="replay-badge"
                        title={`Replayed ${d.replay_count} time${d.replay_count === 1 ? "" : "s"}${
                          d.last_replayed_at ? `, last at ${formatUtc(d.last_replayed_at)}` : ""
                        }`}
                      >
                        ↻{d.replay_count}
                      </span>
                    )}
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
                  {anyReplayable && (
                    <td className="right actions-cell">{d.replayable && <ReplayButton delivery={d} onReplayed={replayed} />}</td>
                  )}
                </tr>
                {/* The columns already say "delivered, 200"; spell things out only where it helps. */}
                {(isOpen || NEEDS_EXPLAINING.has(d.status)) && (
                  <tr className={`row-explain${bad ? " row-failed" : ""}`}>
                    <td colSpan={colCount}>
                      <DeliveryExplanation delivery={d} compact={!isOpen} />
                    </td>
                  </tr>
                )}
                {isOpen && (
                  <tr className="row-detail">
                    <td colSpan={colCount}>
                      <div className="mono tiny muted">
                        Delivery {d.id}
                        {d.replay_count > 0 && d.last_replayed_at && <> · last replayed {formatLocal(d.last_replayed_at)}</>}
                      </div>
                      <AttemptHistory deliveryId={d.id} replayCount={d.replay_count} />
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
