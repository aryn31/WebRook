"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage, type Delivery, type EventReplayed, type HookEvent, type ReplaySkipped } from "@/lib/api";
import { INSPECTED_KEY, shortId } from "@/lib/format";
import { DeliveryTable } from "@/components/DeliveryTable";
import { useMe } from "@/components/MeContext";
import { CopyButton, CountsPills, Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

const ACTIVE = new Set(["pending", "processing", "retrying"]);

/** Skipped list from either a 202 result or a 409 nothing_to_replay error's details. */
function skippedFrom(err: unknown): ReplaySkipped[] {
  if (err instanceof ApiError && Array.isArray(err.details)) {
    return err.details.filter(
      (d): d is ReplaySkipped => !!d && typeof d === "object" && "delivery_id" in d && "reason" in d,
    );
  }
  return [];
}

function SkippedList({ skipped, deliveries }: { skipped: ReplaySkipped[]; deliveries: Delivery[] }) {
  if (skipped.length === 0) return null;
  const url = (id: string) => deliveries.find((d) => d.id === id)?.endpoint_url;
  return (
    <ul className="result-list">
      {skipped.map((s) => (
        <li key={s.delivery_id}>
          <span className="mono">{url(s.delivery_id) ?? shortId(s.delivery_id)}</span> — {s.reason}
        </li>
      ))}
    </ul>
  );
}

/** "Replay failed deliveries" for the whole event, with an inline confirm and a result summary. */
function ReplayEventPanel({
  eventId,
  deliveries,
  onDone,
}: {
  eventId: string;
  deliveries: Delivery[];
  onDone: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EventReplayed | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const canReplay = useMe().can("deliveries:replay");
  const replayable = canReplay ? deliveries.filter((d) => d.replayable) : [];

  async function go() {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      setResult(await api.replayEvent(eventId));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
      setAsking(false);
      onDone();
    }
  }

  const n = replayable.length;
  return (
    <>
      {replayable.length > 0 &&
        (asking ? (
          <span className="confirm">
            <span className="confirm-prompt confirm-prompt-neutral">
              Send {n} failed/cancelled deliver{n === 1 ? "y" : "ies"} again?
            </span>
            <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={go}>
              {busy ? "Replaying…" : `Replay ${n}`}
            </button>
            <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => setAsking(false)}>
              Cancel
            </button>
          </span>
        ) : (
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setAsking(true)}>
            ↻ Replay failed deliveries
          </button>
        ))}
      {(result || err != null) && (
        <div className="replay-result">
          {result && (
            <div className={`alert ${result.replayed.length > 0 ? "alert-success" : "alert-warning"}`} role="status">
              <div>
                <strong>
                  Replayed {result.replayed.length} deliver{result.replayed.length === 1 ? "y" : "ies"}
                  {result.skipped.length > 0 && `, skipped ${result.skipped.length}`}.
                </strong>
                {result.skipped.length > 0 && <SkippedList skipped={result.skipped} deliveries={deliveries} />}
              </div>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setResult(null)}>
                Dismiss
              </button>
            </div>
          )}
          {err != null && (
            <div className="alert alert-error" role="alert">
              <div>
                <strong>{errorMessage(err)}</strong>
                <SkippedList skipped={skippedFrom(err)} deliveries={deliveries} />
              </div>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setErr(null)}>
                Dismiss
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export default function EventDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [event, setEvent] = useState<HookEvent | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [deliveries, setDeliveries] = useState<Delivery[] | null>(null);
  const [dErr, setDErr] = useState<unknown>(null);

  const loadEvent = useCallback(async () => {
    setErr(null);
    try {
      setEvent(await api.getEvent(id));
    } catch (e) {
      setErr(e);
    }
  }, [id]);

  const loadDeliveries = useCallback(async () => {
    setDErr(null);
    try {
      setDeliveries((await api.getEventDeliveries(id)).data);
    } catch (e) {
      setDErr(e);
    }
  }, [id]);

  useEffect(() => {
    void loadEvent();
    void loadDeliveries();
    try {
      window.localStorage.setItem(INSPECTED_KEY, "1");
    } catch {
      /* storage unavailable */
    }
  }, [loadEvent, loadDeliveries]);

  // Poll while any delivery is still in flight.
  const active = deliveries?.some((d) => ACTIVE.has(d.status)) ?? false;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => {
      void loadDeliveries();
      void loadEvent();
    }, 5000);
    return () => clearInterval(t);
  }, [active, loadDeliveries, loadEvent]);

  function refresh() {
    void loadDeliveries();
    void loadEvent();
  }

  if (err) {
    const notFound = err instanceof ApiError && err.status === 404;
    return (
      <div className="page">
        <PageHeader title="Event" />
        {notFound ? (
          <Empty title="Event not found">
            Check the ID, or <Link href="/events">browse all events</Link>.
          </Empty>
        ) : (
          <ErrorBox error={err} onRetry={loadEvent} />
        )}
      </div>
    );
  }
  if (!event) return <div className="page"><Loading /></div>;

  const payload = JSON.stringify(event.data, null, 2);

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link href="/events">Events</Link> <span className="muted">/</span>
      </div>
      <PageHeader
        title={<span className="mono">{event.event_type}</span>}
        sub={
          <span className="row-wrap">
            <span className="mono">{event.id}</span>
            <CopyButton text={event.id} label="Copy ID" />
            <span className="muted">·</span>
            <Time iso={event.created_at} withRelative />
            {event.idempotency_key && (
              <>
                <span className="muted">·</span>
                <span className="small" title="Idempotency-Key sent with this event">
                  Idempotency key <code className="mono">{event.idempotency_key}</code>
                </span>
              </>
            )}
          </span>
        }
      />

      <section className="card">
        <div className="card-head">
          <h2>Deliveries</h2>
          <span className="row-wrap">
            <CountsPills counts={event.deliveries} />
            {active && <span className="muted small">Auto-refreshing…</span>}
            <button type="button" className="btn btn-sm btn-ghost" onClick={refresh}>
              Refresh
            </button>
          </span>
        </div>
        <ErrorBox error={dErr} onRetry={loadDeliveries} />
        {!deliveries && !dErr && <Loading />}
        {deliveries && deliveries.length === 0 && (
          <Empty title="No deliveries">
            No enabled endpoint was subscribed to <code className="mono">{event.event_type}</code> when this event was sent.{" "}
            <Link href="/endpoints">Add or edit an endpoint</Link>
          </Empty>
        )}
        {deliveries && deliveries.length > 0 && (
          <>
            <div className="row replay-bar">
              <p className="muted small grow">Click a delivery to see each attempt and the response your endpoint returned.</p>
              <ReplayEventPanel eventId={event.id} deliveries={deliveries} onDone={refresh} />
            </div>
            <DeliveryTable deliveries={deliveries} show={["endpoint"]} onReplayed={refresh} />
          </>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Payload</h2>
          <CopyButton text={payload} label="Copy JSON" />
        </div>
        <pre className="mono payload">{payload}</pre>
      </section>
    </div>
  );
}
