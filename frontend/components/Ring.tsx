"use client";

import { useEffect, useState } from "react";

/** A percentage as a ring that fills in. Colour comes from the `--hero-tone` of the surrounding element. */
export function Ring({ pct, label = "success", size }: { pct: number | null; label?: string; size?: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = window.requestAnimationFrame(() => setShown(pct ?? 0));
    return () => window.cancelAnimationFrame(id);
  }, [pct]);
  return (
    <div className="ring" style={size ? { width: size, height: size } : undefined}>
      <svg viewBox="0 0 120 120" aria-hidden>
        <circle cx="60" cy="60" r={r} className="ring-track" />
        <circle cx="60" cy="60" r={r} className="ring-value" strokeDasharray={c}
          strokeDashoffset={c * (1 - shown / 100)} transform="rotate(-90 60 60)" />
      </svg>
      <div className="ring-label">
        <span className="ring-num">{pct == null ? "—" : `${pct}%`}</span>
        <span className="ring-sub">{label}</span>
      </div>
    </div>
  );
}
