"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, MAX_ATTEMPTS_DEFAULT, type EndpointWithHealth, type EndpointWithSecret } from "@/lib/api";
import { HealthBadge } from "@/components/EndpointHealth";
import { EventTypeList, EventTypesInput } from "@/components/EventTypesInput";
import { MaxAttemptsInput, maxAttemptsError } from "@/components/MaxAttemptsInput";
import { useMe } from "@/components/MeContext";
import {
  RetryScheduleInput,
  scheduleDraftError,
  scheduleDraftValue,
  type ScheduleDraft,
} from "@/components/RetryScheduleInput";
import { Empty, ErrorBox, Loading, PageHeader, SecretBox, Time } from "@/components/ui";

function CreateForm({ onCreated, onCancel }: { onCreated: (e: EndpointWithSecret) => void; onCancel: () => void }) {
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [types, setTypes] = useState<string[]>(["*"]);
  const [maxAttempts, setMaxAttempts] = useState(String(MAX_ATTEMPTS_DEFAULT));
  const [schedule, setSchedule] = useState<ScheduleDraft>({ custom: false, text: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [localErr, setLocalErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setLocalErr(null);
    let parsed: URL;
    try {
      parsed = new URL(url.trim());
    } catch {
      setLocalErr("Enter a full URL, e.g. https://example.com/webhooks.");
      return;
    }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      setLocalErr("The URL must start with https://.");
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
    setBusy(true);
    setErr(null);
    try {
      const created = await api.createEndpoint({
        url: url.trim(),
        description: description.trim() || undefined,
        event_types: types,
        max_attempts: Number(maxAttempts),
        retry_schedule: scheduleDraftValue(schedule),
      });
      onCreated(created);
    } catch (e2) {
      setErr(e2);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <label className="field">
        <span className="field-label">URL</span>
        <input
          className="input mono"
          type="url"
          placeholder="https://example.com/webhooks"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">
          Description <span className="muted">(optional)</span>
        </span>
        <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Orders service" />
      </label>
      <EventTypesInput value={types} onChange={setTypes} />
      <MaxAttemptsInput value={maxAttempts} onChange={setMaxAttempts} />
      <RetryScheduleInput value={schedule} onChange={setSchedule} maxAttempts={Number(maxAttempts)} />
      {localErr && <div className="alert alert-error">{localErr}</div>}
      <ErrorBox error={err} />
      <div className="row">
        <button type="submit" className="btn btn-primary" disabled={busy || !url.trim()}>
          {busy ? "Adding…" : "Add endpoint"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function EndpointsPage() {
  const router = useRouter();
  const [items, setItems] = useState<EndpointWithHealth[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [created, setCreated] = useState<EndpointWithSecret | null>(null);
  const { can } = useMe();
  const canWrite = can("endpoints:write");

  const load = useCallback(async (after: string | null) => {
    setLoadErr(null);
    if (after) setLoadingMore(true);
    try {
      const res = await api.listEndpoints({ limit: 50, cursor: after });
      setItems((prev) => (after ? [...(prev ?? []), ...res.data] : res.data));
      setCursor(res.next_cursor);
    } catch (e) {
      setLoadErr(e);
    } finally {
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  return (
    <div className="page">
      <PageHeader
        title="Endpoints"
        sub="HTTPS URLs that receive your events, signed with a per-endpoint secret."
        actions={
          canWrite &&
          !showForm &&
          !created && (
            <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
              + Add endpoint
            </button>
          )
        }
      />

      {created && (
        <section className="card">
          <div className="card-head">
            <h2>Endpoint added</h2>
          </div>
          <p className="mono small">{created.url}</p>
          <SecretBox
            title="Signing secret"
            value={created.signing_secret}
            warning="Save this secret in your endpoint's configuration and use it to verify the HookFlow-Signature header. You can reveal it again from the endpoint page."
          />
          <div className="row mt">
            <button type="button" className="btn btn-primary" onClick={() => router.push(`/endpoints/${created.id}`)}>
              Continue to endpoint →
            </button>
          </div>
        </section>
      )}

      {showForm && !created && (
        <section className="card">
          <div className="card-head">
            <h2>Add endpoint</h2>
          </div>
          <CreateForm
            onCancel={() => setShowForm(false)}
            onCreated={(e) => {
              setCreated(e);
              setShowForm(false);
              const { signing_secret: _secret, ...endpoint } = e;
              const idle = {
                state: "idle", attempts: 0, successes: 0, success_rate: null, last_attempt_at: null,
                last_success: null, last_status_code: null, last_error: null,
              } as const;
              setItems((prev) => [{ ...endpoint, health: idle }, ...(prev ?? [])]);
            }}
          />
        </section>
      )}

      <section className="card">
        <ErrorBox error={loadErr} onRetry={() => load(null)} />
        {!items && !loadErr && <Loading />}
        {items && items.length === 0 && (
          <Empty title="No endpoints yet">
            {canWrite ? "Add the URL where you want to receive webhooks." : "Nobody has added an endpoint yet."}{" "}
            {canWrite && !showForm && (
              <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowForm(true)}>
                Add endpoint
              </button>
            )}
          </Empty>
        )}
        {items && items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Event types</th>
                  <th>Health (24h)</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id} className="row-click" onClick={() => router.push(`/endpoints/${e.id}`)}>
                    <td className="url-cell">
                      <Link href={`/endpoints/${e.id}`} className="mono" onClick={(ev) => ev.stopPropagation()}>
                        {e.url}
                      </Link>
                      {e.description && <div className="muted small">{e.description}</div>}
                    </td>
                    <td>
                      <EventTypeList types={e.event_types} />
                    </td>
                    <td className="health-cell">
                      <HealthBadge health={e.health} />
                    </td>
                    <td>
                      {e.enabled ? <span className="badge badge-green">Enabled</span> : <span className="badge badge-grey">Disabled</span>}
                    </td>
                    <td>
                      <Time iso={e.created_at} />
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
