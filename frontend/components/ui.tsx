"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, describeDetails, errorMessage, type DeliveryCounts, type DeliveryStatus } from "@/lib/api";
import { countsEntries, formatLocal, formatUtc, relative, STATUS_LABEL } from "@/lib/format";

export function StatusPill({ status, count }: { status: DeliveryStatus; count?: number }) {
  return (
    <span className={`pill pill-${status}`}>
      <span className="pill-dot" aria-hidden />
      {count != null ? `${count} ${STATUS_LABEL[status].toLowerCase()}` : STATUS_LABEL[status]}
    </span>
  );
}

export function CountsPills({ counts }: { counts: DeliveryCounts }) {
  const entries = countsEntries(counts);
  if (counts.total === 0 || entries.length === 0) return <span className="muted small">No deliveries</span>;
  return (
    <span className="pill-row">
      {entries.map(([s, n]) => (
        <StatusPill key={s} status={s} count={n} />
      ))}
    </span>
  );
}

/** Local time, UTC on hover. */
export function Time({ iso, withRelative }: { iso: string | null | undefined; withRelative?: boolean }) {
  if (!iso) return <span className="muted">—</span>;
  return (
    <time dateTime={iso} title={formatUtc(iso)} className="nowrap">
      {formatLocal(iso)}
      {withRelative && <span className="muted"> · {relative(iso)}</span>}
    </time>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("error");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 1800);
  }
  return (
    <button type="button" className="btn btn-sm" onClick={copy}>
      {state === "copied" ? "Copied ✓" : state === "error" ? "Select & copy manually" : label}
    </button>
  );
}

/** A button that asks for inline confirmation instead of window.confirm. */
export function ConfirmButton({
  label,
  confirmLabel = "Yes, continue",
  prompt = "Are you sure?",
  onConfirm,
  danger = true,
  small,
  disabled,
}: {
  label: string;
  confirmLabel?: string;
  prompt?: ReactNode;
  onConfirm: () => Promise<void> | void;
  danger?: boolean;
  small?: boolean;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const sz = small ? " btn-sm" : "";
  if (!asking) {
    return (
      <button type="button" className={`btn${danger ? " btn-danger-ghost" : ""}${sz}`} disabled={disabled} onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="confirm">
      <span className="confirm-prompt">{prompt}</span>
      <button
        type="button"
        className={`btn${danger ? " btn-danger" : " btn-primary"}${sz}`}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setAsking(false);
          }
        }}
      >
        {busy ? "Working…" : confirmLabel}
      </button>
      <button type="button" className={`btn btn-ghost${sz}`} disabled={busy} onClick={() => setAsking(false)}>
        Cancel
      </button>
    </span>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const details = error instanceof ApiError ? describeDetails(error.details) : [];
  return (
    <div className="alert alert-error" role="alert">
      <div>
        <strong>{errorMessage(error)}</strong>
        {details.length > 0 && (
          <ul className="alert-details">
            {details.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        )}
      </div>
      {onRetry && (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden /> {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function SecretBox({
  value,
  title,
  warning,
}: {
  value: string;
  title: string;
  warning?: ReactNode;
}) {
  return (
    <div className="secret-box">
      <div className="secret-title">{title}</div>
      <div className="secret-row">
        <code className="mono secret-value">{value}</code>
        <CopyButton text={value} />
      </div>
      {warning && <div className="secret-warning">⚠ {warning}</div>}
    </div>
  );
}

export function CodeBlock({ code }: { code: string }) {
  return (
    <div className="codeblock">
      <div className="codeblock-copy">
        <CopyButton text={code} />
      </div>
      <pre className="mono">{code}</pre>
    </div>
  );
}
