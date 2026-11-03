"use client";

import { RETRY_DELAY_MAX_SECONDS, RETRY_SCHEDULE_MAX_ITEMS } from "@/lib/api";

const UNITS: Record<string, number> = { s: 1, m: 60, h: 3600 };

/** "30s", "5m", "2h" or a plain number of seconds. */
export function formatDelay(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

export function scheduleToText(schedule: number[] | null): string {
  return schedule ? schedule.map(formatDelay).join(", ") : "";
}

/** Parse "30s, 5m, 1h" into seconds. Returns an error message instead when it isn't valid. */
export function parseSchedule(text: string): { value: number[] } | { error: string } {
  const parts = text.split(/[,\s]+/).filter(Boolean);
  if (parts.length === 0) return { error: "Enter at least one delay, e.g. 30s, 5m, 1h." };
  if (parts.length > RETRY_SCHEDULE_MAX_ITEMS) {
    return { error: `At most ${RETRY_SCHEDULE_MAX_ITEMS} delays. The last one repeats for later retries.` };
  }
  const out: number[] = [];
  for (const p of parts) {
    const m = /^(\d+)\s*([smh]?)$/i.exec(p);
    if (!m) return { error: `“${p}” isn't a delay. Use a number with s, m or h, e.g. 90s or 10m.` };
    const seconds = Number(m[1]) * UNITS[(m[2] || "s").toLowerCase()];
    if (seconds < 1 || seconds > RETRY_DELAY_MAX_SECONDS) return { error: "Each delay must be from 1s to 24h." };
    out.push(seconds);
  }
  return { value: out };
}

/** Plain-language description of when retries happen, for up to `maxAttempts` attempts. */
export function describeSchedule(schedule: number[], maxAttempts: number): string {
  const retries = Math.max(maxAttempts - 1, 0);
  if (retries === 0) return "No retries: max attempts is 1.";
  const shown = Array.from({ length: retries }, (_, i) => formatDelay(schedule[Math.min(i, schedule.length - 1)]));
  return `Waits ${shown.join(" → ")} between attempts (±10%). A longer Retry-After from your server wins.`;
}

export type ScheduleDraft = { custom: boolean; text: string };

export function scheduleDraftError(d: ScheduleDraft): string | null {
  if (!d.custom) return null;
  const r = parseSchedule(d.text);
  return "error" in r ? r.error : null;
}

export function scheduleDraftValue(d: ScheduleDraft): number[] | null {
  if (!d.custom) return null;
  const r = parseSchedule(d.text);
  return "value" in r ? r.value : null;
}

/** Choose between the default exponential backoff and a custom list of delays. */
export function RetryScheduleInput({
  value,
  onChange,
  maxAttempts,
}: {
  value: ScheduleDraft;
  onChange: (v: ScheduleDraft) => void;
  maxAttempts: number;
}) {
  const parsed = value.custom ? parseSchedule(value.text) : null;
  return (
    <div className="field">
      <span className="field-label">Retry timing</span>
      <label className="checkbox">
        <input type="radio" name="retry-mode" checked={!value.custom} onChange={() => onChange({ ...value, custom: false })} />
        <span>Default backoff: about 30s, 2m, 8m, 32m, then up to 6h</span>
      </label>
      <label className="checkbox">
        <input
          type="radio"
          name="retry-mode"
          checked={value.custom}
          onChange={() => onChange({ custom: true, text: value.text || "30s, 5m, 30m" })}
        />
        <span>Custom schedule</span>
      </label>
      {value.custom && (
        <>
          <input
            className="input mono"
            value={value.text}
            onChange={(e) => onChange({ ...value, text: e.target.value })}
            placeholder="30s, 5m, 30m"
            aria-label="Retry delays"
          />
          <span className={`field-hint${parsed && "error" in parsed ? " text-failed" : ""}`}>
            {parsed && "error" in parsed
              ? parsed.error
              : parsed && Number.isFinite(maxAttempts)
                ? describeSchedule(parsed.value, maxAttempts)
                : null}
          </span>
        </>
      )}
    </div>
  );
}
