"use client";

import { useState } from "react";
import { api, type BulkReplayFilters, type BulkReplayResult } from "@/lib/api";
import { useMe } from "./MeContext";
import { ErrorBox } from "./ui";

const BATCH = 500;

/**
 * "Replay failed deliveries" for a set of filters. Checks first (a dry run) and asks before replaying.
 * Replays up to 500 per click; when there are more, offers the next batch.
 */
export function BulkReplay({
  filters,
  label = "Replay failed deliveries",
  onDone,
}: {
  filters: BulkReplayFilters;
  label?: string;
  onDone?: () => void;
}) {
  const { can } = useMe();
  const [check, setCheck] = useState<BulkReplayResult | null>(null);
  const [done, setDone] = useState<BulkReplayResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  if (!can("deliveries:replay")) return null;

  async function preview() {
    setBusy(true);
    setErr(null);
    setDone(null);
    try {
      setCheck(await api.bulkReplay({ ...filters, limit: BATCH }, true));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.bulkReplay({ ...filters, limit: BATCH });
      setDone(res);
      setCheck(null);
      onDone?.();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  const count = check?.replayed.length ?? 0;

  return (
    <div className="stack">
      <div className="bulk-replay">
        {!check && (
          <button type="button" className="btn" onClick={preview} disabled={busy}>
            {busy ? "Checking…" : done?.has_more ? "Replay the next batch" : label}
          </button>
        )}
        {check && count === 0 && (
          <>
            <span className="bulk-replay-result">Nothing to replay: no failed deliveries match.</span>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setCheck(null)}>
              OK
            </button>
          </>
        )}
        {check && count > 0 && (
          <>
            <span className="bulk-replay-result">
              Replay <strong>{count}</strong> failed deliver{count === 1 ? "y" : "ies"}
              {check.has_more ? ` (the oldest ${count}; more remain)` : ""}? Each is sent again with a fresh set of
              attempts.
            </span>
            <button type="button" className="btn btn-primary" onClick={run} disabled={busy}>
              {busy ? "Replaying…" : `Replay ${count}`}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setCheck(null)} disabled={busy}>
              Cancel
            </button>
          </>
        )}
        {done && !check && (
          <span className="bulk-replay-result">
            Replayed {done.replayed.length}
            {done.skipped.length > 0 ? `, skipped ${done.skipped.length}` : ""}.
            {done.has_more ? " More failed deliveries remain." : ""}
          </span>
        )}
      </div>
      <ErrorBox error={err} />
    </div>
  );
}
