"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type EventAccepted, type EventSummary } from "@/lib/api";
import { validateEventType } from "@/components/EventTypesInput";
import { useMe } from "@/components/MeContext";
import { CountsPills, Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

type Filters = { event_type: string; after: string; before: string };

/** yyyy-mm-dd (local) → ISO at local start of that day (+ days). */
function dayToIso(day: string, addDays = 0): string | undefined {
  if (!day) return undefined;
  const [y, m, d] = day.split("-").map(Number);
  if (!y || !m || !d) return undefined;
  return new Date(y, m - 1, d + addDays).toISOString();
}

const SAMPLE = `{
  "order_id": "ord_123",
  "amount": 4999,
  "currency": "usd"
}`;

const MAX_BYTES = 1024 * 1024;

function SendEventPanel({ onSent }: { onSent: () => void }) {
  const [eventType, setEventType] = useState("order.created");
  const [json, setJson] = useState(SAMPLE);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [result, setResult] = useState<EventAccepted | null>(null);

  let jsonError: string | null = null;
  let parsed: Record<string, unknown> | null = null;
  try {
    const v: unknown = JSON.parse(json);
    if (v === null || typeof v !== "object" || Array.isArray(v)) jsonError = "Data must be a JSON object, e.g. { \"key\": \"value\" }.";
    else parsed = v as Record<string, unknown>;
  } catch (e) {
    jsonError = `Invalid JSON: ${e instanceof Error ? e.message : "could not parse"}`;
  }
  const typeError = eventType ? validateEventType(eventType.trim()) : "Event type is required.";
  const size = new TextEncoder().encode(json).length;
  const sizeError = size > MAX_BYTES ? "Payload is larger than 1 MiB." : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!parsed || typeError || sizeError) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      setResult(await api.sendEvent(eventType.trim(), parsed));
      onSent();
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <label className="field">
        <span className="field-label">Event type</span>
        <input className="input mono" value={eventType} onChange={(e) => setEventType(e.target.value)} />
        {typeError && eventType && <span className="field-hint text-failed">{typeError}</span>}
      </label>
      <label className="field">
        <span className="field-label">Data (JSON object)</span>
        <textarea
          className="input mono textarea"
          rows={8}
          spellCheck={false}
          value={json}
          onChange={(e) => setJson(e.target.value)}
        />
        <span className={`field-hint${jsonError || sizeError ? " text-failed" : ""}`}>
          {jsonError ?? sizeError ?? "Valid JSON ✓"}
        </span>
      </label>
      <ErrorBox error={err} />
      <div className="row-wrap">
        <button type="submit" className="btn btn-primary" disabled={busy || !!jsonError || !!typeError || !!sizeError}>
          {busy ? "Sending…" : "Send event"}
        </button>
        {parsed && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setJson(JSON.stringify(parsed, null, 2))}>
            Format JSON
          </button>
        )}
        {result && (
          <span className="small">
            Accepted · {result.delivery_count} deliver{result.delivery_count === 1 ? "y" : "ies"} ·{" "}
            <Link href={`/events/${result.event_id}`} className="mono">
              {result.event_id} →
            </Link>
          </span>
        )}
      </div>
      {result && result.delivery_count === 0 && (
        <div className="alert alert-warning">
          No endpoint is subscribed to <code className="mono">{eventType}</code>, so nothing will be delivered.{" "}
          <Link href="/endpoints">Manage endpoints</Link>
        </div>
      )}
    </form>
  );
}

export default function EventsPage() {
  const router = useRouter();
  const [draft, setDraft] = useState<Filters>({ event_type: "", after: "", before: "" });
  const [filters, setFilters] = useState<Filters>(draft);
  const [items, setItems] = useState<EventSummary[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [showSend, setShowSend] = useState(false);
  const canSend = useMe().can("events:write");

  const load = useCallback(
    async (after: string | null) => {
      setErr(null);
      if (after) setLoadingMore(true);
      else setItems(null);
      try {
        const res = await api.listEvents({
          limit: 25,
          cursor: after,
          event_type: filters.event_type.trim() || undefined,
          created_after: dayToIso(filters.after),
          created_before: dayToIso(filters.before, 1),
        });
        setItems((prev) => (after ? [...(prev ?? []), ...res.data] : res.data));
        setCursor(res.next_cursor);
      } catch (e) {
        setErr(e);
      } finally {
        setLoadingMore(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    void load(null);
  }, [load]);

  const filtered = !!(filters.event_type || filters.after || filters.before);

  return (
    <div className="page">
      <PageHeader
        title="Events"
        sub="Everything your application sent to HookFlow, newest first."
        actions={
          canSend && (
            <button type="button" className={`btn${showSend ? "" : " btn-primary"}`} onClick={() => setShowSend((v) => !v)}>
              {showSend ? "Close" : "Send event"}
            </button>
          )
        }
      />

      {showSend && (
        <section className="card">
          <div className="card-head">
            <h2>Send an event</h2>
            <span className="muted small">Uses your dashboard session — no API key needed.</span>
          </div>
          <SendEventPanel onSent={() => void load(null)} />
        </section>
      )}

      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <label className="field">
          <span className="field-label">Event type</span>
          <input
            className="input mono"
            placeholder="order.created"
            value={draft.event_type}
            onChange={(e) => setDraft({ ...draft, event_type: e.target.value })}
          />
        </label>
        <label className="field">
          <span className="field-label">From</span>
          <input type="date" className="input" value={draft.after} onChange={(e) => setDraft({ ...draft, after: e.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">To</span>
          <input type="date" className="input" value={draft.before} onChange={(e) => setDraft({ ...draft, before: e.target.value })} />
        </label>
        <div className="filters-actions">
          <button type="submit" className="btn">
            Apply
          </button>
          {filtered && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                const empty = { event_type: "", after: "", before: "" };
                setDraft(empty);
                setFilters(empty);
              }}
            >
              Clear
            </button>
          )}
        </div>
      </form>

      <section className="card card-flush">
        <ErrorBox error={err} onRetry={() => load(null)} />
        {!items && !err && <Loading />}
        {items && items.length === 0 &&
          (filtered ? (
            <Empty title="No events match these filters">Try a different event type or date range.</Empty>
          ) : (
            <Empty title="No events yet">
              {canSend ? (
                <>
                  Send one with your API key, or{" "}
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowSend(true)}>
                    send a test event
                  </button>
                </>
              ) : (
                "Events sent to this account will show up here."
              )}
            </Empty>
          ))}
        {items && items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Event ID</th>
                  <th>Type</th>
                  <th>Created</th>
                  <th>Deliveries</th>
                </tr>
              </thead>
              <tbody>
                {items.map((ev) => (
                  <tr key={ev.id} className={`row-click${ev.deliveries.failed > 0 ? " row-failed" : ""}`} onClick={() => router.push(`/events/${ev.id}`)}>
                    <td className="mono">
                      <Link href={`/events/${ev.id}`} onClick={(e) => e.stopPropagation()}>
                        {ev.id}
                      </Link>
                    </td>
                    <td className="mono">{ev.event_type}</td>
                    <td>
                      <Time iso={ev.created_at} />
                    </td>
                    <td>
                      <CountsPills counts={ev.deliveries} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {cursor && (
          <div className="load-more">
            <button type="button" className="btn" disabled={loadingMore} onClick={() => load(cursor)}>
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
