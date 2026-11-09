"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, API_PUBLIC_URL, type Consumer } from "@/lib/api";
import { useMe } from "@/components/MeContext";
import { Avatar } from "@/components/Avatar";
import { CodeTabs } from "@/components/CodeTabs";
import { ConfirmButton, Empty, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";

const UID_RE = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,99}$/;

function HowItWorks() {
  const samples = [
    {
      label: "1. Add a consumer",
      code: `curl -X POST ${API_PUBLIC_URL}/v1/consumers \\
  -H "Authorization: Bearer $HOOKFLOW_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"uid": "ana-bakery", "name": "Ana\\u0027s Bakery"}'`,
    },
    {
      label: "2. Send their events",
      code: `curl -X POST ${API_PUBLIC_URL}/v1/events \\
  -H "Authorization: Bearer $HOOKFLOW_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"event_type": "order.created", "consumer": "ana-bakery",
       "data": {"order_id": "1042"}}'`,
    },
    {
      label: "3. Show their portal",
      code: `# On your server, when the customer opens "Webhooks" in your app:
curl -X POST ${API_PUBLIC_URL}/v1/consumers/ana-bakery/portal \\
  -H "Authorization: Bearer $HOOKFLOW_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"brand_name": "ShopCo"}'
# → {"url": "https://…/portal#token=hfp_…", "expires_at": "…"}

<!-- then in your page -->
<iframe src="{url}" style="width:100%;height:800px;border:0"></iframe>`,
    },
  ];
  return (
    <section className="card">
      <div className="card-head">
        <h2>How it works</h2>
        <span className="muted small">For SaaS apps that send webhooks to their own customers</span>
      </div>
      <p className="muted small cons-intro">
        A consumer is one of <em>your</em> customers. Give each one a portal (a page you embed in your app) where they
        add their own endpoints, see deliveries to them, replay failures and check their signature verification. Events
        sent with <code className="mono">consumer</code> go only to that consumer&apos;s endpoints. They never see your
        other customers or your own endpoints.
      </p>
      <CodeTabs samples={samples} />
    </section>
  );
}

export default function ConsumersPage() {
  const { can } = useMe();
  const canWrite = can("endpoints:write");
  const [items, setItems] = useState<Consumer[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [actionErr, setActionErr] = useState<unknown>(null);
  const [uid, setUid] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);

  const load = useCallback(async (after: string | null) => {
    setLoadErr(null);
    try {
      const page = await api.listConsumers({ limit: 50, cursor: after });
      setItems((prev) => (after ? [...(prev ?? []), ...page.data] : page.data));
      setCursor(page.next_cursor);
    } catch (e) {
      setLoadErr(e);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  const uidOk = UID_RE.test(uid.trim());

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!uidOk) return;
    setBusy(true);
    setActionErr(null);
    setNotice(null);
    try {
      const c = await api.createConsumer(uid.trim(), name.trim() || null);
      setItems((prev) => [c, ...(prev ?? [])]);
      setUid("");
      setName("");
      setNotice(`Added ${c.name ?? c.uid}. Send events with "consumer": "${c.uid}", and open their portal below.`);
    } catch (err) {
      setActionErr(err);
    } finally {
      setBusy(false);
    }
  }

  async function portal(c: Consumer, mode: "open" | "copy") {
    setOpening(c.id + mode);
    setActionErr(null);
    setNotice(null);
    // Open the tab first (inside the click), so pop-up blockers allow it.
    const tab = mode === "open" ? window.open("about:blank", "_blank") : null;
    try {
      const link = await api.createPortalLink(c.uid);
      if (tab) tab.location.href = link.url;
      else {
        await navigator.clipboard.writeText(link.url);
        setNotice(`Copied a portal link for ${c.name ?? c.uid}. It works for 60 minutes; anyone with it can manage their endpoints.`);
      }
    } catch (err) {
      tab?.close();
      setActionErr(err);
    } finally {
      setOpening(null);
    }
  }

  async function remove(c: Consumer) {
    setActionErr(null);
    try {
      await api.deleteConsumer(c.uid);
      setItems((prev) => (prev ?? []).filter((x) => x.id !== c.id));
      setNotice(`Deleted ${c.name ?? c.uid} and their endpoints.`);
    } catch (err) {
      setActionErr(err);
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Consumers"
        sub="Your own customers. Each one gets a portal to manage the webhooks you send them."
      />

      <HowItWorks />

      {canWrite && (
        <section className="card">
          <div className="card-head"><h2>Add a consumer</h2></div>
          <form onSubmit={create} className="cons-form">
            <label className="field">
              <span className="field-label">ID</span>
              <input className="input mono" placeholder="ana-bakery" value={uid} maxLength={100}
                onChange={(e) => setUid(e.target.value)} aria-invalid={(uid.length > 0 && !uidOk) || undefined} />
              <span className={`field-hint${uid.length > 0 && !uidOk ? " field-hint-error" : ""}`}>
                Your ID for them, e.g. their account ID. Letters, digits and . _ : @ -
              </span>
            </label>
            <label className="field">
              <span className="field-label">Name <span className="muted">(optional)</span></span>
              <input className="input" placeholder="Ana's Bakery" value={name} maxLength={200}
                onChange={(e) => setName(e.target.value)} />
              <span className="field-hint">Shown at the top of their portal.</span>
            </label>
            <button type="submit" className="btn btn-primary" disabled={busy || !uidOk}>
              {busy ? "Adding…" : "Add consumer"}
            </button>
          </form>
        </section>
      )}

      <ErrorBox error={actionErr} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <section className="card card-flush">
        <ErrorBox error={loadErr} onRetry={() => load(null)} />
        {!items && !loadErr && <Loading />}
        {items && items.length === 0 && (
          <Empty title="No consumers yet">
            Add one above, or with <code className="mono">POST /v1/consumers</code> from your server.
          </Empty>
        )}
        {items && items.length > 0 && (
          <ul className="cons-list">
            {items.map((c) => (
              <li key={c.id} className="cons-row">
                <Avatar email={c.uid + "@x"} size={34} />
                <div className="cons-main">
                  <div className="cons-name">{c.name ?? c.uid}</div>
                  <div className="cons-uid mono">{c.uid}</div>
                </div>
                <div className="cons-count">
                  <strong>{c.endpoint_count}</strong> endpoint{c.endpoint_count === 1 ? "" : "s"}
                </div>
                <div className="cons-date muted small">Added <Time iso={c.created_at} /></div>
                <div className="cons-actions">
                  {canWrite && (
                    <>
                      <button type="button" className="btn btn-sm btn-primary" disabled={opening !== null}
                        onClick={() => portal(c, "open")}>
                        {opening === c.id + "open" ? "Opening…" : "Open portal ↗"}
                      </button>
                      <button type="button" className="btn btn-sm" disabled={opening !== null}
                        onClick={() => portal(c, "copy")}>
                        {opening === c.id + "copy" ? "Copying…" : "Copy link"}
                      </button>
                      <ConfirmButton small label="Delete" prompt={`Delete ${c.name ?? c.uid} and their endpoints?`}
                        confirmLabel="Delete" onConfirm={() => remove(c)} />
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {cursor && (
          <div className="load-more">
            <button type="button" className="btn" onClick={() => load(cursor)}>Load more</button>
          </div>
        )}
      </section>
      <p className="muted small">
        Consumers&apos; endpoints don&apos;t appear on your <Link href="/endpoints">Endpoints</Link> page or trigger your
        failure alerts. Their events do appear under Events.
      </p>
    </div>
  );
}
