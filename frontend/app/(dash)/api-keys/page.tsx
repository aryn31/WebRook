"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, API_PUBLIC_URL, type ApiKey } from "@/lib/api";
import { CodeBlock, ConfirmButton, Empty, ErrorBox, Loading, PageHeader, SecretBox, Time } from "@/components/ui";

function curlExample(key: string): string {
  return `curl -X POST ${API_PUBLIC_URL}/v1/events \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"event_type": "order.created", "data": {"order_id": "ord_123", "amount": 4999}}'`;
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<unknown>(null);
  const [created, setCreated] = useState<{ key: string; api_key: ApiKey } | null>(null);
  const [actionErr, setActionErr] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      setKeys((await api.listApiKeys()).data);
    } catch (e) {
      setLoadErr(e);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setCreateErr(null);
    try {
      const res = await api.createApiKey(name.trim());
      setCreated(res);
      setName("");
      setKeys((prev) => [res.api_key, ...(prev ?? []).filter((k) => k.id !== res.api_key.id)]);
    } catch (err) {
      setCreateErr(err);
    } finally {
      setCreating(false);
    }
  }

  async function revoke(k: ApiKey) {
    setActionErr(null);
    try {
      const res = await api.revokeApiKey(k.id);
      setKeys((prev) => (prev ?? []).map((x) => (x.id === k.id ? res.api_key : x)));
    } catch (err) {
      setActionErr(err);
    }
  }

  const sorted = keys ? [...keys].sort((a, b) => Number(!!a.revoked_at) - Number(!!b.revoked_at)) : null;

  return (
    <div className="page">
      <PageHeader title="API keys" sub="Your application authenticates to the HookFlow API with these keys." />

      <section className="card">
        <div className="card-head">
          <h2>Create a key</h2>
        </div>
        <form onSubmit={create} className="inline-form">
          <label className="field grow">
            <span className="field-label">Name</span>
            <input
              className="input"
              placeholder="e.g. Production"
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={creating || !name.trim()}>
            {creating ? "Creating…" : "Create key"}
          </button>
        </form>
        <ErrorBox error={createErr} />

        {created && (
          <div className="stack mt">
            <SecretBox
              title={`New key “${created.api_key.name}”`}
              value={created.key}
              warning="Copy this key now and store it somewhere safe. It won't be shown again."
            />
            <div>
              <div className="field-label">Send your first event</div>
              <CodeBlock code={curlExample(created.key)} />
            </div>
            <div>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setCreated(null)}>
                I&apos;ve saved it — dismiss
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Keys</h2>
        </div>
        <ErrorBox error={loadErr} onRetry={load} />
        <ErrorBox error={actionErr} />
        {!sorted && !loadErr && <Loading />}
        {sorted && sorted.length === 0 && (
          <Empty title="No API keys yet">Create one above to start sending events from your application.</Empty>
        )}
        {sorted && sorted.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Prefix</th>
                  <th>Created</th>
                  <th>Last used</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sorted.map((k) => (
                  <tr key={k.id} className={k.revoked_at ? "row-muted" : ""}>
                    <td>
                      {k.name}{" "}
                      {k.revoked_at && (
                        <span className="badge badge-grey" title={`Revoked ${new Date(k.revoked_at).toISOString()}`}>
                          Revoked
                        </span>
                      )}
                    </td>
                    <td className="mono">{k.prefix}_…</td>
                    <td>
                      <Time iso={k.created_at} />
                    </td>
                    <td>{k.last_used_at ? <Time iso={k.last_used_at} /> : <span className="muted">Never</span>}</td>
                    <td className="right">
                      {!k.revoked_at && (
                        <ConfirmButton
                          small
                          label="Revoke"
                          prompt="Requests using this key will fail immediately."
                          confirmLabel="Revoke key"
                          onConfirm={() => revoke(k)}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
