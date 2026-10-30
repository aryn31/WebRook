"use client";

import { MAX_ATTEMPTS_MAX, MAX_ATTEMPTS_MIN } from "@/lib/api";

/** Validation message for the raw text of the input, or null when it's a valid 1–10 integer. */
export function maxAttemptsError(raw: string): string | null {
  const n = Number(raw);
  if (raw.trim() === "" || !Number.isInteger(n) || n < MAX_ATTEMPTS_MIN || n > MAX_ATTEMPTS_MAX) {
    return `Max attempts must be a whole number from ${MAX_ATTEMPTS_MIN} to ${MAX_ATTEMPTS_MAX}.`;
  }
  return null;
}

/** Number input for an endpoint's max_attempts. Kept as text so the user can clear and retype. */
export function MaxAttemptsInput({ value, onChange, editing }: { value: string; onChange: (v: string) => void; editing?: boolean }) {
  const err = value.trim() !== "" ? maxAttemptsError(value) : null;
  return (
    <label className="field field-narrow">
      <span className="field-label">Max attempts</span>
      <input
        className="input"
        type="number"
        inputMode="numeric"
        min={MAX_ATTEMPTS_MIN}
        max={MAX_ATTEMPTS_MAX}
        step={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
      />
      <span className={`field-hint${err ? " text-failed" : ""}`}>
        {err ??
          `Attempts per delivery, including the first (${MAX_ATTEMPTS_MIN}–${MAX_ATTEMPTS_MAX}).${
            editing ? " Changes apply to new deliveries only." : ""
          }`}
      </span>
    </label>
  );
}
