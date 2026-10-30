"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Delivery, type Endpoint, type EventAccepted } from "@/lib/api";
import { EventTypeList, EventTypesInput } from "@/components/EventTypesInput";
import { DeliveryTable } from "@/components/DeliveryTable";
import { ConfirmButton, CopyButton, Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

function EditForm({ endpoint, onSaved, onCancel }: { endpoint: Endpoint; onSaved: (e: Endpoint) => void; onCancel: () => void }) {
  const [url, setUrl] = useState(endpoint.url);
  const [description, setDescription] = useState(endpoint.description ?? "");
  const [types, setTypes] = useState<string[]>(endpoint.event_types);
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
    setBusy(true);
    setErr(null);
    try {
      const saved = await api.updateEndpoint(endpoint.id, {
        url: url.trim(),
        description: description.trim() || null,
        event_types: types,
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

function SecretSection({ endpointId }: { endpointId: string }) {
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [rotated, setRotated] = useState(false);

  async function reveal() {
    setBusy(true);
    setErr(null);
    try {
      setSecret((await api.getEndpointSecret(endpointId)).signing_secret);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  async function rotate() {
    setErr(null);
    try {
      setSecret((await api.rotateEndpointSecret(endpointId)).signing_secret);
      setRotated(true);
    } catch (e) {
      setErr(e);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Signing secret</h2>
      </div>
      <p className="muted small">
        Use this secret to verify the <code className="mono">HookFlow-Signature</code> header: HMAC-SHA256 of{" "}
        <code className="mono">{"{timestamp}.{raw body}"}</code>.
      </p>
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
            {busy ? "Revealing…" : "Reveal"}
          </button>
        )}
        <ConfirmButton
          small
          label="Rotate"
          prompt="The current secret stops working immediately."
          confirmLabel="Rotate secret"
          onConfirm={rotate}
        />
      </div>
      {rotated && (
        <div className="alert alert-warning mt">
          Secret rotated. Update your endpoint with the new secret now — signatures made with the old one will no longer match.
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

      <SecretSection endpointId={endpoint.id} />

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
