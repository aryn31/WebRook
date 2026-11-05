"use client";

import { AuditIcon } from "@/components/AuditIcon";
import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api, AUDIT_ACTIONS, type AuditLog } from "@/lib/api";
import { auditLabel, auditSummary, shortId } from "@/lib/format";
import { Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

function Actor({ log }: { log: AuditLog }) {
  const who = log.actor.email ? <div className="muted small">{log.actor.email}</div> : null;
  if (log.actor.type === "api_key") {
    return (
      <span>
        API key{" "}
        {log.actor.api_key_id ? (
          <Link href="/api-keys" className="actor-key" title={log.actor.api_key_id}>
            {shortId(log.actor.api_key_id, 16)}
          </Link>
        ) : null}
        {who}
      </span>
    );
  }
  return (
    <span>
      Dashboard
      {who}
    </span>
  );
}

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

/** Link to the most useful page for the entry's resource. */
function Resource({ log }: { log: AuditLog }) {
  const id = log.resource_id;
  const type = log.resource_type;
  if (!id) return <span className="muted">—</span>;
  const label = <span className="mono small" title={id}>{shortId(id, 18)}</span>;
  switch (type) {
    case "endpoint":
      return (
        <span>
          <span className="muted small">Endpoint </span>
          {log.action === "endpoint.archived" ? label : <Link href={`/endpoints/${id}`}>{label}</Link>}
        </span>
      );
    case "event":
      return (
        <span>
          <span className="muted small">Event </span>
          <Link href={`/events/${id}`}>{label}</Link>
        </span>
      );
    case "delivery": {
      const eventId = str(log.details?.event_id);
      return (
        <span>
          <span className="muted small">Delivery </span>
          {label}
          {eventId && (
            <div className="tiny">
              <Link href={`/events/${eventId}`}>View event →</Link>
            </div>
          )}
        </span>
      );
    }
    case "api_key":
      return (
        <span>
          <span className="muted small">API key </span>
          <Link href="/api-keys">{label}</Link>
        </span>
      );
    default:
      return (
        <span>
          {type && <span className="muted small">{type.replace(/_/g, " ")} </span>}
          {label}
        </span>
      );
  }
}

function AuditLogView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const action = params.get("action") ?? "";
  const resourceId = params.get("resource_id") ?? "";

  const [items, setItems] = useState<AuditLog[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(
    async (after: string | null) => {
      setErr(null);
      if (after) setLoadingMore(true);
      else setItems(null);
      try {
        const res = await api.listAuditLogs({
          limit: 50,
          cursor: after,
          action: action || undefined,
          resource_id: resourceId || undefined,
        });
        setItems((prev) => (after ? [...(prev ?? []), ...res.data] : res.data));
        setCursor(res.next_cursor);
      } catch (e) {
        setErr(e);
      } finally {
        setLoadingMore(false);
      }
    },
    [action, resourceId],
  );

  useEffect(() => {
    void load(null);
  }, [load]);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const filtered = !!(action || resourceId);

  return (
    <div className="page">
      <PageHeader
        title="Audit log"
        sub="Security-relevant actions on your account: sign-ins, API keys, endpoint changes, secret access and replays."
      />

      <section className="card card-flush">
        <div className="filter-bar">
          <label className="field">
            <span className="field-label">Action</span>
            <select className="input select" value={action} onChange={(e) => setParam("action", e.target.value)}>
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {auditLabel(a)}
                </option>
              ))}
            </select>
          </label>
          {resourceId && (
            <span className="chip">
              Resource <span className="mono">{shortId(resourceId, 20)}</span>
              <button type="button" aria-label="Clear resource filter" onClick={() => setParam("resource_id", "")}>
                ×
              </button>
            </span>
          )}
          {filtered && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => router.replace(pathname, { scroll: false })}>
              Clear filters
            </button>
          )}
        </div>

        <ErrorBox error={err} onRetry={() => load(null)} />
        {!items && !err && <Loading />}
        {items && items.length === 0 && (
          <Empty title={filtered ? "No matching entries" : "No audit entries yet"}>
            {filtered ? "Try a different action or clear the filters." : "Actions like creating endpoints or rotating secrets will appear here."}
          </Empty>
        )}
        {items && items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Actor</th>
                  <th>Resource</th>
                  <th>Details</th>
                  <th>IP</th>
                </tr>
              </thead>
              <tbody>
                {items.map((log) => {
                  const summary = auditSummary(log);
                  return (
                    <tr key={log.id}>
                      <td className="nowrap-cell">
                        <Time iso={log.created_at} />
                      </td>
                      <td>
                        <div className="person">
                          <AuditIcon action={log.action} />
                          <div>
                            <span title={log.action}>{auditLabel(log.action)}</span>
                            <div className="mono muted tiny">{log.action}</div>
                          </div>
                        </div>
                      </td>
                      <td className="nowrap-cell">
                        <Actor log={log} />
                      </td>
                      <td>
                        <Resource log={log} />
                      </td>
                      <td>
                        {summary.length > 0 ? (
                          <ul className="audit-details">
                            {summary.map((line, i) => (
                              <li key={i}>{line}</li>
                            ))}
                          </ul>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="mono small nowrap-cell">{log.ip_address ?? <span className="muted">—</span>}</td>
                    </tr>
                  );
                })}
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

export default function AuditLogPage() {
  return (
    <Suspense fallback={<div className="page"><Loading /></div>}>
      <AuditLogView />
    </Suspense>
  );
}
