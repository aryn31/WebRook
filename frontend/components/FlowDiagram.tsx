// Animated illustration: one event fans out to three endpoints; the middle one fails (503), is retried and
// succeeds. Pure SVG + SMIL, so it runs without JavaScript. Purely decorative.

const CYCLE = "6s";
const APP = { x: 12, y: 128, w: 124, h: 44 };
const CORE = { x: 196, y: 116, w: 176, h: 68 };
const EPS = [
  { y: 30, label: "orders.example.com" },
  { y: 128, label: "billing.example.com" },
  { y: 226, label: "notify.example.com" },
];
const EP = { x: 402, w: 168, h: 44 };

const inPath = `M${APP.x + APP.w} ${APP.y + APP.h / 2} H${CORE.x}`;
const outPath = (y: number) => {
  const sx = CORE.x + CORE.w;
  const sy = CORE.y + CORE.h / 2;
  const ey = y + EP.h / 2;
  return `M${sx} ${sy} C${sx + 40} ${sy}, ${EP.x - 40} ${ey}, ${EP.x} ${ey}`;
};

/** A dot that travels `path` once per cycle, starting `start` (0–1) into the cycle and taking `len` of it. */
function Packet({ path, start, len, tone }: { path: string; start: number; len: number; tone: "signal" | "bad" }) {
  const end = start + len;
  const kt = `0;${start.toFixed(3)};${end.toFixed(3)};1`;
  return (
    <circle r="4.5" className={`flow-packet flow-packet-${tone}`} opacity="0">
      <animateMotion dur={CYCLE} repeatCount="indefinite" path={path} keyPoints="0;0;1;1" keyTimes={kt} calcMode="linear" />
      <animate attributeName="opacity" dur={CYCLE} repeatCount="indefinite"
        values="0;1;1;0;0" keyTimes={`0;${start.toFixed(3)};${(end - 0.005).toFixed(3)};${end.toFixed(3)};1`} />
    </circle>
  );
}

/** A status chip at an endpoint, visible between `from` and `to` (fractions of the cycle). */
function Badge({ x, y, text, tone, from, to }: { x: number; y: number; text: string; tone: "ok" | "bad"; from: number; to: number }) {
  return (
    <g opacity="0">
      <animate attributeName="opacity" dur={CYCLE} repeatCount="indefinite"
        values="0;0;1;1;0;0" keyTimes={`0;${from.toFixed(3)};${(from + 0.02).toFixed(3)};${to.toFixed(3)};${(to + 0.02).toFixed(3)};1`} />
      <rect x={x} y={y} width="34" height="18" rx="5" className={`flow-badge flow-badge-${tone}`} />
      <text x={x + 17} y={y + 12.5} textAnchor="middle" className="flow-badge-text">{text}</text>
    </g>
  );
}

export function FlowDiagram({ compact = false }: { compact?: boolean }) {
  return (
    <svg viewBox="0 0 580 300" className={`flow${compact ? " flow-compact" : ""}`} role="img"
      aria-label="An event sent once to HookFlow is delivered to three endpoints. One fails with HTTP 503, is retried and succeeds.">
      <defs>
        <pattern id="flow-dots" width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" className="flow-grid-dot" />
        </pattern>
      </defs>
      <rect width="580" height="300" fill="url(#flow-dots)" />

      <path d={inPath} className="flow-line" />
      {EPS.map((e) => <path key={e.label} d={outPath(e.y)} className="flow-line" />)}

      {/* source */}
      <g>
        <rect x={APP.x} y={APP.y} width={APP.w} height={APP.h} rx="10" className="flow-node" />
        <text x={APP.x + 16} y={APP.y + 19} className="flow-label">Your app</text>
        <text x={APP.x + 16} y={APP.y + 33} className="flow-sub">POST /v1/events</text>
      </g>

      {/* HookFlow */}
      <g>
        <rect x={CORE.x} y={CORE.y} width={CORE.w} height={CORE.h} rx="14" className="flow-core" />
        <rect x={CORE.x + 16} y={CORE.y + 20} width="28" height="28" rx="8" className="flow-core-tile" />
        <path d={`M${CORE.x + 22} ${CORE.y + 38}c2.4 0 2.9-8 7-8s4.6 8 7 8`} className="flow-core-wave" />
        <text x={CORE.x + 54} y={CORE.y + 32} className="flow-core-label">HookFlow</text>
        <text x={CORE.x + 54} y={CORE.y + 47} className="flow-core-sub">sign · retry · log</text>
      </g>

      {/* endpoints */}
      {EPS.map((e) => (
        <g key={e.label}>
          <rect x={EP.x} y={e.y} width={EP.w} height={EP.h} rx="10" className="flow-node" />
          <circle cx={EP.x + 16} cy={e.y + EP.h / 2} r="3.5" className="flow-ep-dot" />
          <text x={EP.x + 28} y={e.y + 26} className="flow-host">{e.label}</text>
        </g>
      ))}

      <Packet path={inPath} start={0.02} len={0.13} tone="signal" />
      {EPS.map((e) => <Packet key={e.label} path={outPath(e.y)} start={0.16} len={0.14} tone="signal" />)}
      {/* the retry to the middle endpoint */}
      <Packet path={outPath(EPS[1].y)} start={0.5} len={0.14} tone="signal" />

      <Badge x={EP.x + EP.w - 42} y={EPS[0].y - 9} text="200" tone="ok" from={0.3} to={0.93} />
      <Badge x={EP.x + EP.w - 42} y={EPS[1].y - 9} text="503" tone="bad" from={0.3} to={0.5} />
      <Badge x={EP.x + EP.w - 42} y={EPS[1].y - 9} text="200" tone="ok" from={0.64} to={0.93} />
      <Badge x={EP.x + EP.w - 42} y={EPS[2].y - 9} text="200" tone="ok" from={0.3} to={0.93} />

      <g opacity="0">
        <animate attributeName="opacity" dur={CYCLE} repeatCount="indefinite"
          values="0;0;1;1;0;0" keyTimes="0;0.32;0.34;0.5;0.52;1" />
        <text x={EP.x - 8} y={EPS[1].y + EP.h + 18} textAnchor="end" className="flow-note">retrying in 30s…</text>
      </g>
    </svg>
  );
}
