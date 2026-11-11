"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type ProofLink, type ProofLinkCreated } from "@/lib/api";
import { relative } from "@/lib/format";
import { ConfirmButton, CopyButton, ErrorBox } from "./ui";
import { useMe } from "./MeContext";

const EXPIRY_OPTIONS = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "1 year" },
];

function linkState(p: ProofLink): { label: string; tone: string } {
  if (p.revoked_at) return { label: "Turned off", tone: "off" };
  if (!p.active) return { label: "Expired", tone: "off" };
  return { label: "Active", tone: "on" };
}

/** "Share proof of delivery": create a public proof page for one delivery, and list or turn off existing ones. */
export function ProofLinks({ deliveryId }: { deliveryId: string }) {
  const { can } = useMe();
  const canShare = can("deliveries:replay");
  const [links, setLinks] = useState<ProofLink[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<ProofLinkCreated | null>(null);

  const load = useCallback(async () => {
    try {
      setLinks((await api.listProofs(deliveryId)).data);
    } catch (e) {
      setError(e);
    }
  }, [deliveryId]);

  useEffect(() => void load(), [load]);

  async function revoke(p: ProofLink) {
    setError(null);
    try {
      await api.revokeProof(deliveryId, p.id);
      if (created?.id === p.id) setCreated(null);
      await load();
    } catch (e) {
      setError(e);
    }
  }

  const active = links?.filter((p) => p.active) ?? [];
  if (!canShare && active.length === 0) return null;

  return (
    <div className="proof-panel">
      <div className="proof-head">
        <div>
          <div className="proof-title">Proof of delivery</div>
          <div className="muted small">
            A page you can send to anyone to show what happened to this delivery, with a signed receipt they can check.
          </div>
        </div>
        {canShare && !open && !created && (
          <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
            Share proof
          </button>
        )}
      </div>

      <ErrorBox error={error} />

      {open && !created && (
        <CreateProof
          deliveryId={deliveryId}
          onCancel={() => setOpen(false)}
          onCreated={(p) => {
            setCreated(p);
            setOpen(false);
            void load();
          }}
        />
      )}

      {created && (
        <div className="proof-created">
          <div className="small">
            <strong>Link created.</strong> Copy it now: for security, it can&apos;t be shown again.
          </div>
          <div className="secret-row">
            <code className="mono secret-value">{created.url}</code>
            <CopyButton text={created.url} />
            <a className="btn btn-sm btn-ghost" href={created.url} target="_blank" rel="noreferrer">
              Open
            </a>
          </div>
          <button type="button" className="btn btn-sm btn-ghost proof-done" onClick={() => setCreated(null)}>
            Done
          </button>
        </div>
      )}

      {links && links.length > 0 && (
        <ul className="proof-list">
          {links.map((p) => {
            const st = linkState(p);
            return (
              <li key={p.id} className="proof-row">
                <span className={`proof-state proof-state-${st.tone}`}>{st.label}</span>
                <span className="small">
                  {p.created_by_email ? `By ${p.created_by_email}` : "Created"} {relative(p.created_at)}
                  {p.include_body && <span className="muted"> · shows body</span>}
                </span>
                <span className="muted small">
                  {p.view_count} view{p.view_count === 1 ? "" : "s"}
                  {p.active && <> · expires {relative(p.expires_at)}</>}
                </span>
                {canShare && p.active && (
                  <ConfirmButton
                    small
                    label="Turn off"
                    prompt="Turn off this link?"
                    confirmLabel="Turn off"
                    onConfirm={() => revoke(p)}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function CreateProof({
  deliveryId,
  onCancel,
  onCreated,
}: {
  deliveryId: string;
  onCancel: () => void;
  onCreated: (p: ProofLinkCreated) => void;
}) {
  const [sender, setSender] = useState("");
  const [days, setDays] = useState(30);
  const [includeBody, setIncludeBody] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createProof(deliveryId, { include_body: includeBody, expires_in_days: days, sender_name: sender || null }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="proof-form" onSubmit={submit}>
      <div className="proof-form-grid">
        <label className="field">
          <span className="field-label">Your name on the page (optional)</span>
          <input className="input" maxLength={100} placeholder="e.g. Northwind" value={sender} onChange={(e) => setSender(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Link works for</span>
          <select className="input select" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {EXPIRY_OPTIONS.map((o) => (
              <option key={o.days} value={o.days}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="checkbox">
        <input type="checkbox" checked={includeBody} onChange={(e) => setIncludeBody(e.target.checked)} />
        <span>Show the event&apos;s body on the page</span>
      </label>
      <div className="field-hint">
        Off by default. The page always shows the body&apos;s fingerprint (SHA-256), which the receiver can match against
        their own logs without you sharing the data.
      </div>
      <ErrorBox error={error} />
      <div className="proof-actions">
        <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
          {busy ? "Creating…" : "Create link"}
        </button>
        <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
