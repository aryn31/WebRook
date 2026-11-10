"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, errorMessage, type Attempt, type Delivery, type Endpoint, type EndpointWithHealth } from "@/lib/api";
import { formatDuration, relative } from "@/lib/format";
import { portalApi, takeToken, type PortalApi, type PortalMe } from "@/lib/portal";
import { HealthBadge } from "@/components/EndpointHealth";
import { EventTypeList, EventTypesInput } from "@/components/EventTypesInput";
import { SecurityBadge, SecurityCheckCard } from "@/components/SecurityCheck";
import { ThemeToggle } from "@/components/ThemeToggle";
import { SignatureHelp } from "@/components/SignatureHelp";
import { ConfirmButton, CopyButton, Empty, ErrorBox, Loading, SecretBox, StatusPill, Time } from "@/components/ui";

type View = { kind: "list" } | { kind: "new" } | { kind: "endpoint"; id: string };

export function PortalApp() {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [me, setMe] = useState<PortalMe | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [view, setView] = useState<View>({ kind: "list" });

  useEffect(() => setToken(takeToken()), []);
  const client = useMemo(() => (token ? portalApi(token) : null), [token]);

  useEffect(() => {
    if (token === null) setFatal("This page needs a link from the app you use. Open its webhook settings again.");
    if (!client) return;
    client.me().then(setMe).catch((e) => setFatal(errorMessage(e)));
  }, [client, token]);

  // Any expired-link answer later on replaces the page with the same message.
  const onError = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) setFatal(e.message);
  }, []);

  const title = me?.brand_name ? `${me.brand_name} webhooks` : "Webhooks";

  return (
    <div className="portal">
      <header className="portal-top">
        <div className="portal-top-inner">
          <div className="portal-title">
            <span className="portal-mark" aria-hidden>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z" /></svg>
            </span>
            <div>
              <div className="portal-name">{title}</div>
              {me && <div className="portal-sub">{me.consumer.name ?? me.consumer.uid}</div>}
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="portal-main">
        {fatal ? (
          <div className="portal-fatal">
            <h1>Link expired</h1>
            <p className="muted">{fatal}</p>
          </div>
        ) : !me || !client ? (
          <Loading />
        ) : view.kind === "new" ? (
          <NewEndpoint client={client} me={me} onError={onError} onDone={(id) => setView(id ? { kind: "endpoint", id } : { kind: "list" })} />
        ) : view.kind === "endpoint" ? (
          <EndpointView client={client} id={view.id} onError={onError} onBack={() => setView({ kind: "list" })} />
        ) : (
          <EndpointList client={client} onError={onError} onOpen={(id) => setView({ kind: "endpoint", id })}
            onNew={() => setView({ kind: "new" })} />
        )}
      </main>

      <footer className="portal-foot">
        Webhook delivery by <a href="/" target="_blank" rel="noreferrer">HookFlow</a>
      </footer>
    </div>
  );
}

function EndpointList({ client, onOpen, onNew, onError }: {
  client: PortalApi; onOpen: (id: string) => void; onNew: () => void; onError: (e: unknown) => void;
}) {
  const [items, setItems] = useState<EndpointWithHealth[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    client.listEndpoints().then((r) => setItems(r.data)).catch((e) => { setErr(e); onError(e); });
  }, [client, onError]);

  return (
    <>
      <div className="portal-head">
        <div>
          <h1>Endpoints</h1>
          <p className="muted">URLs on your servers that receive events. Each request is signed so you can check it came from us.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={onNew}>+ Add endpoint</button>
      </div>
      <ErrorBox error={err} />
      {!items && !err && <Loading />}
      {items && items.length === 0 && (
        <section className="card">
          <Empty title="No endpoints yet">
            Add the URL where you want to receive events.
            <button type="button" className="btn btn-sm btn-primary" onClick={onNew}>Add endpoint</button>
          </Empty>
        </section>
      )}
      {items && items.length > 0 && (
        <ul className="ep-grid">
          {items.map((e) => {
            const pct = e.health.success_rate == null ? null : Math.round(e.health.success_rate * 100);
            return (
              <li key={e.id}>
                <button type="button" className={`ep-card ep-${e.enabled ? e.health.state : "off"} portal-card`} onClick={() => onOpen(e.id)}>
                  <div className="ep-card-top">
                    <span className="ep-card-dot" aria-hidden />
                    <span className="ep-card-name">{e.description || new URL(e.url).host}</span>
                    <SecurityBadge check={e.security_check} />
                    {e.enabled ? <span className="badge badge-green">Enabled</span> : <span className="badge badge-grey">Disabled</span>}
                  </div>
                  <div className="ep-card-url mono">{e.url}</div>
                  <div className="ep-card-health">
                    <span className="ep-card-bar" aria-hidden><span style={{ width: `${pct ?? 0}%` }} /></span>
                    <HealthBadge health={e.health} />
                  </div>
                  <div className="ep-card-foot"><EventTypeList types={e.event_types} /></div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

function NewEndpoint({ client, me, onDone, onError }: {
  client: PortalApi; me: PortalMe; onDone: (id: string | null) => void; onError: (e: unknown) => void;
}) {
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [types, setTypes] = useState<string[]>(["*"]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [created, setCreated] = useState<(Endpoint & { signing_secret: string }) | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      setCreated(await client.createEndpoint({ url: url.trim(), description: description.trim() || null, event_types: types }));
    } catch (x) {
      setErr(x);
      onError(x);
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <section className="card portal-narrow">
        <div className="card-head"><h2>Endpoint added</h2></div>
        <SecretBox title="Signing secret" value={created.signing_secret}
          warning="Store this on your server and verify every request with it, using any Standard Webhooks library or the HookFlow-Signature header. You can view it again later on the endpoint's page." />
        <div className="row mt">
          <button type="button" className="btn btn-primary" onClick={() => onDone(created.id)}>Open endpoint</button>
          <button type="button" className="btn" onClick={() => onDone(null)}>Back to endpoints</button>
        </div>
      </section>
    );
  }

  const suggestions = me.event_types.filter((t) => !types.includes(t));
  return (
    <section className="card portal-narrow">
      <button type="button" className="link-button portal-back" onClick={() => onDone(null)}>← Endpoints</button>
      <div className="card-head"><h2>Add an endpoint</h2></div>
      <form onSubmit={submit} className="stack">
        <label className="field">
          <span className="field-label">URL</span>
          <input className="input mono" placeholder="https://example.com/webhooks" value={url} onChange={(e) => setUrl(e.target.value)} required />
        </label>
        <label className="field">
          <span className="field-label">Description <span className="muted">(optional)</span></span>
          <input className="input" placeholder="Production" value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="field">
          <span className="field-label">Events to receive</span>
          <EventTypesInput value={types} onChange={setTypes} />
          {suggestions.length > 0 && (
            <div className="portal-suggest">
              <span className="muted small">Available:</span>
              {suggestions.slice(0, 20).map((t) => (
                <button key={t} type="button" className="chip-button mono"
                  onClick={() => setTypes((prev) => [...prev.filter((x) => x !== "*"), t])}>+ {t}</button>
              ))}
            </div>
          )}
        </div>
        <ErrorBox error={err} />
        <div><button type="submit" className="btn btn-primary" disabled={busy || !url.trim()}>{busy ? "Adding…" : "Add endpoint"}</button></div>
      </form>
    </section>
  );
}

function EndpointView({ client, id, onBack, onError }: {
  client: PortalApi; id: string; onBack: () => void; onError: (e: unknown) => void;
}) {
  const [e, setE] = useState<EndpointWithHealth | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    client.getEndpoint(id).then(setE).catch((x) => { setErr(x); onError(x); });
  }, [client, id, onError]);
  useEffect(load, [load]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (x) {
      setErr(x);
      onError(x);
    } finally {
      setBusy(false);
    }
  }

  if (!e) return err ? <ErrorBox error={err} /> : <Loading />;

  return (
    <div className="stack portal-detail">
      <button type="button" className="link-button portal-back" onClick={onBack}>← Endpoints</button>
      <div className="portal-head">
        <div>
          <h1>{e.description || new URL(e.url).host}</h1>
          <div className="row-wrap">
            {e.enabled ? <span className="badge badge-green">Enabled</span> : <span className="badge badge-grey">Disabled</span>}
            <SecurityBadge check={e.security_check} />
            <span className="mono detail-url">{e.url}</span>
          </div>
        </div>
        <div className="page-actions">
          <button type="button" className="btn" disabled={busy}
            onClick={() => act(async () => { await client.updateEndpoint(e.id, { enabled: !e.enabled }); load(); })}>
            {e.enabled ? "Disable" : "Enable"}
          </button>
          <ConfirmButton label="Delete" prompt="Delete this endpoint? Nothing more will be sent to it."
            confirmLabel="Delete" onConfirm={() => act(async () => { await client.deleteEndpoint(e.id); onBack(); })} />
        </div>
      </div>
      <ErrorBox error={err} />

      <section className="card">
        <div className="card-head"><h2>Health</h2><span className="muted small">Last 24 hours</span></div>
        <HealthBadge health={e.health} detailed />
        <div className="mt"><span className="muted small">Receives: </span><EventTypeList types={e.event_types} /></div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Signing secret</h2></div>
        <SignatureHelp format={e.secret_format} />
        <div className="secret-row">
          <code className="mono secret-value">{secret ?? "whsec_••••••••••••••••••••••••"}</code>
          {secret ? <CopyButton text={secret} /> : (
            <button type="button" className="btn btn-sm" disabled={busy}
              onClick={() => act(async () => setSecret((await client.getSecret(e.id)).signing_secret))}>Reveal</button>
          )}
        </div>
      </section>

      <SecurityCheckCard endpoint={e} canRun onChecked={(x) => setE({ ...e, ...x })} runCheck={client.securityCheck} />

      <Deliveries client={client} endpointId={e.id} onError={onError} />
    </div>
  );
}

function Deliveries({ client, endpointId, onError }: { client: PortalApi; endpointId: string; onError: (e: unknown) => void }) {
  const [items, setItems] = useState<Delivery[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<Record<string, Attempt[]>>({});

  const load = useCallback(() => {
    client.listDeliveries(endpointId).then((r) => setItems(r.data)).catch((x) => { setErr(x); onError(x); });
  }, [client, endpointId, onError]);
  useEffect(load, [load]);

  async function toggle(d: Delivery) {
    if (open === d.id) return setOpen(null);
    setOpen(d.id);
    if (!attempts[d.id]) {
      try {
        const r = await client.listAttempts(d.id);
        setAttempts((a) => ({ ...a, [d.id]: r.data }));
      } catch (x) {
        setErr(x);
      }
    }
  }

  async function replay(d: Delivery) {
    setErr(null);
    try {
      const r = await client.replay(d.id);
      setItems((prev) => (prev ?? []).map((x) => (x.id === d.id ? r.delivery : x)));
      setAttempts((a) => { const n = { ...a }; delete n[d.id]; return n; });
    } catch (x) {
      setErr(x);
      onError(x);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Recent deliveries</h2>
        <button type="button" className="btn btn-sm btn-ghost" onClick={load}>Refresh</button>
      </div>
      <ErrorBox error={err} />
      {!items && !err && <Loading />}
      {items && items.length === 0 && <Empty title="Nothing sent yet">Events sent to this endpoint will show up here.</Empty>}
      {items && items.length > 0 && (
        <ul className="pd-list">
          {items.map((d) => (
            <li key={d.id} className={`pd-item${d.status === "failed" ? " pd-failed" : ""}`}>
              <button type="button" className="pd-row" onClick={() => toggle(d)} aria-expanded={open === d.id}>
                <StatusPill status={d.status} />
                <span className="pd-type mono">{d.event_type}</span>
                <span className="pd-meta">
                  {d.last_status_code != null && <b className="mono">{d.last_status_code}</b>}
                  {d.run_attempt_count}/{d.run_max_attempts} attempts
                </span>
                <span className="pd-time"><Time iso={d.updated_at} /></span>
              </button>
              {d.replayable && <button type="button" className="btn btn-sm pd-replay" onClick={() => replay(d)}>↻ Replay</button>}
              {open === d.id && (
                <div className="pd-attempts">
                  {d.last_error && <div className="health-error small">{d.last_error}</div>}
                  {!attempts[d.id] ? <Loading rows={1} /> : attempts[d.id].length === 0 ? (
                    <span className="muted small">No attempts yet.</span>
                  ) : attempts[d.id].map((a) => (
                    <div key={a.id} className={`pd-attempt${a.success ? " ok" : ""}`}>
                      <span className="mono">#{a.attempt_number}</span>
                      <span className="mono">{a.response_status ?? "—"}</span>
                      <span>{a.error ?? (a.success ? "Delivered" : "Failed")}</span>
                      <span className="muted small">{formatDuration(a.duration_ms)} · {relative(a.started_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
