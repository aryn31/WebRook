"use client";

import { useMemo, useState } from "react";
import type { Stats, StatsRange } from "@/lib/api";
import { formatUtc } from "@/lib/format";

type Point = Stats["series"][number];
type Key = "events" | "delivered" | "failed";

const SERIES: { key: Key; label: string; color: string }[] = [
  { key: "events", label: "Events", color: "var(--series-events)" },
  { key: "delivered", label: "Delivered", color: "var(--status-delivered)" },
  { key: "failed", label: "Failed", color: "var(--status-failed)" },
];

function bucketLabel(iso: string, range: StatsRange): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (range === "24h") return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / mag;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * mag;
}

/** Grouped bars per bucket, inline SVG, hover tooltip. */
export function SeriesChart({ series, range }: { series: Point[]; range: StatsRange }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 760;
  const H = 220;
  const pad = { l: 36, r: 8, t: 10, b: 24 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;

  const max = useMemo(() => niceMax(Math.max(0, ...series.flatMap((p) => [p.events, p.delivered, p.failed]))), [series]);
  const n = Math.max(series.length, 1);
  const band = innerW / n;
  const groupW = Math.min(band * 0.78, 42);
  const gap = band > 14 ? 1.5 : 0.5;
  const barW = Math.max((groupW - gap * 2) / 3, 1);
  const y = (v: number) => pad.t + innerH - (v / max) * innerH;
  const ticks = [0, max / 2, max];
  const labelEvery = Math.ceil(n / 8);

  const total = series.reduce((a, p) => a + p.events + p.delivered + p.failed, 0);
  const hp = hover != null ? series[hover] : null;

  return (
    <div className="chart">
      <div className="chart-legend">
        {SERIES.map((s) => (
          <span key={s.key} className="legend-item">
            <span className="legend-swatch" style={{ background: s.color }} /> {s.label}
          </span>
        ))}
      </div>
      <div className="chart-box">
        <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img" aria-label="Events, delivered and failed deliveries over time" onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={pad.l - 6} y={y(t) + 3} textAnchor="end" className="chart-tick">
                {Number.isInteger(t) ? t : t.toFixed(1)}
              </text>
            </g>
          ))}
          {series.map((p, i) => {
            const x0 = pad.l + i * band + (band - groupW) / 2;
            return (
              <g key={p.bucket}>
                {hover === i && <rect x={pad.l + i * band} y={pad.t} width={band} height={innerH} className="chart-hover-band" />}
                {SERIES.map((s, j) => {
                  const v = p[s.key];
                  if (v === 0) return null;
                  const bx = x0 + j * (barW + gap);
                  const r = Math.min(2, barW / 2);
                  return (
                    <path
                      key={s.key}
                      d={`M${bx},${pad.t + innerH} V${y(v) + r} Q${bx},${y(v)} ${bx + r},${y(v)} H${bx + barW - r} Q${bx + barW},${y(v)} ${bx + barW},${y(v) + r} V${pad.t + innerH} Z`}
                      fill={s.color}
                      opacity={hover == null || hover === i ? 1 : 0.45}
                    >
                      <title>{`${s.label}: ${v}`}</title>
                    </path>
                  );
                })}
                {i % labelEvery === 0 && (
                  <text x={pad.l + i * band + band / 2} y={H - 6} textAnchor="middle" className="chart-tick">
                    {bucketLabel(p.bucket, range)}
                  </text>
                )}
                <rect
                  x={pad.l + i * band}
                  y={pad.t}
                  width={band}
                  height={innerH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              </g>
            );
          })}
          <line x1={pad.l} x2={W - pad.r} y1={pad.t + innerH} y2={pad.t + innerH} className="chart-axis" />
        </svg>
        {hp && hover != null && (
          <div
            className="chart-tooltip"
            style={{ left: `${((pad.l + hover * band + band / 2) / W) * 100}%` }}
          >
            <div className="chart-tooltip-title" title={formatUtc(hp.bucket)}>
              {range === "24h"
                ? new Date(hp.bucket).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
                : new Date(hp.bucket).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
            </div>
            {SERIES.map((s) => (
              <div key={s.key} className="chart-tooltip-row">
                <span className="legend-swatch" style={{ background: s.color }} />
                <span>{s.label}</span>
                <span className="mono">{hp[s.key]}</span>
              </div>
            ))}
          </div>
        )}
        {total === 0 && <div className="chart-empty">No activity in this range yet.</div>}
      </div>
    </div>
  );
}
