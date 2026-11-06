import type { Metadata } from "next";
import Link from "next/link";
import { AuthCta } from "@/components/AuthCta";
import { FlowDiagram } from "@/components/FlowDiagram";
import { SiteFooter, SiteHeader } from "@/components/SiteChrome";

export const metadata: Metadata = {
  title: "Platform",
  description:
    "How HookFlow accepts, delivers, retries, signs and records your webhooks, and the limits it runs within.",
};

const SECTIONS = [
  ["how", "How it works"],
  ["lifecycle", "Lifecycle"],
  ["reliability", "Reliability"],
  ["security", "Security"],
  ["visibility", "Visibility"],
  ["limits", "Limits"],
] as const;

const STEPS = [
  ["Accept", "Your app POSTs an event with an API key. We validate it, store it and reply 202, usually within milliseconds."],
  ["Fan out", "One delivery is created for every enabled endpoint subscribed to that event type, or to every event."],
  ["Deliver", "A worker signs the request and sends it, waiting up to 10 seconds for a response."],
  ["Record", "Every attempt is saved: status code, response body, timing, and a plain-English reason when it fails."],
];

const STATES = [
  { s: "pending", t: "Pending", d: "Saved and waiting for a worker." },
  { s: "processing", t: "Sending", d: "A worker holds a 60-second lease and is sending it." },
  { s: "retrying", t: "Retrying", d: "It failed in a way worth retrying. The next attempt is scheduled." },
  { s: "delivered", t: "Delivered", d: "The endpoint answered with a 2xx." },
  { s: "failed", t: "Failed", d: "Out of attempts, or an error that retrying won't fix. Can be replayed." },
];

const BACKOFF = [
  ["1", "now"],
  ["2", "+30s"],
  ["3", "+2m"],
  ["4", "+8m"],
  ["5", "+32m"],
];

const LIMITS = [
  ["Delivery attempts", "5 by default, 1–10 per endpoint"],
  ["Retry backoff", "30s × 4ⁿ with ±25% jitter, at most 6h"],
  ["Request timeout", "10 seconds per attempt"],
  ["Payload size", "1 MiB per event"],
  ["Ingestion rate", "600 events per minute per account"],
  ["Daily quota", "10,000 new events per account"],
  ["In flight per endpoint", "10 requests at once"],
  ["Endpoints", "50 per account"],
  ["Idempotency keys", "Remembered for 24 hours"],
  ["History", "Events and attempts kept for 30 days"],
  ["Response bodies", "First 4 KiB stored"],
  ["Manual replays", "60 deliveries per minute"],
];

export default function PlatformPage() {

  return (
    <div className="lp">
      <SiteHeader active="platform" />

      <main>
        <section className="pf-hero">
          <div className="lp-wrap">
            <p className="lp-kicker">Platform</p>
            <h1 className="pf-title">
              How HookFlow <em>delivers.</em>
            </h1>
            <p className="pf-lead">
              What happens between your app sending an event and your customer&apos;s server receiving it, and
              everything we do when that server isn&apos;t answering.
            </p>
            <nav className="pf-toc" aria-label="On this page">
              {SECTIONS.map(([id, label]) => (
                <a key={id} href={`#${id}`}>{label}</a>
              ))}
            </nav>
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="pf-section">
          <div className="lp-wrap">
            <div className="pf-head">
              <span className="lp-row-num">01</span>
              <h2>How it works</h2>
              <p>Send once. HookFlow takes it from there.</p>
            </div>
            <div className="pf-diagram ink">
              <FlowDiagram />
            </div>
            <ol className="pf-steps">
              {STEPS.map(([t, d], i) => (
                <li key={t}>
                  <span className="pf-step-num">{i + 1}</span>
                  <h3>{t}</h3>
                  <p>{d}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Lifecycle */}
        <section id="lifecycle" className="pf-section pf-alt">
          <div className="lp-wrap">
            <div className="pf-head">
              <span className="lp-row-num">02</span>
              <h2>The life of a delivery</h2>
              <p>One delivery is one event going to one endpoint. It is always in exactly one of these states.</p>
            </div>
            <ol className="pf-states">
              {STATES.map((x) => (
                <li key={x.s} className={`pf-state pf-state-${x.s}`}>
                  <span className={`pill pill-${x.s}`}><span className="pill-dot" /> {x.t}</span>
                  <p>{x.d}</p>
                </li>
              ))}
            </ol>
            <p className="pf-note">
              Disabling or deleting an endpoint cancels its unsent deliveries. Failed and cancelled deliveries can be
              replayed: the same delivery goes back to pending with a fresh set of attempts, and the history keeps both.
            </p>
          </div>
        </section>

        {/* Reliability */}
        <section id="reliability" className="pf-section">
          <div className="lp-wrap">
            <div className="pf-head">
              <span className="lp-row-num">03</span>
              <h2>Built not to lose anything</h2>
              <p>Delivery is at-least-once. Every event has a stable ID, so receivers can drop the rare duplicate.</p>
            </div>
            <div className="pf-split">
              <div className="pf-card">
                <h3>Retries that back off</h3>
                <p>
                  Timeouts, connection errors, 408, 429 and 5xx are retried. Other 4xx responses stop at once, so a
                  wrong URL doesn&apos;t burn attempts. A <code>Retry-After</code> header is honoured.
                </p>
                <ol className="pf-backoff">
                  {BACKOFF.map(([n, at], i) => (
                    <li key={n}>
                      <span className={`pf-backoff-dot${i === BACKOFF.length - 1 ? " ok" : ""}`} />
                      <span className="pf-backoff-at">{at}</span>
                      <span className="pf-backoff-n">attempt {n}</span>
                    </li>
                  ))}
                </ol>
              </div>
              <div className="pf-card">
                <h3>Saved before we say yes</h3>
                <ol className="pf-seq">
                  <li><b>Saved:</b> the event, its deliveries and their queue messages, in one database transaction.</li>
                  <li><b>202</b> returned to your app. If the queue is down, nothing is lost; messages wait in the database.</li>
                  <li><b>Claimed</b> by a worker with a 60-second lease, so two workers never send the same attempt.</li>
                  <li><b>Recovered</b> automatically: a sweeper reclaims work from a worker that crashed mid-send.</li>
                </ol>
              </div>
            </div>
            <div className="pf-card pf-card-wide">
              <h3>Idempotent ingestion</h3>
              <p>
                Send an <code>Idempotency-Key</code> header and retry your own request as often as you like: the same key
                and body return the original event instead of creating a new one. Reusing a key with a different body is
                rejected, so mistakes are loud.
              </p>
            </div>
          </div>
        </section>

        {/* Security */}
        <section id="security" className="pf-section pf-alt">
          <div className="lp-wrap">
            <div className="pf-head">
              <span className="lp-row-num">04</span>
              <h2>Secure by default</h2>
              <p>Receivers can prove a request came from you, and HookFlow can&apos;t be pointed at your own network.</p>
            </div>
            <div className="pf-split">
              <div className="pf-code">
                <pre>
                  <span className="pf-dim">POST /webhooks HTTP/1.1</span>{"\n"}
                  <span className="pf-key">HookFlow-Event-Id:</span> evt_01JD7Q…{"\n"}
                  <span className="pf-key">HookFlow-Delivery-Id:</span> dlv_01JD7R…{"\n"}
                  <span className="pf-key">HookFlow-Attempt:</span> 2{"\n"}
                  <span className="pf-key">HookFlow-Timestamp:</span> 1793612400{"\n"}
                  <span className="pf-key">HookFlow-Signature:</span> <span className="pf-hi">v1=9f3c51…e07a</span>
                </pre>
              </div>
              <ul className="pf-list">
                <li><b>Signed requests.</b> HMAC-SHA256 over the timestamp and raw body, so receivers can also reject anything
                  older than five minutes.</li>
                <li><b>Rotation without downtime.</b> During a grace period of up to 7 days, both the new and old secret
                  sign each request.</li>
                <li><b>SSRF protection.</b> Only public addresses. We connect to the exact IP we checked, which blocks DNS
                  rebinding, and never follow redirects.</li>
                <li><b>Secrets at rest.</b> Signing secrets are encrypted; API keys and passwords are stored only as
                  hashes.</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Visibility */}
        <section id="visibility" className="pf-section">
          <div className="lp-wrap">
            <div className="pf-head">
              <span className="lp-row-num">05</span>
              <h2>Nothing is a black box</h2>
              <p>When a customer says &ldquo;we never got it&rdquo;, you can show exactly what happened.</p>
            </div>
            <div className="pf-split">
              <ul className="pf-attempts">
                <li><span className="code-badge bad">503</span><span>Attempt 1 · destination returned HTTP 503</span><span className="pf-dim">1.2 s</span></li>
                <li><span className="code-badge bad">503</span><span>Attempt 2 · destination returned HTTP 503</span><span className="pf-dim">1.1 s</span></li>
                <li className="pf-attempts-replay">↻ Replayed from dashboard</li>
                <li><span className="code-badge ok">200</span><span>Attempt 3 · delivered</span><span className="pf-dim">97 ms</span></li>
              </ul>
              <ul className="pf-list">
                <li><b>Dashboard.</b> Events, deliveries and attempts, success rate, response times, usage, and the
                  health of every endpoint over the last 24 hours.</li>
                <li><b>Replay.</b> One delivery, or every failed delivery of an event, from the dashboard or the API.</li>
                <li><b>Audit log.</b> Keys created, endpoints changed, secrets revealed and replays: who, when and from
                  where.</li>
                <li><b>Operations.</b> Health checks, Prometheus metrics and alerts when work gets stuck.</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Limits */}
        <section id="limits" className="pf-section pf-alt">
          <div className="lp-wrap">
            <div className="pf-head">
              <span className="lp-row-num">06</span>
              <h2>Limits, in writing</h2>
              <p>The defaults. Every limited response says how much you have left and when it resets.</p>
            </div>
            <dl className="pf-limits">
              {LIMITS.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="lp-wrap">
          <div className="lp-final ink">
            <img className="lp-final-img" src="/landing/ridges-1600.jpg" alt="" loading="lazy" decoding="async" />
            <h2>
              Seen enough?
              <br />
              <em>Send your first event.</em>
            </h2>
            <div className="lp-final-cta">
              <AuthCta variant="final" secondary={<Link href="/contact" className="btn btn-lg lp-final-login">Talk to us</Link>} />
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
