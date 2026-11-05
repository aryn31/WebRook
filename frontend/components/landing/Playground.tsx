"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

// A pretend HookFlow running in the browser: send events, take an endpoint down, and watch the retries.
// Nothing here talks to the API. Timings are sped up (real retries back off from 30 seconds to hours).

const MAX_ATTEMPTS = 4;
const BACKOFF_MS = [2000, 4000, 7000]; // after attempt 1, 2, 3
const SEND_MS = 650; // time "on the wire"
const MAX_EVENTS = 6;
const TYPES = ["order.created", "invoice.paid", "user.signed_up", "refund.issued"];

type Endpoint = { id: string; host: string; up: boolean };
type Attempt = { code: number; ms: number };
type Delivery = {
  endpoint: string;
  status: "sending" | "delivered" | "retrying" | "failed";
  attempts: Attempt[];
  due: number; // when the current send finishes, or the next retry starts
};
type Ev = { id: string; type: string; at: number; deliveries: Delivery[] };
type State = { endpoints: Endpoint[]; events: Ev[]; seq: number; now: number };

type Action =
  | { t: "send"; type: string; now: number }
  | { t: "toggle"; id: string }
  | { t: "replay"; event: string; endpoint: string; now: number }
  | { t: "tick"; now: number; latency: number };

function seed(id: string, type: string, results: (number[] | [number, number][])[]): Ev {
  const ids = ["orders", "billing", "notify"];
  return {
    id, type, at: 0,
    deliveries: results.map((r, i) => ({
      endpoint: ids[i],
      status: "delivered" as const,
      attempts: typeof r[0] === "number" ? [{ code: 200, ms: r[0] as number }]
        : (r as [number, number][]).map(([code, ms]) => ({ code, ms })),
      due: 0,
    })),
  };
}

const INITIAL: State = {
  endpoints: [
    { id: "orders", host: "orders.acme.dev", up: true },
    { id: "billing", host: "billing.acme.dev", up: true },
    { id: "notify", host: "notify.acme.dev", up: true },
  ],
  // A few finished events, so the log never starts empty.
  events: [
    seed("evt_01JD8V3", "invoice.paid", [[94], [[503, 1210], [200, 71]], [112]]),
    seed("evt_01JD8T7", "user.signed_up", [[63], [88], [57]]),
    seed("evt_01JD8R2", "order.created", [[102], [79], [131]]),
  ],
  seq: 1041,
  now: 0,
};

function reducer(s: State, a: Action): State {
  switch (a.t) {
    case "send": {
      const seq = s.seq + 1;
      const ev: Ev = {
        id: `evt_01JD9${seq.toString(36).toUpperCase()}`,
        type: a.type,
        at: a.now,
        deliveries: s.endpoints.map((e, i) => ({
          endpoint: e.id,
          status: "sending",
          attempts: [],
          due: a.now + SEND_MS + i * 90,
        })),
      };
      return { ...s, seq, now: a.now, events: [ev, ...s.events].slice(0, MAX_EVENTS) };
    }
    case "toggle":
      return { ...s, endpoints: s.endpoints.map((e) => (e.id === a.id ? { ...e, up: !e.up } : e)) };
    case "replay":
      return {
        ...s,
        events: s.events.map((ev) =>
          ev.id !== a.event
            ? ev
            : {
                ...ev,
                deliveries: ev.deliveries.map((d) =>
                  d.endpoint === a.endpoint && d.status === "failed"
                    ? { ...d, status: "sending", attempts: [], due: a.now + SEND_MS }
                    : d,
                ),
              },
        ),
      };
    case "tick": {
      const up = new Map(s.endpoints.map((e) => [e.id, e.up]));
      let changed = false;
      const events = s.events.map((ev) => {
        let evChanged = false;
        const deliveries = ev.deliveries.map((d): Delivery => {
          if (d.due > a.now) return d;
          if (d.status === "sending") {
            evChanged = true;
            if (up.get(d.endpoint)) {
              return { ...d, status: "delivered", attempts: [...d.attempts, { code: 200, ms: a.latency }] };
            }
            const attempts = [...d.attempts, { code: 503, ms: 1000 + (a.latency % 400) }];
            if (attempts.length >= MAX_ATTEMPTS) return { ...d, status: "failed", attempts };
            return { ...d, status: "retrying", attempts, due: a.now + BACKOFF_MS[attempts.length - 1] };
          }
          if (d.status === "retrying") {
            evChanged = true;
            return { ...d, status: "sending", due: a.now + SEND_MS };
          }
          return d;
        });
        if (!evChanged) return ev;
        changed = true;
        return { ...ev, deliveries };
      });
      return changed ? { ...s, events, now: a.now } : { ...s, now: a.now };
    }
  }
}

// Plays a short story until the visitor touches anything: events flow, billing goes down, gets retried, recovers.
const SCRIPT: { at: number; do: "send" | "billing" }[] = [
  { at: 400, do: "send" },
  { at: 2600, do: "send" },
  { at: 4200, do: "billing" },
  { at: 4800, do: "send" },
  { at: 7600, do: "send" },
  { at: 10400, do: "billing" },
  { at: 12800, do: "send" },
  { at: 15500, do: "send" },
];
const SCRIPT_LOOP_MS = 18000;

export function Playground() {
  const [s, dispatch] = useReducer(reducer, INITIAL);
  const [type, setType] = useState(TYPES[0]);
  const [auto, setAuto] = useState(true);
  const [visible, setVisible] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const typeIdx = useRef(0);

  // Only run while on screen.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    const id = window.setInterval(() => {
      dispatch({ t: "tick", now: Date.now(), latency: 38 + Math.floor(Math.random() * 140) });
    }, 120);
    return () => window.clearInterval(id);
  }, [visible]);

  useEffect(() => {
    if (!auto || !visible) return;
    let timers: number[] = [];
    const run = () => {
      timers = SCRIPT.map((step) =>
        window.setTimeout(() => {
          if (step.do === "send") {
            typeIdx.current = (typeIdx.current + 1) % TYPES.length;
            dispatch({ t: "send", type: TYPES[typeIdx.current], now: Date.now() });
          } else dispatch({ t: "toggle", id: "billing" });
        }, step.at),
      );
    };
    run();
    const loop = window.setInterval(run, SCRIPT_LOOP_MS);
    return () => {
      timers.forEach(window.clearTimeout);
      window.clearInterval(loop);
    };
  }, [auto, visible]);

  // The first click hands control to the visitor.
  const takeOver = useCallback(() => {
    if (!auto) return;
    setAuto(false);
  }, [auto]);

  const send = () => {
    takeOver();
    dispatch({ t: "send", type, now: Date.now() });
  };

  const all = s.events.flatMap((e) => e.deliveries);
  const delivered = all.filter((d) => d.status === "delivered").length;
  const retrying = all.filter((d) => d.status === "retrying" || (d.status === "sending" && d.attempts.length > 0)).length;
  const failed = all.filter((d) => d.status === "failed").length;
  const settled = delivered + failed;
  const rate = settled ? Math.round((delivered / settled) * 100) : 100;

  return (
    <div className="pg ink" ref={box}>
      <div className="pg-bar">
        <span className="pg-dots" aria-hidden><i /><i /><i /></span>
        <span className="pg-title">HookFlow · Live demo</span>
        <span className={`pg-mode${auto ? " is-auto" : ""}`}>{auto ? "Autoplay · click anything to take over" : "You're in control"}</span>
      </div>

      <div className="pg-body">
        <aside className="pg-side">
          <div className="pg-send">
            <label className="pg-label" htmlFor="pg-type">Event type</label>
            <select id="pg-type" className="pg-select" value={type}
              onChange={(e) => { takeOver(); setType(e.target.value); }}>
              {TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <button type="button" className="btn btn-signal pg-send-btn" onClick={send}>
              Send event <span aria-hidden>→</span>
            </button>
          </div>

          <div className="pg-label">Endpoints <span className="pg-hint">click to take one down</span></div>
          <ul className="pg-endpoints">
            {s.endpoints.map((e) => (
              <li key={e.id}>
                <button type="button" className={`pg-ep${e.up ? "" : " is-down"}`} aria-pressed={!e.up}
                  onClick={() => { takeOver(); dispatch({ t: "toggle", id: e.id }); }}>
                  <span className="pg-ep-dot" />
                  <span className="pg-ep-host">{e.host}</span>
                  <span className="pg-ep-state">{e.up ? "Online" : "Down"}</span>
                </button>
              </li>
            ))}
          </ul>

          <dl className="pg-stats">
            <div><dt>Delivered</dt><dd className="ok">{delivered}</dd></div>
            <div><dt>Retrying</dt><dd className="warn">{retrying}</dd></div>
            <div><dt>Failed</dt><dd className="bad">{failed}</dd></div>
            <div><dt>Success</dt><dd>{rate}%</dd></div>
          </dl>
        </aside>

        <div className="pg-log" aria-live="polite">
          <div className="pg-log-head">
            <span>Event</span>
            {s.endpoints.map((e) => <span key={e.id}>{e.id}</span>)}
          </div>
          {s.events.length === 0 && <div className="pg-empty">Press <strong>Send event</strong> to fire your first webhook.</div>}
          {s.events.map((ev) => (
            <div className="pg-row" key={ev.id}>
              <div className="pg-ev">
                <span className="pg-ev-type">{ev.type}</span>
                <span className="pg-ev-id">{ev.id}</span>
              </div>
              {ev.deliveries.map((d) => (
                <Cell key={d.endpoint} d={d} now={s.now}
                  onReplay={() => { takeOver(); dispatch({ t: "replay", event: ev.id, endpoint: d.endpoint, now: Date.now() }); }} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Cell({ d, now, onReplay }: { d: Delivery; now: number; onReplay: () => void }) {
  const n = d.attempts.length;
  const last = d.attempts[n - 1];
  let body: React.ReactNode;
  if (d.status === "delivered") {
    body = <><b>200</b><span className="pg-long">{last.ms} ms{n > 1 ? ` · try ${n}` : ""}</span></>;
  } else if (d.status === "retrying") {
    const secs = Math.max(Math.ceil((d.due - now) / 1000), 0);
    body = <><b>503</b><span><span className="pg-long">retry in </span>{secs}s</span></>;
  } else if (d.status === "failed") {
    body = (
      <>
        <b className="pg-long">Failed</b>
        <button type="button" className="pg-replay" onClick={onReplay}>Replay</button>
      </>
    );
  } else {
    body = <><i className="pg-spin" aria-hidden /><span className="pg-long">{n > 0 ? `attempt ${n + 1}` : "sending"}</span></>;
  }
  return <div className={`pg-cell is-${d.status}`}>{body}</div>;
}
