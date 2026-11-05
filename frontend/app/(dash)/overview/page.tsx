"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Delivery, type EndpointWithHealth, type Stats, type StatsRange, type Usage, type UsageWindow } from "@/lib/api";
import { formatCountdown, formatDuration, formatNumber, INSPECTED_KEY, ONBOARDING_DISMISSED_KEY } from "@/lib/format";
import { SeriesChart } from "@/components/SeriesChart";
import { DeliveryExplanation } from "@/components/DeliveryTable";
import { Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";
import { useMe } from "@/components/MeContext";

const RANGES: { value: StatsRange; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
];

type Onboarding = { apiKey: boolean; endpoint: boolean; event: boolean; inspected: boolean; delivered: boolean };

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false; // storage unavailable
  }
}

function Checklist({ state, onDismiss }: { state: Onboarding; onDismiss: () => void }) {
  const steps = [
    { done: state.apiKey, title: "Create an API key", body: "Your application uses it to send events.", href: "/api-keys", cta: "Create key" },
    { done: state.endpoint, title: "Add an endpoint", body: "The HTTPS URL HookFlow delivers events to.", href: "/endpoints", cta: "Add endpoint" },
    { done: state.event, title: "Send a test event", body: "From an endpoint's page, or with curl and your API key.", href: "/events", cta: "Send event" },
    { done: state.inspected, title: "Inspect the result", body: "Open an event to see each delivery and its attempts.", href: "/events", cta: "View events" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  // Once an event has been delivered the account is clearly set up; stop taking up the top of the page.
  if (doneCount === steps.length || (state.event && state.delivered)) return null;
  const nextIdx = steps.findIndex((s) => !s.done);
  return (
    <section className="card onboarding">
      <div className="card-head">
        <h2>Get started</h2>
        <span className="row">
          <span className="muted small">
            {doneCount} of {steps.length} done
          </span>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onDismiss}>
            Dismiss
          </button>
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

function Meter({ window: w, unit, label }: { window: UsageWindow; unit: string; label: string }) {
  if (w.limit == null) {
    return (
      <div className="meter-block">
        <div className="meter-head">
          <span className="meter-label">{label}</span>
          <span className="muted small">
            {formatNumber(w.used)} {unit} · no limit
          </span>
        </div>
      </div>
    );
  }
  const pct = Math.min((w.used / w.limit) * 100, 100);
  const tone = pct >= 100 ? "failed" : pct >= 80 ? "retrying" : "ok";
  return (
    <div className="meter-block">
      <div className="meter-head">
        <span className="meter-label">{label}</span>
        <span className="small">
          <strong>{formatNumber(w.used)}</strong> <span className="muted">of {formatNumber(w.limit)} {unit}</span>
        </span>
      </div>
      <div
        className={`meter meter-${tone}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={w.limit}
        aria-valuenow={w.used}
        aria-label={label}
      >
        <div className="meter-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="muted tiny">
        {pct >= 100
          ? `Limit reached — new events are rejected for ${formatCountdown(w.resets_in_seconds)}.`
          : `Resets in ${formatCountdown(w.resets_in_seconds)}`}
      </div>
    </div>
  );
}

function UsageCard({ usage }: { usage: Usage }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>Usage</h2>
        <span className="muted small">Limits apply to POST /v1/events</span>
      </div>
      <div className="meters">
        <Meter window={usage.events_today} unit="events" label="Today (UTC)" />
        <Meter window={usage.requests_this_minute} unit="requests" label="This minute" />
      </div>
    </section>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Success rate as a ring that fills in. */
function Ring({ pct, tone }: { pct: number | null; tone: string }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = window.requestAnimationFrame(() => setShown(pct ?? 0));
    return () => window.cancelAnimationFrame(id);
  }, [pct]);
  return (
    <div className={`ring ring-${tone}`}>
      <svg viewBox="0 0 120 120" aria-hidden>
        <circle cx="60" cy="60" r={r} className="ring-track" />
        <circle cx="60" cy="60" r={r} className="ring-value" strokeDasharray={c}
          strokeDashoffset={c * (1 - shown / 100)} transform="rotate(-90 60 60)" />
      </svg>
      <div className="ring-label">
        <span className="ring-num">{pct == null ? "—" : `${pct}%`}</span>
        <span className="ring-sub">success</span>
      </div>
    </div>
  );
}

function verdict(rate: number | null, failed: number, retrying: number): { tone: string; title: string; body: string } {
  if (rate == null) {
    return retrying > 0
      ? { tone: "retrying", title: "Deliveries in progress", body: "Nothing has finished yet in this range." }
      : { tone: "idle", title: "Quiet so far", body: "No deliveries in this range yet. Send an event to see it here." };
  }
  if (rate >= 99) return { tone: "ok", title: "Everything's arriving", body: "Your endpoints are accepting what you send." };
  if (rate >= 90) return { tone: "ok", title: "Mostly smooth", body: `${formatNumber(failed)} failed deliver${failed === 1 ? "y" : "ies"} worth a look.` };
  if (rate >= 60) return { tone: "retrying", title: "Some endpoints are struggling", body: "Check the failing endpoints below, then replay what failed." };
  return { tone: "failed", title: "Most deliveries are failing", body: "At least one endpoint is rejecting requests. Start with the list below." };
}

const HEALTH_LABEL: Record<EndpointWithHealth["health"]["state"], string> = {
  healthy: "Healthy", degraded: "Degraded", failing: "Failing", idle: "No traffic",
};

function EndpointsHealth({ endpoints }: { endpoints: EndpointWithHealth[] }) {
  const order = { failing: 0, degraded: 1, healthy: 2, idle: 3 };
  const list = [...endpoints].filter((e) => e.enabled).sort((a, b) => order[a.health.state] - order[b.health.state]).slice(0, 6);
  return (
    <section className="card">
      <div className="card-head">
        <h2>Endpoint health</h2>
        <Link href="/endpoints" className="small">All endpoints →</Link>
      </div>
      {list.length === 0 ? (
        <Empty title="No endpoints yet">
          <Link href="/endpoints" className="btn btn-sm btn-primary">Add your first endpoint</Link>
        </Empty>
      ) : (
        <ul className="eph">
          {list.map((e) => {
            const pct = e.health.success_rate == null ? null : Math.round(e.health.success_rate * 100);
            return (
              <li key={e.id}>
                <Link href={`/endpoints/${e.id}`} className={`eph-row eph-${e.health.state}`}>
                  <span className="eph-dot" aria-hidden />
                  <span className="eph-main">
                    <span className="eph-name">{e.description || e.url}</span>
                    <span className="eph-url mono">{e.url}</span>
                  </span>
                  <span className="eph-bar" aria-hidden><span style={{ width: `${pct ?? 0}%` }} /></span>
                  <span className="eph-pct">{pct == null ? "—" : `${pct}%`}</span>
                  <span className="eph-state">{HEALTH_LABEL[e.health.state]}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default function OverviewPage() {
  const { me } = useMe();
  const [endpoints, setEndpoints] = useState<EndpointWithHealth[] | null>(null);
  const [hello, setHello] = useState("Welcome back");
  useEffect(() => setHello(greeting()), []);
  const [range, setRange] = useState<StatsRange>("24h");
  const [usage, setUsage] = useState<Usage | null>(null);
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
    api.listEndpoints({ limit: 50 }).then((r) => setEndpoints(r.data)).catch(() => {
      /* optional card; hidden on errors */
    });
    api.usage().then(setUsage).catch(() => {
      /* optional card; hidden on errors */
    });
    (async () => {
      if (readFlag(ONBOARDING_DISMISSED_KEY)) return;
      try {
        const [keys, eps, evs, delivered] = await Promise.all([
          api.listApiKeys(),
          api.listEndpoints({ limit: 1 }),
          api.listEvents({ limit: 1 }),
          api.listDeliveries({ status: "delivered", limit: 1 }),
        ]);
        setOnboarding({
          apiKey: keys.data.some((k) => !k.revoked_at),
          endpoint: eps.data.length > 0,
          event: evs.data.length > 0,
          inspected: readFlag(INSPECTED_KEY) && evs.data.length > 0,
          delivered: delivered.data.length > 0,
        });
      } catch {
        // The checklist is optional; hide it on errors.
      }
    })();
  }, [loadFailed]);

  function dismissOnboarding() {
    try {
      window.localStorage.setItem(ONBOARDING_DISMISSED_KEY, "1");
    } catch {
      /* storage unavailable: hide for this visit only */
    }
    setOnboarding(null);
  }

  const s = stats?.deliveries_by_status;
  const successRate =
    s && s.delivered + s.failed > 0 ? Math.round((s.delivered / (s.delivered + s.failed)) * 1000) / 10 : null;
  const pending = s ? s.pending + s.processing : 0;
  const total = s ? s.delivered + s.retrying + s.failed + pending : 0;
  const v = verdict(successRate, s?.failed ?? 0, s?.retrying ?? 0);
  const num = (n: number | undefined) => (n == null ? (statsErr ? "—" : "…") : formatNumber(n));
  const counts: { label: string; value: string; cls: string; href: string; n: number }[] = [
    { label: "Delivered", value: num(s?.delivered), cls: "delivered", href: "/deliveries?status=delivered", n: s?.delivered ?? 0 },
    { label: "Retrying", value: num(s?.retrying), cls: "retrying", href: "/deliveries?status=retrying", n: s?.retrying ?? 0 },
    { label: "Failed", value: num(s?.failed), cls: "failed", href: "/deliveries?status=failed", n: s?.failed ?? 0 },
    { label: "Pending", value: num(s ? pending : undefined), cls: "pending", href: "/deliveries?status=pending", n: pending },
  ];
  const name = me?.user.email.split("@")[0];

  return (
    <div className="page">
      <PageHeader
        title={<>{hello}{name ? <>, <em className="greet-name">{name}</em></> : null}</>}
        sub="Here's how your webhooks are doing."
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

      {onboarding && <Checklist state={onboarding} onDismiss={dismissOnboarding} />}

      <ErrorBox error={statsErr} onRetry={() => loadStats(range)} />

      <section className={`card hero-card hero-${v.tone}`}>
        <Ring pct={stats ? successRate : null} tone={v.tone} />
        <div className="hero-main">
          <div className="hero-verdict">
            <span className="hero-verdict-dot" aria-hidden />
            {stats ? v.title : statsErr ? "Couldn't load activity" : "Loading activity…"}
          </div>
          <p className="hero-body">{stats ? v.body : "\u00a0"}</p>
          <div className="hero-split" aria-hidden>
            {total > 0 && counts.map((c) => c.n > 0 && (
              <span key={c.cls} className={`split-${c.cls}`} style={{ flexGrow: c.n }} />
            ))}
          </div>
          <div className="hero-counts">
            {counts.map((c) => (
              <Link key={c.cls} href={c.href} className={`hero-count count-${c.cls}`}>
                <span className="hero-count-label"><span className={`pill-dot dot-${c.cls}`} aria-hidden /> {c.label}</span>
                <span className="hero-count-value">{c.value}</span>
              </Link>
            ))}
          </div>
        </div>
        <div className="hero-side">
          <Link href="/events" className="hero-stat">
            <span className="hero-stat-label">Events</span>
            <span className="hero-stat-value">{num(stats?.events_total)}</span>
          </Link>
          <div className="hero-stat"
            title={stats?.latency_ms ? `95% of attempts got a response within this time. Median: ${formatDuration(stats.latency_ms.p50)}.` : "No delivery attempts in this range."}>
            <span className="hero-stat-label">p95 response</span>
            <span className="hero-stat-value">{!stats ? num(undefined) : stats.latency_ms ? formatDuration(stats.latency_ms.p95) : "—"}</span>
          </div>
        </div>
      </section>

      <div className="overview-grid">
        {endpoints && <EndpointsHealth endpoints={endpoints} />}
        {usage && <UsageCard usage={usage} />}
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
          <Empty good title="No failed deliveries">Everything that finished was delivered. Nice.</Empty>
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
