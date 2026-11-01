import type { EndpointHealth } from "@/lib/api";
import { formatLocal } from "@/lib/format";

const LABEL: Record<EndpointHealth["state"], string> = {
  idle: "No traffic",
  healthy: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
};

function percent(rate: number): string {
  const p = rate * 100;
  return `${p >= 99.95 || p === 0 ? p.toFixed(0) : p.toFixed(1)}%`;
}

/** Success rate and latest problem over the last 24 hours. */
export function HealthBadge({ health, detailed }: { health?: EndpointHealth; detailed?: boolean }) {
  if (!health) return <span className="muted">—</span>;
  const summary =
    health.state === "idle"
      ? "No delivery attempts in the last 24 hours."
      : `${health.successes} of ${health.attempts} attempts succeeded in the last 24 hours.`;
  const lastProblem = health.last_success === false ? health.last_error ?? `HTTP ${health.last_status_code}` : null;
  return (
    <div className="health" title={summary}>
      <span className={`health-state health-${health.state}`}>
        <span className="health-dot" aria-hidden />
        {LABEL[health.state]}
        {health.success_rate != null && <span className="health-rate">{percent(health.success_rate)}</span>}
      </span>
      {lastProblem && <div className="health-error small">{lastProblem}</div>}
      {detailed && (
        <div className="muted small">
          {summary}
          {health.last_attempt_at && <> Last attempt {formatLocal(health.last_attempt_at)}.</>}
        </div>
      )}
    </div>
  );
}
