"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Delivery, type Endpoint, type EndpointHealth, type EventAccepted } from "@/lib/api";
import { Ring } from "@/components/Ring";
import { EventTypeList, EventTypesInput } from "@/components/EventTypesInput";
import { DeliveryTable } from "@/components/DeliveryTable";
import { MaxAttemptsInput, maxAttemptsError } from "@/components/MaxAttemptsInput";
import { BulkReplay } from "@/components/BulkReplay";
import { useMe } from "@/components/MeContext";
import {
  describeSchedule,
  RetryScheduleInput,
  scheduleDraftError,
  scheduleDraftValue,
  scheduleToText,
  type ScheduleDraft,
} from "@/components/RetryScheduleInput";
import { ConfirmButton, CopyButton, Empty, ErrorBox, Loading, PageHeader, SecretBox, Time } from "@/components/ui";
import { formatClock, formatSeconds, formatUtc, GRACE_DEFAULT, GRACE_OPTIONS, isFuture, relative } from "@/lib/format";

function EditForm({ endpoint, onSaved, onCancel }: { endpoint: Endpoint; onSaved: (e: Endpoint) => void; onCancel: () => void }) {
  const [url, setUrl] = useState(endpoint.url);
  const [description, setDescription] = useState(endpoint.description ?? "");
  const [types, setTypes] = useState<string[]>(endpoint.event_types);
  const [maxAttempts, setMaxAttempts] = useState(String(endpoint.max_attempts));
  const [schedule, setSchedule] = useState<ScheduleDraft>({
    custom: endpoint.retry_schedule !== null,
    text: scheduleToText(endpoint.retry_schedule),
  });
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
    const schedErr = scheduleDraftError(schedule);
    if (schedErr) {
      setLocalErr(schedErr);
      return;
    }
    const newSchedule = scheduleDraftValue(schedule);
    const scheduleChanged = JSON.stringify(newSchedule) !== JSON.stringify(endpoint.retry_schedule);
    setBusy(true);
    setErr(null);
    try {
      const saved = await api.updateEndpoint(endpoint.id, {
        ...(scheduleChanged ? { retry_schedule: newSchedule } : {}),
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
      <RetryScheduleInput value={schedule} onChange={setSchedule} maxAttempts={Number(maxAttempts)} />
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

const HEALTH_COPY: Record<EndpointHealth["state"], { tone: string; title: string; body: string }> = {
  healthy: { tone: "ok", title: "Healthy", body: "It's accepting what HookFlow sends." },
  degraded: { tone: "retrying", title: "Some attempts are failing", body: "Most requests get through, but not all. Retries are covering the gaps." },
  failing: { tone: "failed", title: "Failing", body: "Recent attempts were rejected. Fix the endpoint, then replay what failed below." },
  idle: { tone: "idle", title: "No traffic yet", body: "No delivery attempts in the last 24 hours. Send a test event to check it." },
};

function HealthCard({ health, alertSentAt }: { health: EndpointHealth; alertSentAt: string | null }) {
  const c = HEALTH_COPY[health.state];
  const pct = health.success_rate == null ? null : Math.round(health.success_rate * 1000) / 10;
  const failed = health.attempts - health.successes;
  return (
    <section className={`card hero-card hero-${c.tone} ep-hero`}>
      <Ring pct={pct} />
      <div className="hero-main">
        <div className="hero-verdict"><span className="hero-verdict-dot" aria-hidden />{c.title}</div>
        <p className="hero-body">{c.body}</p>
        {alertSentAt && (
          <p className="ep-hero-alerted">
            <span aria-hidden>✉</span> Owners and admins were emailed {relative(alertSentAt)}. They&apos;ll get one more
            email when it&apos;s working again.
          </p>
        )}
        {health.last_success === false && (
          <div className="ep-hero-error">
            <span className="mono">{health.last_status_code ?? "ERR"}</span>
            {health.last_error ?? `Destination returned HTTP ${health.last_status_code}.`}
          </div>
        )}
        <div className="hero-counts">
          <div className="hero-count"><span className="hero-count-label">Attempts (24h)</span><span className="hero-count-value">{health.attempts}</span></div>
          <div className="hero-count count-delivered"><span className="hero-count-label"><span className="pill-dot dot-delivered" aria-hidden /> Succeeded</span><span className="hero-count-value">{health.successes}</span></div>
          <div className="hero-count count-failed"><span className="hero-count-label"><span className="pill-dot dot-failed" aria-hidden /> Failed</span><span className="hero-count-value">{failed}</span></div>
          <div className="hero-count"><span className="hero-count-label">Last attempt</span><span className="hero-count-value hero-count-time">{health.last_attempt_at ? relative(health.last_attempt_at) : "—"}</span></div>
        </div>
      </div>
    </section>
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

/** An event type this endpoint receives, for the test button. "order.*" becomes "order.test". */
function testEventType(types: string[]): string {
  const first = types.includes("*") ? undefined : types[0];
  if (!first) return "test.ping";
  return first.endsWith(".*") ? `${first.slice(0, -2)}.test` : first;
}

export default function EndpointDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();

  const [endpoint, setEndpoint] = useState<Endpoint | null>(null);
  const [health, setHealth] = useState<EndpointHealth | undefined>(undefined);
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
  const { can } = useMe();
  const canWrite = can("endpoints:write");

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const { health: h, ...e } = await api.getEndpoint(id);
      setEndpoint(e);
      setHealth(h);
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
    const eventType = testEventType(endpoint.event_types);
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

  const testType = testEventType(endpoint.event_types);

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link href="/endpoints">Endpoints</Link> <span className="muted">/</span>
      </div>
      <PageHeader
        title={endpoint.description || new URL(endpoint.url).host}
        sub={
          <span className="row-wrap">
            {endpoint.enabled ? <span className="badge badge-green">Enabled</span> : <span className="badge badge-grey">Disabled</span>}
            <span className="mono detail-url">{endpoint.url}</span>
            <CopyButton text={endpoint.url} label="Copy URL" />
          </span>
        }
        actions={
          canWrite && (
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
          )
        }
      />
      <ErrorBox error={actionErr} />

      {!endpoint.enabled && (
        <div className="alert alert-warning">This endpoint is disabled. It won&apos;t receive new deliveries until you enable it.</div>
      )}

      {health && !editing && <HealthCard health={health} alertSentAt={endpoint.alert_sent_at} />}

      <section className="card">
        <div className="card-head">
          <h2>Settings</h2>
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
            <dt>ID</dt>
            <dd className="mono small">{endpoint.id}</dd>
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
            <dt>Retry timing</dt>
            <dd>
              {endpoint.retry_schedule ? (
                <>
                  <span className="mono">{scheduleToText(endpoint.retry_schedule)}</span>{" "}
                  <span className="muted small">{describeSchedule(endpoint.retry_schedule, endpoint.max_attempts)}</span>
                </>
              ) : (
                <span className="muted">Default backoff (about 30s, 2m, 8m, 32m, up to 6h)</span>
              )}
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

      <div className="detail-grid">
      {canWrite && (
        <SecretSection
          endpoint={endpoint}
          onRotated={(exp) => setEndpoint((e) => (e ? { ...e, previous_secret_expires_at: exp } : e))}
        />
      )}

      {can("events:write") && (
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
      )}
      </div>

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
        {deliveries && deliveries.some((d) => d.status === "failed") && endpoint.enabled && (
          <div className="mt">
            <BulkReplay
              filters={{ endpoint_id: endpoint.id }}
              label="Replay all failed deliveries to this endpoint"
              onDone={() => setTimeout(() => void loadDeliveries(null), 800)}
            />
          </div>
        )}
        {dCursor && (
          <div className="load-more">
            <button type="button" className="btn" disabled={dLoadingMore} onClick={() => loadDeliveries(dCursor)}>
              {dLoadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </section>

      {canWrite && (
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
      )}
    </div>
  );
}
