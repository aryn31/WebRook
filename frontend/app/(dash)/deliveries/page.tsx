"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api, type Delivery, type DeliveryStatus } from "@/lib/api";
import { STATUS_LABEL } from "@/lib/format";
import { BulkReplay } from "@/components/BulkReplay";
import { DeliveryTable } from "@/components/DeliveryTable";
import { Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";

type Tab = "all" | Exclude<DeliveryStatus, "processing">;
const TABS: Tab[] = ["all", "pending", "retrying", "delivered", "failed", "cancelled"];

function DeliveriesView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("status");
  const tab: Tab = raw && (TABS as string[]).includes(raw) ? (raw as Tab) : "all";
  const [items, setItems] = useState<Delivery[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async (t: Tab, after: string | null) => {
    setErr(null);
    if (after) setLoadingMore(true);
    else setItems(null);
    try {
      const res = await api.listDeliveries({
        limit: 25,
        cursor: after,
        status: t === "all" ? undefined : (t as DeliveryStatus),
      });
      setItems((prev) => (after ? [...(prev ?? []), ...res.data] : res.data));
      setCursor(res.next_cursor);
    } catch (e) {
      setErr(e);
    } finally {
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void load(tab, null);
  }, [tab, load]);

  function select(t: Tab) {
    router.replace(t === "all" ? pathname : `${pathname}?status=${t}`, { scroll: false });
  }

  const emptyText: Record<Tab, string> = {
    all: "No deliveries yet. Add an endpoint and send an event to see deliveries here.",
    pending: "Nothing waiting to be sent.",
    retrying: "No deliveries are being retried.",
    delivered: "No successful deliveries yet.",
    failed: "No failed deliveries. 🎉",
    cancelled: "No cancelled deliveries.",
  };

  return (
    <div className="page">
      <PageHeader title="Deliveries" sub="One delivery is one event going to one endpoint. Click a row for its attempt history." />

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`tab${tab === t ? " active" : ""}`}
            onClick={() => select(t)}
          >
            {t !== "all" && <span className={`pill-dot dot-${t}`} aria-hidden />}
            {t === "all" ? "All" : STATUS_LABEL[t]}
          </button>
        ))}
      </div>

      {tab === "failed" && items && items.length > 0 && (
        <section className="card">
          <BulkReplay filters={{}} label="Replay all failed deliveries" onDone={() => setTimeout(() => void load(tab, null), 800)} />
          <p className="muted small mt">
            Deliveries to disabled endpoints are left alone. To replay only some, use the button on an endpoint&apos;s
            page, or call <code className="mono">POST /v1/deliveries/replay</code> with filters.
          </p>
        </section>
      )}

      <section className="card card-flush">
        <ErrorBox error={err} onRetry={() => load(tab, null)} />
        {!items && !err && <Loading />}
        {items && items.length === 0 && <Empty title={emptyText[tab]} />}
        {items && items.length > 0 && <DeliveryTable deliveries={items} />}
        {cursor && (
          <div className="load-more">
            <button type="button" className="btn" disabled={loadingMore} onClick={() => load(tab, cursor)}>
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

export default function DeliveriesPage() {
  return (
    <Suspense fallback={<div className="page"><Loading /></div>}>
      <DeliveriesView />
    </Suspense>
  );
}
