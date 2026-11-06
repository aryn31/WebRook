import type { Metadata } from "next";
import { API_PUBLIC_URL } from "@/lib/api";
import Link from "next/link";
import { SiteFooter, SiteHeader } from "@/components/SiteChrome";
import { AuthCta } from "@/components/AuthCta";
import { CodeTabs } from "@/components/CodeTabs";
import { HeroScene } from "@/components/HeroScene";
import { IconArrow } from "@/components/Icons";
import { Playground } from "@/components/landing/Playground";
import { Reveal } from "@/components/landing/Reveal";

export const metadata: Metadata = {
  title: { absolute: "HookFlow — webhooks that arrive" },
  description:
    "Send an event to HookFlow once. It delivers it to every subscribed endpoint, signs it, retries failures and records every attempt.",
};

const SAMPLES = [
  {
    label: "curl",
    code: `curl -X POST ${API_PUBLIC_URL}/v1/events \\
  -H "Authorization: Bearer $HOOKFLOW_KEY" \\
  -H "Idempotency-Key: order-1042" \\
  -H "Content-Type: application/json" \\
  -d '{"event_type": "order.created",
       "data": {"order_id": "1042", "total": 4999}}'`,
  },
  {
    label: "Node.js",
    code: `await fetch("${API_PUBLIC_URL}/v1/events", {
  method: "POST",
  headers: {
    Authorization: \`Bearer \${process.env.HOOKFLOW_KEY}\`,
    "Idempotency-Key": "order-1042",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    event_type: "order.created",
    data: { order_id: "1042", total: 4999 },
  }),
});`,
  },
  {
    label: "Python",
    code: `import os, httpx

httpx.post(
    "${API_PUBLIC_URL}/v1/events",
    headers={
        "Authorization": f"Bearer {os.environ['HOOKFLOW_KEY']}",
        "Idempotency-Key": "order-1042",
    },
    json={"event_type": "order.created",
          "data": {"order_id": "1042", "total": 4999}},
)`,
  },
];

const STRIP = [
  { big: "202", small: "accepted in milliseconds" },
  { big: "5×", small: "attempts, backing off to 6 hours" },
  { big: "HMAC", small: "SHA-256 signature on every request" },
  { big: "30 days", small: "of attempts you can replay" },
];

const STEPS = [
  {
    title: "Add an endpoint",
    body: "Paste the URL that should receive events and pick which event types it wants.",
    ui: <div className="step-ui"><span className="step-ui-label">URL</span><span className="step-ui-input">https://api.acme.dev/hooks<i className="step-caret" /></span></div>,
  },
  {
    title: "Create an API key",
    body: "Scoped to just what it needs: send events, read deliveries, or both.",
    ui: <div className="step-ui"><span className="step-ui-label">Key</span><span className="step-ui-input mono">hf_live_••••••••3f9a</span></div>,
  },
  {
    title: "Send your first event",
    body: "One POST. HookFlow signs it, delivers it, and keeps trying until it lands.",
    ui: <div className="step-ui"><span className="step-ui-badge">202</span><span className="step-ui-input mono">evt_01JD8…  queued → delivered</span></div>,
  },
];

const FAQ = [
  {
    q: "What happens when my customer's server is down?",
    a: "HookFlow retries on an exponential schedule (5 attempts by default, up to 6 hours apart, or your own schedule). Each attempt is recorded with its status code and response. If every attempt fails, the delivery is marked failed and you can replay it from the dashboard or the API.",
  },
  {
    q: "Do I need an SDK?",
    a: "No. Sending an event is one HTTPS request from any language. Receivers check a standard HMAC-SHA256 signature; the docs have copy-paste examples.",
  },
  {
    q: "Can it send the same event twice?",
    a: "Delivery is at-least-once, so a receiver can very rarely see a duplicate. Every event and delivery has a stable ID to drop it. On your side, send an Idempotency-Key and retrying your own request never creates a second event.",
  },
  {
    q: "Can my team use it?",
    a: "Yes. Invite people as admins, developers or viewers. Every key created, endpoint changed and secret revealed is in the audit log.",
  },
  {
    q: "How much does it cost?",
    a: "Sign up free, no card needed. Each account can send 10,000 events a day to up to 50 endpoints.",
  },
];

export default function LandingPage() {

  return (
    <div className="lp">
      <noscript><style>{`.reveal{opacity:1!important;transform:none!important}`}</style></noscript>
      <SiteHeader active="home" />

      <main>
        {/* ---------- hero ---------- */}
        <HeroScene>
          <p className="scene-kicker"><span className="lp-live-dot" /> Webhook delivery</p>
          <h1 className="scene-title">
            Webhooks that <em>arrive.</em>
          </h1>
          <div className="scene-row">
            <p className="scene-lead">
              However far they have to go. Send each event to HookFlow once; we deliver it to every endpoint that wants
              it, signed, retried when they&apos;re down, and recorded attempt by attempt.
            </p>
            <div className="scene-cta">
              <AuthCta variant="hero" />
            </div>
          </div>
          <p className="scene-trust">
            <span>Free to start</span><span>No card</span><span>No SDK</span>
            <a href="#demo">Try the live demo ↓</a>
          </p>
        </HeroScene>

        {/* ---------- facts ---------- */}
        <section className="lp-strip" aria-label="At a glance">
          <div className="lp-wrap lp-strip-inner">
            {STRIP.map((x, i) => (
              <Reveal key={x.big} className="lp-strip-item" delay={i * 80}>
                <span className="lp-strip-big">{x.big}</span>
                <span className="lp-strip-small">{x.small}</span>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ---------- live demo ---------- */}
        <section id="demo" className="lp-section lp-demo">
          <div className="lp-wrap">
            <Reveal className="lp-head">
              <p className="lp-kicker">Try it</p>
              <h2 className="lp-h2">Go on, <em>break something.</em></h2>
              <p className="lp-sub">
                This is HookFlow, sped up. Send a few events, then take an endpoint down and watch what happens to
                them. Bring it back, or replay what failed.
              </p>
            </Reveal>
            <Reveal delay={120}>
              <Playground />
            </Reveal>
          </div>
        </section>

        {/* ---------- features ---------- */}
        <section id="product" className="lp-section lp-features">
          <div className="lp-wrap">
            <Reveal className="lp-head">
              <p className="lp-kicker">What you get</p>
              <h2 className="lp-h2">Everything the retry queue <em>was going to need.</em></h2>
            </Reveal>
            <div className="bento">
              <Reveal className="bento-card bento-wide">
                <div className="bento-text">
                  <h3>Retries that back off</h3>
                  <p>Timeouts and 5xx answers are retried on an exponential schedule, or one you set per endpoint.
                    A wrong URL doesn&apos;t burn attempts, and retry times survive restarts.</p>
                </div>
                <div className="viz-retry" aria-hidden>
                  {["now", "+30s", "+2m", "+8m", "+32m"].map((t, i) => (
                    <div key={t} className={`viz-retry-step${i === 4 ? " ok" : ""}`} style={{ animationDelay: `${i * 0.35}s` }}>
                      <span className="viz-retry-dot" />
                      <span className="viz-retry-code">{i === 4 ? "200" : "503"}</span>
                      <span className="viz-retry-time">{t}</span>
                    </div>
                  ))}
                </div>
              </Reveal>
              <Reveal className="bento-card" delay={80}>
                <div className="bento-text">
                  <h3>Signed, every time</h3>
                  <p>HMAC-SHA256 over the timestamp and body. Rotate secrets with zero downtime.</p>
                </div>
                <pre className="viz-sig" aria-hidden>{`POST /hooks HTTP/1.1
HookFlow-Event-Id: evt_01JD8…
HookFlow-Timestamp: 1793612400
HookFlow-Signature: `}<mark>v1=9f3c51…e07a</mark></pre>
              </Reveal>
              <Reveal className="bento-card">
                <div className="bento-text">
                  <h3>Replay in one click</h3>
                  <p>One delivery, every failure of an event, or everything that failed overnight.</p>
                </div>
                <div className="viz-replay" aria-hidden>
                  <div className="viz-replay-row bad"><b>503</b> Attempt 3 · billing</div>
                  <div className="viz-replay-btn">↻ Replay 12 failed deliveries</div>
                  <div className="viz-replay-row ok"><b>200</b> Delivered · 84 ms</div>
                </div>
              </Reveal>
              <Reveal className="bento-card" delay={80}>
                <div className="bento-text">
                  <h3>Health at a glance</h3>
                  <p>Success rate and response times for every endpoint over the last 24 hours.</p>
                </div>
                <div className="viz-bars" aria-hidden>
                  {[62, 70, 66, 80, 74, 88, 30, 18, 52, 84, 90, 86, 92, 95, 89, 96].map((h, i) => (
                    <span key={i} className={h < 40 ? "low" : ""} style={{ height: `${h}%`, animationDelay: `${i * 40}ms` }} />
                  ))}
                </div>
              </Reveal>
              <Reveal className="bento-card" delay={160}>
                <div className="bento-text">
                  <h3>Built for teams</h3>
                  <p>Roles for admins, developers and viewers. Scoped API keys. An audit log of who did what.</p>
                </div>
                <ul className="viz-team" aria-hidden>
                  <li><span className="av">AK</span>Ana K.<em>Owner</em></li>
                  <li><span className="av">RM</span>Ravi M.<em>Developer</em></li>
                  <li><span className="av">JS</span>Jo S.<em>Viewer</em></li>
                </ul>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ---------- steps ---------- */}
        <section className="lp-section lp-steps-section">
          <div className="lp-wrap">
            <Reveal className="lp-head">
              <p className="lp-kicker">Get started</p>
              <h2 className="lp-h2">Live in <em>three steps.</em></h2>
            </Reveal>
            <ol className="lp-steps">
              {STEPS.map((st, i) => (
                <Reveal as="li" key={st.title} className="lp-step" delay={i * 100}>
                  <span className="lp-step-num">{i + 1}</span>
                  <h3>{st.title}</h3>
                  <p>{st.body}</p>
                  {st.ui}
                </Reveal>
              ))}
            </ol>
          </div>
        </section>

        {/* ---------- developers ---------- */}
        <section id="developers" className="lp-section lp-dev">
          <div className="lp-wrap lp-dev-grid">
            <Reveal>
              <p className="lp-kicker">Developers</p>
              <h2 className="lp-h2 lp-h2-left">One request.<br /><em>That&apos;s the integration.</em></h2>
              <p className="lp-dev-lead">No SDK, any language. Add an endpoint, send events with an API key, and verify
                the signature in your receiver.</p>
              <Link href="/platform" className="lp-textlink">
                See how delivery works <IconArrow size={15} />
              </Link>
            </Reveal>
            <Reveal delay={100}>
              <CodeTabs samples={SAMPLES} />
            </Reveal>
          </div>
        </section>

        {/* ---------- FAQ ---------- */}
        <section id="faq" className="lp-section lp-faq-section">
          <div className="lp-wrap lp-faq-grid">
            <Reveal>
              <p className="lp-kicker">Questions</p>
              <h2 className="lp-h2 lp-h2-left">Good to <em>know.</em></h2>
            </Reveal>
            <Reveal className="lp-faq" delay={100}>
              {FAQ.map((f) => (
                <details key={f.q}>
                  <summary>{f.q}</summary>
                  <p>{f.a}</p>
                </details>
              ))}
            </Reveal>
          </div>
        </section>

        {/* ---------- final ---------- */}
        <section className="lp-wrap">
          <div className="lp-final ink">
            <img className="lp-final-img" src="/landing/ridges-1600.jpg" alt="" loading="lazy" decoding="async" />
            <h2>
              Ship the feature.
              <br />
              <em>Not the retry queue.</em>
            </h2>
            <div className="lp-final-cta">
              <AuthCta variant="final" />
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
