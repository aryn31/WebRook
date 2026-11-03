"use client";

import { useState, type KeyboardEvent } from "react";

export const EVENT_TYPE_RE = /^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$/;

export function validateEventType(t: string): string | null {
  if (t.length === 0) return "Event type is required.";
  if (t.length > 100) return "Event type must be at most 100 characters.";
  if (!EVENT_TYPE_RE.test(t)) return `“${t}” is not a valid event type. Use letters, digits, _ or - in dot-separated parts, e.g. order.created.`;
  return null;
}

/** A subscription: an event type, or a pattern like "order.*" (every type starting with "order."). */
export function validateSubscription(t: string): string | null {
  if (t.endsWith(".*")) {
    const prefix = t.slice(0, -2);
    if (t.length <= 100 && EVENT_TYPE_RE.test(prefix)) return null;
    return `“${t}” is not a valid pattern. Patterns end in .* after a prefix, e.g. order.*.`;
  }
  if (t.includes("*")) return `“${t}” is not valid. * only works at the end, as in order.*.`;
  return validateEventType(t);
}

/** Chips input for event types; "*" (all events) is a separate toggle. */
export function EventTypesInput({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const all = value.includes("*");

  function addFrom(text: string) {
    const parts = text
      .split(/[,\s]+/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    if (parts.includes("*")) {
      onChange(["*"]);
      setDraft("");
      setErr(null);
      return;
    }
    for (const p of parts) {
      const e = validateSubscription(p);
      if (e) {
        setErr(e);
        return;
      }
    }
    const next = [...value.filter((v) => v !== "*")];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    onChange(next);
    setDraft("");
    setErr(null);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addFrom(draft);
    } else if (e.key === "Backspace" && draft === "" && value.length > 0 && !all) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div className="field">
      <span className="field-label">Event types</span>
      <label className="checkbox">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.target.checked ? ["*"] : [])} />
        <span>
          All events <code className="mono">*</code>
        </span>
      </label>
      {!all && (
        <>
          <div className="chips-input">
            {value.map((t) => (
              <span key={t} className="chip mono">
                {t}
                <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((v) => v !== t))}>
                  ×
                </button>
              </span>
            ))}
            <input
              className="chips-entry mono"
              placeholder={value.length ? "Add another…" : "order.created, invoice.*"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              onBlur={() => draft.trim() && addFrom(draft)}
            />
          </div>
          <span className={`field-hint${err ? " text-failed" : ""}`}>
            {err ?? (
              <>
                Press Enter or comma to add. Use a pattern like <code className="mono">order.*</code> to match every
                type that starts with <code className="mono">order.</code>
              </>
            )}
          </span>
        </>
      )}
    </div>
  );
}

export function EventTypeList({ types }: { types: string[] }) {
  if (types.includes("*")) return <span className="chip chip-static">All events</span>;
  if (types.length === 0) return <span className="muted small">None</span>;
  return (
    <span className="pill-row">
      {types.map((t) => (
        <span key={t} className="chip chip-static mono" title={t.endsWith(".*") ? `Every event type starting with ${t.slice(0, -1)}` : undefined}>
          {t}
        </span>
      ))}
    </span>
  );
}
