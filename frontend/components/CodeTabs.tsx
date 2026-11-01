"use client";

import { useState } from "react";

export type CodeSample = { label: string; code: string };

export function CodeTabs({ samples }: { samples: CodeSample[] }) {
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(samples[active].code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked; the code is selectable */
    }
  }

  return (
    <div className="codetabs">
      <div className="codetabs-bar">
        <div role="tablist" aria-label="Language" className="codetabs-tabs">
          {samples.map((s, i) => (
            <button key={s.label} type="button" role="tab" aria-selected={i === active}
              className={i === active ? "active" : ""} onClick={() => setActive(i)}>
              {s.label}
            </button>
          ))}
        </div>
        <button type="button" className="codetabs-copy" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <pre className="codetabs-pre"><code>{samples[active].code}</code></pre>
    </div>
  );
}
