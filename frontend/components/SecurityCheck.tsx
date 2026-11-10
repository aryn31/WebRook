"use client";

import { useState } from "react";
import { api, type Endpoint, type SecurityCheck, type SecurityVerdict } from "@/lib/api";
import { relative } from "@/lib/format";
import { CodeTabs } from "./CodeTabs";
import { ErrorBox } from "./ui";

const VERDICT: Record<SecurityVerdict, { label: string; badge: string }> = {
  pass: { label: "Signature verified", badge: "Verified" },
  partial: { label: "Partly protected", badge: "Partly verified" },
  fail: { label: "Not verifying signatures", badge: "Not verifying" },
  inconclusive: { label: "Couldn't tell", badge: "Check inconclusive" },
};

const PROBES: { name: string; label: string; expected: "accept" | "reject" }[] = [
  { name: "valid", label: "Correctly signed request", expected: "accept" },
  { name: "wrong_signature", label: "Signed with the wrong secret", expected: "reject" },
  { name: "tampered_body", label: "Body changed after signing", expected: "reject" },
  { name: "old_timestamp", label: "Correct signature, but an hour old", expected: "reject" },
  { name: "missing_signature", label: "No signature header", expected: "reject" },
];

const FIX = [
  {
    label: "Standard Webhooks",
    code: `// npm install standardwebhooks   (pip install standardwebhooks, go get …, gem install … are similar)
import { Webhook } from "standardwebhooks";

const wh = new Webhook(process.env.HOOKFLOW_WEBHOOK_SECRET); // the whsec_… secret

// Use the raw request body, exactly as received.
try {
  const event = wh.verify(rawBody, {
    "webhook-id": req.headers["webhook-id"],
    "webhook-timestamp": req.headers["webhook-timestamp"],
    "webhook-signature": req.headers["webhook-signature"],
  }); // also rejects requests older than 5 minutes
  handle(event);
  res.sendStatus(204);
} catch {
  res.sendStatus(400);
}`,
  },
  {
    label: "Node.js",
    code: `import { verify } from "hookflow"; // or check by hand, below

// Express: read the raw body for this route
app.post("/webhooks", express.raw({ type: "application/json" }), (req, res) => {
  try {
    const event = verify(req.body, req.headers, process.env.HOOKFLOW_WEBHOOK_SECRET);
    handle(event);
    res.sendStatus(204);
  } catch {
    res.sendStatus(400); // wrong or missing signature, or too old
  }
});

// By hand: HMAC-SHA256 of \`\${timestamp}.\${rawBody}\` with your secret, compared in constant time,
// and reject timestamps more than 5 minutes from now.`,
  },
  {
    label: "Python",
    code: `import hashlib, hmac, os, time

SECRET = os.environ["HOOKFLOW_WEBHOOK_SECRET"].encode()

def is_genuine(raw_body: bytes, headers) -> bool:
    ts = headers.get("HookFlow-Timestamp", "")
    sig = headers.get("HookFlow-Signature", "")
    if not ts or not sig or abs(time.time() - int(ts)) > 300:
        return False
    expected = "v1=" + hmac.new(SECRET, f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s.strip()) for s in sig.split(","))

# Answer 400 when is_genuine(...) is False, before doing anything with the event.`,
  },
];

/** Small badge for lists and headers. Nothing when the check was never run. */
export function SecurityBadge({ check }: { check: SecurityCheck | null }) {
  if (!check) return null;
  return (
    <span className={`sec-badge sec-${check.verdict}`} title={check.summary}>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6l-7-3Z" />
        {check.verdict === "pass" && <path d="m9 12 2.2 2.2L15.5 10" />}
        {check.verdict === "fail" && <path d="M12 8.5v4M12 15.5h.01" />}
      </svg>
      {VERDICT[check.verdict].badge}
    </span>
  );
}

export function SecurityCheckCard({ endpoint, canRun, onChecked, runCheck }: {
  endpoint: Endpoint; canRun: boolean; onChecked: (e: Endpoint) => void;
  /** How to run it; defaults to the dashboard API. The customer portal passes its own. */
  runCheck?: (id: string) => Promise<Endpoint>;
}) {
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const check = endpoint.security_check;

  async function run() {
    setRunning(true);
    setErr(null);
    try {
      onChecked(await (runCheck ?? api.runSecurityCheck)(endpoint.id));
    } catch (e) {
      setErr(e);
    } finally {
      setRunning(false);
    }
  }

  const rows = PROBES.map((p) => ({ ...p, result: running ? undefined : check?.probes.find((r) => r.name === p.name) }));
  const anyServerError = !running && check?.probes.some((p) => p.server_error);

  return (
    <section className={`card sec-card${check && !running ? ` sec-card-${check.verdict}` : ""}`}>
      <div className="card-head">
        <h2>Signature check</h2>
        {check && !running && <span className="muted small">Last run {relative(check.checked_at)}</span>}
      </div>
      <p className="muted small sec-intro">
        Makes sure your endpoint only trusts requests that HookFlow signed. We send it 5 test requests (event type{" "}
        <code className="mono">hookflow.security_check</code>): one genuine, four forged. A safe endpoint accepts the
        first and rejects the rest.
      </p>

      {check && !running && (
        <div className={`sec-verdict sec-${check.verdict}`}>
          <SecurityBadge check={check} />
          <div>
            <div className="sec-verdict-title">{VERDICT[check.verdict].label}</div>
            <div className="sec-verdict-body">{check.summary}</div>
          </div>
        </div>
      )}

      {(running || check) && (
        <ul className="sec-probes">
          {rows.map((r) => {
            const got = r.result
              ? r.result.status_code != null ? `HTTP ${r.result.status_code}` : r.result.error ?? "No answer"
              : "";
            const state = !r.result ? "running" : r.result.ok ? "ok" : "bad";
            return (
              <li key={r.name} className={`sec-probe sec-probe-${state}`}>
                <span className="sec-probe-mark" aria-hidden>{state === "running" ? "" : state === "ok" ? "✓" : "✗"}</span>
                <span className="sec-probe-label">{r.label}</span>
                <span className="sec-probe-expect">Should {r.expected}</span>
                <span className="sec-probe-got mono">
                  {state === "running" ? "Sending…" : `${r.result!.accepted ? "Accepted" : "Rejected"} · ${got}`}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {anyServerError && (
        <p className="sec-note">
          Your endpoint rejected forged requests with a 5xx error. That works, but a 400 or 401 is better: senders
          treat 5xx as &quot;try again later&quot;.
        </p>
      )}

      {check && !running && (check.verdict === "fail" || check.verdict === "partial") && (
        <div className="sec-fix">
          <div className="sec-fix-title">How to fix it</div>
          <CodeTabs samples={FIX} />
        </div>
      )}

      <ErrorBox error={err} />
      {canRun && (
        <div className="sec-actions">
          <button type="button" className={`btn${check ? "" : " btn-primary"}`} onClick={run} disabled={running}>
            {running ? "Checking…" : check ? "Run again" : "Check my endpoint"}
          </button>
          {!check && !running && <span className="muted small">Takes a few seconds.</span>}
        </div>
      )}
    </section>
  );
}
