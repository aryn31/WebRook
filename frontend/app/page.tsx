import type { Metadata } from "next";
import { API_PUBLIC_URL } from "@/lib/api";
import { DOCS_URL, SiteFooter, SiteHeader } from "@/components/SiteChrome";
import { AuthCta } from "@/components/AuthCta";
import { CodeTabs } from "@/components/CodeTabs";
import { HeroScene } from "@/components/HeroScene";
import { IconArrow } from "@/components/Icons";

export const metadata: Metadata = {
  title: { absolute: "HookFlow — webhooks that arrive" },
  description:
    "Send an event to HookFlow once. It delivers it to every subscribed endpoint, signs it, retries failures and records every attempt.",
};

const DOCS = DOCS_URL;

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

const POINTS = [
  {
    title: "Retries that back off",
    body: "Timeouts and 5xx responses are retried on an exponential schedule. Retry times survive restarts.",
  },
  {
    title: "Signed requests",
    body: "Every request carries an HMAC-SHA256 signature, with zero-downtime secret rotation.",
  },
  {
    title: "Every attempt, replayable",
    body: "See each attempt's status, response and timing. Replay anything in one click.",
  },
];

export default function LandingPage() {

  return (
    <div className="lp">
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
        </HeroScene>

        {/* ---------- product ---------- */}
        <section id="product" className="lp-section lp-points-section">
          <div className="lp-wrap">
            <div className="lp-points">
              {POINTS.map((p, i) => (
                <article key={p.title} className="lp-point">
                  <span className="lp-row-num">0{i + 1}</span>
                  <h3>{p.title}</h3>
                  <p>{p.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- developers ---------- */}
        <section id="developers" className="lp-section lp-dev">
          <div className="lp-wrap lp-dev-grid">
            <div>
              <p className="lp-kicker">Developers</p>
              <h2 className="lp-h2 lp-h2-left">One request.<br /><em>That&apos;s the integration.</em></h2>
              <p className="lp-dev-lead">No SDK, any language. Add an endpoint, send events with an API key, and verify
                the signature in your receiver.</p>
              <a href={DOCS} target="_blank" rel="noreferrer" className="lp-textlink">
                Read the API reference <IconArrow size={15} />
              </a>
            </div>
            <CodeTabs samples={SAMPLES} />
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
