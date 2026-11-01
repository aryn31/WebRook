"use client";

import { useEffect, useRef } from "react";

// Full-bleed photo hero. Signals arc from a beacon on the near ridge to three distant peaks (the endpoints).
// The middle one answers 503, is retried, then answers 200. The SVG uses the photo's own coordinate system
// (1200×800, "slice" = object-fit: cover), so the arcs stay pinned to the same peaks at any screen size.

const CYCLE = "7s";
const ORIGIN = { x: 880, y: 516 };
// Kept near the middle of the photo so they stay on screen however the photo is cropped.
const PEAKS = [
  { x: 588, y: 241, name: "orders", fail: false },
  { x: 760, y: 214, name: "billing", fail: true },
  { x: 905, y: 205, name: "notify", fail: false },
];

function arc(to: { x: number; y: number }) {
  const midX = (ORIGIN.x + to.x) / 2;
  const lift = 50 + Math.abs(ORIGIN.x - to.x) * 0.12;
  return `M${ORIGIN.x} ${ORIGIN.y} Q${midX} ${Math.min(ORIGIN.y, to.y) - lift} ${to.x} ${to.y}`;
}

const f = (n: number) => n.toFixed(3);

/** Something visible from `a` to `b` (fractions of the cycle). */
function window01(a: number, b: number) {
  return { values: "0;0;1;1;0;0", keyTimes: `0;${f(a)};${f(a + 0.02)};${f(b)};${f(b + 0.02)};1` };
}

function Packet({ path, start, len }: { path: string; start: number; len: number }) {
  const end = start + len;
  return (
    <circle r="3.4" className="scene-packet" opacity="0">
      <animateMotion dur={CYCLE} repeatCount="indefinite" path={path} keyPoints="0;0;1;1"
        keyTimes={`0;${f(start)};${f(end)};1`} calcMode="spline" keySplines="0 0 1 1;0.45 0 0.2 1;0 0 1 1" />
      <animate attributeName="opacity" dur={CYCLE} repeatCount="indefinite" values="0;1;1;0;0"
        keyTimes={`0;${f(start)};${f(end - 0.004)};${f(end)};1`} />
    </circle>
  );
}

function Ping({ x, y, at, tone }: { x: number; y: number; at: number; tone: "ok" | "bad" }) {
  return (
    <circle cx={x} cy={y} r="4" className={`scene-ping scene-ping-${tone}`} opacity="0">
      <animate attributeName="r" dur={CYCLE} repeatCount="indefinite" values="4;4;26;26"
        keyTimes={`0;${f(at)};${f(at + 0.12)};1`} />
      <animate attributeName="opacity" dur={CYCLE} repeatCount="indefinite" values="0;0;0.9;0;0"
        keyTimes={`0;${f(at - 0.001)};${f(at)};${f(at + 0.12)};1`} />
    </circle>
  );
}

function Label({ x, y, name, code, tone, a, b }: {
  x: number; y: number; name: string; code: string; tone: "ok" | "bad"; a: number; b: number;
}) {
  const w = window01(a, b);
  return (
    <g opacity="0">
      <animate attributeName="opacity" dur={CYCLE} repeatCount="indefinite" values={w.values} keyTimes={w.keyTimes} />
      <rect x={x - 54} y={y - 40} width="108" height="22" rx="11" className="scene-chip" />
      <circle cx={x - 41} cy={y - 29} r="3.5" className={`scene-chip-dot scene-chip-${tone}`} />
      <text x={x - 32} y={y - 25} className="scene-chip-text">{name} · {code}</text>
    </g>
  );
}

export function HeroScene({ children }: { children: React.ReactNode }) {
  const media = useRef<HTMLDivElement>(null);
  const copy = useRef<HTMLDivElement>(null);

  // Gentle parallax: the photo drifts slower than the page; the headline lifts and fades.
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const y = Math.min(window.scrollY, 900);
      if (media.current) media.current.style.transform = `translate3d(0, ${y * 0.32}px, 0) scale(${1.04 + y * 0.00005})`;
      if (copy.current) {
        copy.current.style.transform = `translate3d(0, ${y * 0.12}px, 0)`;
        copy.current.style.opacity = String(Math.max(1 - y / 650, 0));
      }
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <section className="scene" aria-label="HookFlow">
      <div className="scene-media" ref={media}>
        <img
          className="scene-img"
          src="/landing/ridges-1600.jpg"
          srcSet="/landing/ridges-900.jpg 900w, /landing/ridges-1600.jpg 1600w, /landing/ridges-2600.jpg 2600w"
          sizes="100vw"
          alt=""
          fetchPriority="high"
          decoding="async"
        />
        <svg className="scene-svg" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice" aria-hidden>
          <defs>
            <filter id="scene-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {PEAKS.map((p) => (
            <path key={p.name} d={arc(p)} className="scene-arc" />
          ))}

          {/* first wave: all three */}
          <g filter="url(#scene-glow)">
            {PEAKS.map((p, i) => <Packet key={p.name} path={arc(p)} start={0.04 + i * 0.03} len={0.2} />)}
            {/* the retry to "billing" */}
            <Packet path={arc(PEAKS[1])} start={0.55} len={0.2} />
          </g>

          <Ping x={PEAKS[0].x} y={PEAKS[0].y} at={0.24} tone="ok" />
          <Ping x={PEAKS[1].x} y={PEAKS[1].y} at={0.27} tone="bad" />
          <Ping x={PEAKS[1].x} y={PEAKS[1].y} at={0.75} tone="ok" />
          <Ping x={PEAKS[2].x} y={PEAKS[2].y} at={0.30} tone="ok" />

          {PEAKS.map((p) => <circle key={p.name} cx={p.x} cy={p.y} r="3" className="scene-peak" />)}

          <Label x={PEAKS[0].x} y={PEAKS[0].y} name="orders" code="200" tone="ok" a={0.25} b={0.94} />
          <Label x={PEAKS[1].x} y={PEAKS[1].y} name="billing" code="503" tone="bad" a={0.28} b={0.52} />
          <Label x={PEAKS[1].x} y={PEAKS[1].y} name="billing" code="200" tone="ok" a={0.76} b={0.94} />
          <Label x={PEAKS[2].x} y={PEAKS[2].y} name="notify" code="200" tone="ok" a={0.31} b={0.94} />

          <g className="scene-origin">
            <circle cx={ORIGIN.x} cy={ORIGIN.y} r="9" className="scene-origin-halo" />
            <circle cx={ORIGIN.x} cy={ORIGIN.y} r="4.5" className="scene-origin-core" />
          </g>
        </svg>
      </div>
      <div className="scene-shade" />
      <div className="scene-copy lp-wrap" ref={copy}>
        {children}
      </div>
    </section>
  );
}
