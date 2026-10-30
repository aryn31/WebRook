"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Delivery, type Stats, type StatsRange } from "@/lib/api";
import { formatNumber, INSPECTED_KEY } from "@/lib/format";
import { SeriesChart } from "@/components/SeriesChart";
import { DeliveryExplanation } from "@/components/DeliveryTable";
import { Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

const RANGES: { value: StatsRange; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
];

type Onboarding = { apiKey: boolean; endpoint: boolean; event: boolean; inspected: boolean };

function Checklist({ state }: { state: Onboarding }) {
  const steps = [
    { done: state.apiKey, title: "Create an API key", body: "Your application uses it to send events.", href: "/api-keys", cta: "Create key" },
    { done: state.endpoint, title: "Add an endpoint", body: "The HTTPS URL HookFlow delivers events to.", href: "/endpoints", cta: "Add endpoint" },
    { done: state.event, title: "Send a test event", body: "From an endpoint's page, or with curl and your API key.", href: "/events", cta: "Send event" },
    { done: state.inspected, title: "Inspect the result", body: "Open an event to see each delivery and its attempts.", href: "/events", cta: "View events" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  if (doneCount === steps.length) return null;
  const nextIdx = steps.findIndex((s) => !s.done);
  return (
    <section className="card onboarding">
      <div className="card-head">
        <h2>Get started</h2>
        <span className="muted small">
          {doneCount} of {steps.length} done
        </span>
      </div>
      <ol className="checklist">
        {steps.map((s, i) => (
          <li key={s.title} className={`check-item${s.done ? " done" : ""}${i === nextIdx ? " next" : ""}`}>
            <span className="check-mark" aria-hidden>{s.done ? "✓" : i + 1}</span>
            <div className="check-text">
              <div className="check-title">{s.title}</div>
              <div className="muted small">{s.body}</div>
            </div>
            {!s.done && (
              <Link href={s.href} className={`btn btn-sm${i === nextIdx ? " btn-primary" : ""}`}>
                {s.cta}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function OverviewPage() {
  const [range, setRange] = useState<StatsRange>("7d");
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsErr, setStatsErr] = useState<unknown>(null);
  const [failed, setFailed] = useState<Delivery[] | null>(null);
  const [failedErr, setFailedErr] = useState<unknown>(null);
  const [onboarding, setOnboarding] = useState<Onboarding | null>(null);

  const loadStats = useCallback(async (r: StatsRange) => {
    setStatsErr(null);
    try {
      setStats(await api.stats(r));
    } catch (e) {
      setStatsErr(e);
    }
  }, []);

  const loadFailed = useCallback(async () => {
    setFailedErr(null);
    try {
      setFailed((await api.listDeliveries({ status: "failed", limit: 5 })).data);
    } catch (e) {
      setFailedErr(e);
    }
  }, []);

  useEffect(() => {
    void loadStats(range);
  }, [range, loadStats]);

  useEffect(() => {
    void loadFailed();
    (async () => {
      try {
        const [keys, eps, evs] = await Promise.all([
          api.listApiKeys(),
          api.listEndpoints({ limit: 1 }),
          api.listEvents({ limit: 1 }),
        ]);
        let inspected = false;
        try {
          inspected = window.localStorage.getItem(INSPECTED_KEY) === "1";
        } catch {
          /* storage unavailable */
        }
        setOnboarding({
          apiKey: keys.data.some((k) => !k.revoked_at),
          endpoint: eps.data.length > 0,
          event: evs.data.length > 0,
          inspected: inspected && evs.data.length > 0,
        });
      } catch {
        // The checklist is optional; hide it on errors.
      }
    })();
  }, [loadFailed]);

  const s = stats?.deliveries_by_status;
  const tiles: { label: string; value: number | undefined; cls?: string; href?: string }[] = [
    { label: "Events", value: stats?.events_total, href: "/events" },
    { label: "Deliveries", value: stats?.deliveries_total, href: "/deliveries" },
    { label: "Delivered", value: s?.delivered, cls: "delivered", href: "/deliveries?status=delivered" },
    { label: "Retrying", value: s?.retrying, cls: "retrying", href: "/deliveries?status=retrying" },
    { label: "Failed", value: s?.failed, cls: "failed", href: "/deliveries?status=failed" },
    { label: "Pending", value: s ? s.pending + s.processing : undefined, cls: "pending", href: "/deliveries?status=pending" },
  ];
  const successRate =
    s && s.delivered + s.failed > 0 ? Math.round((s.delivered / (s.delivered + s.failed)) * 1000) / 10 : null;

  return (
    <div className="page">
      <PageHeader
        title="Overview"
        sub={successRate != null ? `${successRate}% of finished deliveries succeeded in this range` : "Activity across all your endpoints"}
        actions={
          <div className="segmented" role="tablist" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r.value}
                type="button"
                role="tab"
                aria-selected={range === r.value}
                className={range === r.value ? "active" : ""}
                onClick={() => setRange(r.value)}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      />

      {onboarding && <Checklist state={onboarding} />}

      <ErrorBox error={statsErr} onRetry={() => loadStats(range)} />

      <div className="tiles">
        {tiles.map((t) => (
          <Link key={t.label} href={t.href ?? "#"} className={`tile${t.cls ? ` tile-${t.cls}` : ""}`}>
            <div className="tile-label">
              {t.cls && <span className={`pill-dot dot-${t.cls}`} aria-hidden />} {t.label}
            </div>
            <div className="tile-value">{t.value == null ? (statsErr ? "—" : "…") : formatNumber(t.value)}</div>
          </Link>
        ))}
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Activity</h2>
          <span className="muted small">{range === "24h" ? "Hourly" : "Daily"}, local time</span>
        </div>
        {stats ? <SeriesChart series={stats.series} range={stats.range} /> : !statsErr && <Loading />}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Recent failed deliveries</h2>
          <Link href="/deliveries?status=failed" className="small">
            View all →
          </Link>
        </div>
        <ErrorBox error={failedErr} onRetry={loadFailed} />
        {!failed && !failedErr && <Loading />}
        {failed && failed.length === 0 && (
          <Empty title="No failed deliveries">Everything that finished was delivered. Nice.</Empty>
        )}
        {failed && failed.length > 0 && (
          <ul className="list">
            {failed.map((d) => (
              <li key={d.id} className="list-item">
                <div className="list-main">
                  <div className="list-title">
                    <Link href={`/events/${d.event_id}`} className="mono">
                      {d.event_type}
                    </Link>
                    <span className="muted"> → </span>
                    <Link href={`/endpoints/${d.endpoint_id}`} className="mono url-inline" title={d.endpoint_url}>
                      {d.endpoint_url}
                    </Link>
                  </div>
                  <DeliveryExplanation delivery={d} compact />
                </div>
                <div className="list-side small">
                  <Time iso={d.updated_at} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
