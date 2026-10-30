"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Delivery, type Endpoint, type EventAccepted } from "@/lib/api";
import { EventTypeList, EventTypesInput } from "@/components/EventTypesInput";
import { DeliveryTable } from "@/components/DeliveryTable";
import { MaxAttemptsInput, maxAttemptsError } from "@/components/MaxAttemptsInput";
import { ConfirmButton, CopyButton, Empty, ErrorBox, Loading, PageHeader, SecretBox, Time } from "@/components/ui";
import { formatClock, formatSeconds, formatUtc, GRACE_DEFAULT, GRACE_OPTIONS, isFuture, relative } from "@/lib/format";

function EditForm({ endpoint, onSaved, onCancel }: { endpoint: Endpoint; onSaved: (e: Endpoint) => void; onCancel: () => void }) {
  const [url, setUrl] = useState(endpoint.url);
  const [description, setDescription] = useState(endpoint.description ?? "");
  const [types, setTypes] = useState<string[]>(endpoint.event_types);
  const [maxAttempts, setMaxAttempts] = useState(String(endpoint.max_attempts));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [localErr, setLocalErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setLocalErr(null);
    try {
      new URL(url.trim());
    } catch {
      setLocalErr("Enter a full URL, e.g. https://example.com/webhooks.");
      return;
    }
    if (types.length === 0) {
      setLocalErr("Choose at least one event type, or select All events.");
      return;
    }
    const maErr = maxAttemptsError(maxAttempts);
    if (maErr) {
      setLocalErr(maErr);
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const saved = await api.updateEndpoint(endpoint.id, {
        url: url.trim(),
        description: description.trim() || null,
        event_types: types,
        ...(Number(maxAttempts) !== endpoint.max_attempts ? { max_attempts: Number(maxAttempts) } : {}),
      });
      onSaved(saved);
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <label className="field">
        <span className="field-label">URL</span>
        <input className="input mono" type="url" value={url} onChange={(e) => setUrl(e.target.value)} required />
      </label>
      <label className="field">
        <span className="field-label">Description</span>
        <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <EventTypesInput value={types} onChange={setTypes} />
      <MaxAttemptsInput value={maxAttempts} onChange={setMaxAttempts} editing />
      {localErr && <div className="alert alert-error">{localErr}</div>}
      <ErrorBox error={err} />
      <div className="row">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Saving…" : "Save changes"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function SecretSection({
  endpoint,
  onRotated,
}: {
  endpoint: Endpoint;
  onRotated: (previousSecretExpiresAt: string | null) => void;
}) {
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [rotating, setRotating] = useState(false);
  const [grace, setGrace] = useState(GRACE_DEFAULT);
  const [rotated, setRotated] = useState<{ secret: string; graceSeconds: number; expiresAt: string | null } | null>(null);

  // Viewing the secret is audited, so it's only fetched on an explicit click.
  async function reveal() {
    setBusy(true);
    setErr(null);
    try {
      setSecret((await api.getEndpointSecret(endpoint.id)).signing_secret);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  async function rotate() {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.rotateEndpointSecret(endpoint.id, grace);
      setRotated({ secret: res.signing_secret, graceSeconds: grace, expiresAt: res.previous_secret_expires_at });
      setSecret(null);
      setRotating(false);
      onRotated(res.previous_secret_expires_at);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  const graceActive = isFuture(endpoint.previous_secret_expires_at);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Signing secret</h2>
      </div>
      <p className="muted small">
        Use this secret to verify the <code className="mono">HookFlow-Signature</code> header: HMAC-SHA256 of{" "}
        <code className="mono">{"{timestamp}.{raw body}"}</code>.
      </p>

      {graceActive && !rotated && (
        <div className="alert alert-info mb">
          <span>
            Rotation in progress: the previous secret also signs requests until{" "}
            <strong title={formatUtc(endpoint.previous_secret_expires_at)}>{formatClock(endpoint.previous_secret_expires_at)}</strong> (
            {relative(endpoint.previous_secret_expires_at)}). The header carries two signatures,{" "}
            <code className="mono">v1=&lt;new&gt;,v1=&lt;old&gt;</code> — accept either.
          </span>
        </div>
      )}

      {rotated ? (
        <div className="stack">
          <SecretBox
            title="New signing secret"
            value={rotated.secret}
            warning={
              rotated.graceSeconds > 0 && rotated.expiresAt
                ? `Old secret still signs until ${formatClock(rotated.expiresAt)} (${formatSeconds(rotated.graceSeconds)}). Deploy the new secret to your endpoint before then.`
                : "The old secret stopped working immediately. Update your endpoint with the new secret now."
            }
          />
          <div className="row">
            <button type="button" className="btn btn-sm" onClick={() => setRotated(null)}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <div className="secret-row">
          <code className="mono secret-value">{secret ?? "whsec_••••••••••••••••••••••••"}</code>
          {secret ? (
            <>
              <CopyButton text={secret} />
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setSecret(null)}>
                Hide
              </button>
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={reveal} disabled={busy}>
              {busy && !rotating ? "Revealing…" : "Reveal"}
            </button>
          )}
          {!rotating && (
            <button type="button" className="btn btn-sm btn-danger-ghost" onClick={() => setRotating(true)}>
              Rotate…
            </button>
          )}
        </div>
      )}

      {rotating && !rotated && (
        <div className="rotate-panel">
          <div className="field">
            <span className="field-label">Keep the old secret working for</span>
            <div className="segmented" role="radiogroup" aria-label="Grace period">
              {GRACE_OPTIONS.map((o) => (
                <button
                  key={o.seconds}
                  type="button"
                  role="radio"
                  aria-checked={grace === o.seconds}
                  className={grace === o.seconds ? "active" : ""}
                  onClick={() => setGrace(o.seconds)}
                >
                  {o.label}
                </button>
              ))}
            </div>
            <span className="field-hint">
              {grace > 0
                ? `For ${formatSeconds(grace)} HookFlow signs with both the new and the old secret, so you can deploy the new one without dropping webhooks.`
                : "The old secret stops working immediately — requests signed after this will fail verification until you deploy the new secret."}
            </span>
          </div>
          <div className="row">
            <button type="button" className={`btn ${grace > 0 ? "btn-primary" : "btn-danger"}`} onClick={rotate} disabled={busy}>
              {busy ? "Rotating…" : "Rotate secret"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setRotating(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <ErrorBox error={err} />
    </section>
  );
}

export default function EndpointDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();

  const [endpoint, setEndpoint] = useState<Endpoint | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [actionErr, setActionErr] = useState<unknown>(null);

  const [deliveries, setDeliveries] = useState<Delivery[] | null>(null);
  const [dCursor, setDCursor] = useState<string | null>(null);
  const [dErr, setDErr] = useState<unknown>(null);
  const [dLoadingMore, setDLoadingMore] = useState(false);

  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState<EventAccepted | null>(null);
  const [testErr, setTestErr] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      setEndpoint(await api.getEndpoint(id));
    } catch (e) {
      setLoadErr(e);
    }
  }, [id]);

  const loadDeliveries = useCallback(
    async (after: string | null) => {
      setDErr(null);
      if (after) setDLoadingMore(true);
      try {
        const res = await api.listDeliveries({ endpoint_id: id, limit: 25, cursor: after });
        setDeliveries((prev) => (after ? [...(prev ?? []), ...res.data] : res.data));
        setDCursor(res.next_cursor);
      } catch (e) {
        setDErr(e);
      } finally {
        setDLoadingMore(false);
      }
    },
    [id],
  );

  useEffect(() => {
    void load();
    void loadDeliveries(null);
  }, [load, loadDeliveries]);

  async function toggleEnabled() {
    if (!endpoint) return;
    setToggling(true);
    setActionErr(null);
    try {
      setEndpoint(await api.updateEndpoint(endpoint.id, { enabled: !endpoint.enabled }));
    } catch (e) {
      setActionErr(e);
    } finally {
      setToggling(false);
    }
  }

  async function sendTest() {
    if (!endpoint) return;
    const eventType = endpoint.event_types.includes("*") ? "test.ping" : (endpoint.event_types[0] ?? "test.ping");
    setTestBusy(true);
    setTestErr(null);
    setTestResult(null);
    try {
      const res = await api.sendEvent(eventType, {
        message: "Test event from HookFlow dashboard",
        sent_at: new Date().toISOString(),
      });
      setTestResult(res);
      // Give the worker a moment, then refresh deliveries.
      setTimeout(() => void loadDeliveries(null), 1500);
    } catch (e) {
      setTestErr(e);
    } finally {
      setTestBusy(false);
    }
  }

  async function archive() {
    setActionErr(null);
    try {
      await api.archiveEndpoint(id);
      router.push("/endpoints");
    } catch (e) {
      setActionErr(e);
    }
  }

  if (loadErr) {
    const notFound = loadErr instanceof ApiError && loadErr.status === 404;
    return (
      <div className="page">
        <PageHeader title="Endpoint" />
        {notFound ? (
          <Empty title="Endpoint not found">
            It may have been archived. <Link href="/endpoints">Back to endpoints</Link>
          </Empty>
        ) : (
          <ErrorBox error={loadErr} onRetry={load} />
        )}
      </div>
    );
  }
  if (!endpoint) return <div className="page"><Loading /></div>;

  const testType = endpoint.event_types.includes("*") ? "test.ping" : (endpoint.event_types[0] ?? "test.ping");

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link href="/endpoints">Endpoints</Link> <span className="muted">/</span>
      </div>
      <PageHeader
        title={<span className="mono title-url">{endpoint.url}</span>}
        sub={
          <span className="row-wrap">
            {endpoint.enabled ? <span className="badge badge-green">Enabled</span> : <span className="badge badge-grey">Disabled</span>}
            <span className="mono muted small">{endpoint.id}</span>
          </span>
        }
        actions={
          <>
            <button type="button" className="btn" onClick={toggleEnabled} disabled={toggling}>
              {toggling ? "Saving…" : endpoint.enabled ? "Disable" : "Enable"}
            </button>
            {!editing && (
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                Edit
              </button>
            )}
          </>
        }
      />
      <ErrorBox error={actionErr} />

      {!endpoint.enabled && (
        <div className="alert alert-warning">This endpoint is disabled. It won&apos;t receive new deliveries until you enable it.</div>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Details</h2>
          <Link href={`/audit-log?resource_id=${endpoint.id}`} className="small">
            Audit log →
          </Link>
        </div>
        {editing ? (
          <EditForm
            endpoint={endpoint}
            onCancel={() => setEditing(false)}
            onSaved={(e) => {
              setEndpoint(e);
              setEditing(false);
            }}
          />
        ) : (
          <dl className="dl">
            <dt>URL</dt>
            <dd className="mono break">{endpoint.url}</dd>
            <dt>Description</dt>
            <dd>{endpoint.description || <span className="muted">—</span>}</dd>
            <dt>Event types</dt>
            <dd>
              <EventTypeList types={endpoint.event_types} />
            </dd>
            <dt>Max attempts</dt>
            <dd>
              {endpoint.max_attempts} <span className="muted small">per delivery, including the first</span>
            </dd>
            <dt>Created</dt>
            <dd>
              <Time iso={endpoint.created_at} />
            </dd>
            <dt>Updated</dt>
            <dd>
              <Time iso={endpoint.updated_at} />
            </dd>
          </dl>
        )}
      </section>

      <SecretSection
        endpoint={endpoint}
        onRotated={(exp) => setEndpoint((e) => (e ? { ...e, previous_secret_expires_at: exp } : e))}
      />

      <section className="card">
        <div className="card-head">
          <h2>Send a test event</h2>
        </div>
        <p className="muted small">
          Sends a <code className="mono">{testType}</code> event through the real pipeline. Every endpoint subscribed to{" "}
          <code className="mono">{testType}</code> will receive it.
        </p>
        <div className="row">
          <button type="button" className="btn btn-primary" onClick={sendTest} disabled={testBusy}>
            {testBusy ? "Sending…" : "Send test event"}
          </button>
          {testResult && (
            <span className="small">
              Accepted ·{" "}
              {testResult.delivery_count} deliver{testResult.delivery_count === 1 ? "y" : "ies"} created ·{" "}
              <Link href={`/events/${testResult.event_id}`} className="mono">
                View {testResult.event_id} →
              </Link>
            </span>
          )}
        </div>
        {testResult && testResult.delivery_count === 0 && (
          <div className="alert alert-warning mt">
            No deliveries were created{!endpoint.enabled ? " — this endpoint is disabled. Enable it and try again." : "."}
          </div>
        )}
        <ErrorBox error={testErr} />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Recent deliveries</h2>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => loadDeliveries(null)}>
            Refresh
          </button>
        </div>
        <ErrorBox error={dErr} onRetry={() => loadDeliveries(null)} />
        {!deliveries && !dErr && <Loading />}
        {deliveries && deliveries.length === 0 && (
          <Empty title="No deliveries yet">Send a test event above to see how your endpoint responds.</Empty>
        )}
        {deliveries && deliveries.length > 0 && <DeliveryTable deliveries={deliveries} show={["event"]} />}
        {dCursor && (
          <div className="load-more">
            <button type="button" className="btn" disabled={dLoadingMore} onClick={() => loadDeliveries(dCursor)}>
              {dLoadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </section>

      <section className="card card-danger">
        <div className="card-head">
          <h2>Archive endpoint</h2>
        </div>
        <p className="muted small">
          Archiving removes the endpoint from lists, stops new deliveries and cancels its unsent deliveries. Delivery history is kept.
        </p>
        <ConfirmButton
          label="Archive endpoint"
          prompt="Unsent deliveries will be cancelled."
          confirmLabel="Archive"
          onConfirm={archive}
        />
      </section>
    </div>
  );
}
