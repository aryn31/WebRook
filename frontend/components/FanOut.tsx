import Link from "next/link";
import type { Delivery } from "@/lib/api";
import { STATUS_LABEL } from "@/lib/format";

/** Where one event went: the event on the left, a line to each endpoint, and how each delivery is doing. */
export function FanOut({ eventType, deliveries }: { eventType: string; deliveries: Delivery[] }) {
  const n = deliveries.length;
  const rowH = 52;
  const h = Math.max(n * rowH, rowH);
  const mid = h / 2;
  return (
    <div className="fanout">
      <div className="fanout-src">
        <span className="fanout-src-label">Event</span>
        <span className="fanout-src-type mono">{eventType}</span>
      </div>
      <svg className="fanout-lines" viewBox={`0 0 100 ${h}`} preserveAspectRatio="none" aria-hidden style={{ height: h }}>
        {deliveries.map((d, i) => {
          const y = i * rowH + rowH / 2;
          return (
            <path key={d.id} d={`M0 ${mid} C 50 ${mid}, 50 ${y}, 100 ${y}`} className={`fanout-line fl-${d.status}`}
              vectorEffect="non-scaling-stroke" />
          );
        })}
      </svg>
      <ul className="fanout-dst" style={{ gridAutoRows: rowH }}>
        {deliveries.map((d) => (
          <li key={d.id} className={`fanout-ep fe-${d.status}`}>
            <span className="fanout-ep-dot" aria-hidden />
            <Link href={`/endpoints/${d.endpoint_id}`} className="fanout-ep-url mono" title={d.endpoint_url}>
              {d.endpoint_url.replace(/^https?:\/\//, "")}
            </Link>
            <span className="fanout-ep-status">
              {d.last_status_code != null && <b className="mono">{d.last_status_code}</b>}
              {STATUS_LABEL[d.status]}
              <span className="muted"> · {d.run_attempt_count}/{d.run_max_attempts}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
