"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage, type ProofView } from "@/lib/api";
import { formatDuration, formatUtc } from "@/lib/format";
import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { JsonView } from "@/components/JsonView";
import { CopyButton, Loading } from "@/components/ui";

const REASONS: Record<number, string> = {
  200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
  400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 408: "Request Timeout",
  409: "Conflict", 410: "Gone", 413: "Payload Too Large", 422: "Unprocessable Entity", 429: "Too Many Requests",
  500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout",
};

const VERDICT: Record<string, { title: string; tone: "ok" | "bad" | "wait" | "off" }> = {
  delivered: { title: "Delivered", tone: "ok" },
  failed: { title: "Not delivered", tone: "bad" },
  retrying: { title: "Still trying", tone: "wait" },
  pending: { title: "Waiting to send", tone: "wait" },
  processing: { title: "Sending now", tone: "wait" },
  cancelled: { title: "Cancelled", tone: "off" },
};

function code(status: number | null) {
  if (status == null) return "No response";
  return `${status} ${REASONS[status] ?? ""}`.trim();
}

function summary(p: ProofView): string {
  const who = p.sender_name ?? "The sender";
  const last = p.attempts[p.attempts.length - 1];
  const n = p.attempts.length;
  switch (p.status) {
    case "delivered": {
      const ok = [...p.attempts].reverse().find((a) => a.success);
      return `${who} sent this event and the receiving server accepted it${ok ? ` on attempt ${ok.attempt_number}` : ""}, answering ${code(ok?.response_status ?? null)}.`;
    }
    case "failed":
      return `${who} tried ${n} time${n === 1 ? "" : "s"}, and the receiving server never accepted it. The last answer was: ${last?.error ?? code(last?.response_status ?? null)}`;
    case "retrying":
      return `${who} has tried ${n} time${n === 1 ? "" : "s"} so far without success, and will try again automatically.`;
    case "cancelled":
      return `${who} cancelled this delivery before it succeeded.`;
    default:
      return `${who} hasn't finished sending this event yet.`;
  }
}

function VerdictIcon({ tone }: { tone: string }) {
  const path =
    tone === "ok" ? "M5 12.5l4.5 4.5L19 7.5" : tone === "bad" ? "M7 7l10 10M17 7L7 17" : tone === "wait" ? "M12 7v5l3 2" : "M7 12h10";
  return (
    <span className={`proof-icon proof-icon-${tone}`} aria-hidden>
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        {tone === "wait" && <circle cx="12" cy="12" r="8" />}
        <path d={path} />
      </svg>
    </span>
  );
}

type Check = { state: "idle" | "busy" | "valid" | "invalid" | "unsupported"; keyId?: string };

/** Checks the receipt's Ed25519 signature in the browser against HookFlow's published key. */
async function verifyReceipt(p: ProofView): Promise<Check> {
  const res = await fetch("/api/v1/proof/public-key");
  const key = (await res.json()) as { key_id: string; public_key: string };
  const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  let pub: CryptoKey;
  try {
    pub = await crypto.subtle.importKey("raw", bytes(key.public_key), { name: "Ed25519" }, false, ["verify"]);
  } catch {
    return { state: "unsupported" };
  }
  const ok =
    key.key_id === p.receipt.key_id &&
    (await crypto.subtle.verify({ name: "Ed25519" }, pub, bytes(p.receipt.signature), new TextEncoder().encode(p.receipt.payload)));
  return { state: ok ? "valid" : "invalid", keyId: key.key_id };
}

function download(p: ProofView) {
  const file = {
    ...p.receipt,
    public_key_url: `${window.location.origin}/api/v1/proof/public-key`,
    how_to_verify:
      "Verify `signature` (base64 Ed25519) over the UTF-8 bytes of `payload` with the public key at `public_key_url`. Then parse `payload` as JSON.",
  };
  const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `hookflow-receipt-${p.delivery_id}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function ProofPage({ token }: { token: string }) {
  const [proof, setProof] = useState<ProofView | null>(null);
  const [fatal, setFatal] = useState<{ title: string; text: string } | null>(null);
  const [check, setCheck] = useState<Check>({ state: "idle" });

  const load = useCallback(async () => {
    try {
      setProof(await api.viewProof(token));
    } catch (e) {
      const gone = e instanceof ApiError && e.status === 410;
      setFatal({ title: gone ? "Link no longer works" : "Proof not found", text: errorMessage(e) });
    }
  }, [token]);

  useEffect(() => void load(), [load]);

  async function runCheck() {
    if (!proof) return;
    setCheck({ state: "busy" });
    try {
      setCheck(await verifyReceipt(proof));
    } catch {
      setCheck({ state: "invalid" });
    }
  }

  const v = proof ? VERDICT[proof.status] ?? VERDICT.pending : null;

  return (
    <div className="portal proof-page">
      <header className="portal-top">
        <div className="portal-top-inner proof-top">
          <Brand />
          <ThemeToggle />
        </div>
      </header>

      <main className="portal-main proof-main">
        {fatal ? (
          <div className="portal-fatal">
            <h1>{fatal.title}</h1>
            <p className="muted">{fatal.text}</p>
          </div>
        ) : !proof || !v ? (
          <Loading label="Loading proof…" />
        ) : (
          <>
            <section className={`card proof-verdict proof-verdict-${v.tone}`}>
              <VerdictIcon tone={v.tone} />
              <div className="proof-verdict-text">
                <div className="proof-kicker">Proof of delivery{proof.sender_name ? ` from ${proof.sender_name}` : ""}</div>
                <h1>{v.title}</h1>
                <p>{summary(proof)}</p>
                <div className="proof-facts">
                  <span>
                    <span className="muted">Event</span> <code className="mono">{proof.event_type}</code>
                  </span>
                  <span>
                    <span className="muted">To</span> <code className="mono">{proof.endpoint_url}</code>
                  </span>
                  {proof.delivered_at && (
                    <span>
                      <span className="muted">Delivered</span> {formatUtc(proof.delivered_at)}
                    </span>
                  )}
                </div>
              </div>
            </section>

            <section className="card">
              <h2 className="proof-h2">Every attempt</h2>
              {proof.attempts.length === 0 ? (
                <p className="muted small">No attempts have finished yet.</p>
              ) : (
                <ol className="proof-timeline">
                  {proof.attempts.map((a) => (
                    <li key={a.attempt_number} className={a.success ? "ok" : "bad"}>
                      <span className="proof-dot" aria-hidden />
                      <div>
                        <div className="proof-attempt-line">
                          <strong>Attempt {a.attempt_number}</strong>
                          <span className={`code-badge ${a.success ? "ok" : "bad"}`}>{code(a.response_status)}</span>
                          <span className="muted small">{formatUtc(a.started_at)}</span>
                          {a.duration_ms != null && <span className="muted small">{formatDuration(a.duration_ms)}</span>}
                        </div>
                        {a.error && !a.success && <div className="muted small">{a.error}</div>}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section className="card">
              <h2 className="proof-h2">Check it against your logs</h2>
              <p className="muted small proof-lede">
                If you run the receiving server, you can confirm this matches a request you received.
              </p>
              <ol className="proof-steps">
                <li>
                  Find the request with the header <code className="mono">webhook-id</code> (or{" "}
                  <code className="mono">HookFlow-Event-Id</code>) set to:
                  <div className="proof-copy">
                    <code className="mono">{proof.event_id}</code>
                    <CopyButton text={proof.event_id} />
                  </div>
                </li>
                <li>
                  Hash its raw body with SHA-256, for example{" "}
                  <code className="mono">shasum -a 256 body.json</code>. It should equal:
                  <div className="proof-copy">
                    <code className="mono proof-hash">{proof.body_sha256}</code>
                    <CopyButton text={proof.body_sha256.replace(/^sha256:/, "")} />
                  </div>
                </li>
              </ol>
              <dl className="proof-dl">
                <dt>Delivery ID</dt>
                <dd className="mono">{proof.delivery_id}</dd>
                <dt>Event created</dt>
                <dd>{formatUtc(proof.event_created_at)}</dd>
                <dt>Page checked</dt>
                <dd>{formatUtc(proof.checked_at)}</dd>
              </dl>
            </section>

            {proof.body && (
              <section className="card">
                <h2 className="proof-h2">Body that was sent</h2>
                <JsonView text={(() => { try { return JSON.stringify(JSON.parse(proof.body), null, 2); } catch { return proof.body; } })()} />
              </section>
            )}

            <section className="card proof-receipt">
              <div>
                <h2 className="proof-h2">Signed receipt</h2>
                <p className="muted small proof-lede">
                  HookFlow signs these facts with its Ed25519 key, so a saved receipt can&apos;t be edited without it
                  showing. Anyone can check it, now or later.
                </p>
                {check.state === "valid" && (
                  <div className="alert alert-success small">Signature valid. Signed by HookFlow key {check.keyId}.</div>
                )}
                {check.state === "invalid" && (
                  <div className="alert alert-error small">The signature didn&apos;t match. Don&apos;t rely on this receipt.</div>
                )}
                {check.state === "unsupported" && (
                  <div className="alert small">
                    This browser can&apos;t check Ed25519 signatures. Download the receipt and check it with any Ed25519
                    library.
                  </div>
                )}
              </div>
              <div className="proof-actions">
                <button type="button" className="btn btn-sm btn-primary" onClick={runCheck} disabled={check.state === "busy"}>
                  {check.state === "busy" ? "Checking…" : "Verify signature"}
                </button>
                <button type="button" className="btn btn-sm" onClick={() => download(proof)}>
                  Download receipt
                </button>
              </div>
            </section>
          </>
        )}
      </main>

      <footer className="portal-foot">
        Proof by <a href="/" target="_blank" rel="noreferrer">HookFlow</a>, read live from its delivery records
        {proof && <> · link works until {formatUtc(proof.expires_at)}</>}
      </footer>
    </div>
  );
}
