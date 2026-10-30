"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Delivery, type HookEvent } from "@/lib/api";
import { INSPECTED_KEY } from "@/lib/format";
import { DeliveryTable } from "@/components/DeliveryTable";
import { CopyButton, CountsPills, Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

const ACTIVE = new Set(["pending", "processing", "retrying"]);

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
          </span>
        }
      />

      <section className="card">
        <div className="card-head">
          <h2>Deliveries</h2>
          <span className="row-wrap">
            <CountsPills counts={event.deliveries} />
            {active && <span className="muted small">Auto-refreshing…</span>}
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => { void loadDeliveries(); void loadEvent(); }}>
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
            <p className="muted small">Click a delivery to see each attempt and the response your endpoint returned.</p>
            <DeliveryTable deliveries={deliveries} show={["endpoint"]} />
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
