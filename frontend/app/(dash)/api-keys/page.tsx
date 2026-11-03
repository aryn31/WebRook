"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, API_PUBLIC_URL, type ApiKey, type ApiScope, type ScopeInfo } from "@/lib/api";
import { useMe } from "@/components/MeContext";
import { CodeBlock, ConfirmButton, Empty, ErrorBox, Loading, PageHeader, SecretBox, Time } from "@/components/ui";

type Preset = "full" | "send" | "read" | "custom";

const PRESETS: { id: Preset; label: string; hint: string; scopes?: ApiScope[] }[] = [
  { id: "full", label: "Full access", hint: "Everything your role allows." },
  { id: "send", label: "Send events only", hint: "Best for production servers.", scopes: ["events:write"] },
  {
    id: "read",
    label: "Read only",
    hint: "Dashboards and reporting.",
    scopes: ["events:read", "deliveries:read", "endpoints:read", "audit:read"],
  },
  { id: "custom", label: "Custom", hint: "Pick scopes one by one." },
];

/** Short label for a key's scopes in the table. */
function scopeSummary(scopes: ApiScope[], all: number): string {
  if (scopes.length >= all) return "Full access";
  if (scopes.length === 1 && scopes[0] === "events:write") return "Send events only";
  if (scopes.every((s) => s.endsWith(":read"))) return "Read only";
  return `${scopes.length} scope${scopes.length === 1 ? "" : "s"}`;
}

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
  const [scopeInfo, setScopeInfo] = useState<ScopeInfo[]>([]);
  const [preset, setPreset] = useState<Preset>("full");
  const [custom, setCustom] = useState<ApiScope[]>(["events:write"]);
  const { me, can } = useMe();
  const allowed = new Set(me?.permissions ?? []);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      setKeys((await api.listApiKeys()).data);
    } catch (e) {
      setLoadErr(e);
    }
  }, []);

  const canManage = can("api_keys:manage");

  useEffect(() => {
    if (!canManage) return;
    void load();
    api.listScopes().then((r) => setScopeInfo(r.data)).catch(() => {});
  }, [load, canManage]);

  const chosenScopes = (): ApiScope[] | undefined => {
    if (preset === "full") return undefined;
    if (preset === "custom") return custom;
    return PRESETS.find((p) => p.id === preset)?.scopes;
  };

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setCreateErr(null);
    try {
      const res = await api.createApiKey(name.trim(), chosenScopes());
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
  const header = (
    <PageHeader title="API keys" sub="Your application authenticates to the HookFlow API with these keys." />
  );

  if (me && !canManage) {
    return (
      <div className="page">
        {header}
        <section className="card">
          <Empty title="You can't manage API keys">
            Your role in this account is {me.account.role}. Ask an admin to make you a developer, or to create a key
            for you.
          </Empty>
        </section>
      </div>
    );
  }

  const customInvalid = preset === "custom" && custom.length === 0;

  return (
    <div className="page">
      {header}

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
          <button type="submit" className="btn btn-primary" disabled={creating || !name.trim() || customInvalid}>
            {creating ? "Creating…" : "Create key"}
          </button>
        </form>
        <fieldset className="scope-picker">
          <legend className="field-label">Access</legend>
          <div className="scope-presets" role="radiogroup">
            {PRESETS.map((p) => (
              <label key={p.id} className={`scope-preset${preset === p.id ? " active" : ""}`}>
                <input
                  type="radio"
                  name="preset"
                  checked={preset === p.id}
                  onChange={() => setPreset(p.id)}
                />
                <span className="scope-preset-label">{p.label}</span>
                <span className="muted small">{p.hint}</span>
              </label>
            ))}
          </div>
          {preset === "custom" && (
            <div className="scope-list">
              {scopeInfo.map((s) => {
                const ok = allowed.has(s.scope);
                return (
                  <label key={s.scope} className={`scope-item${ok ? "" : " disabled"}`} title={ok ? undefined : "Your role doesn't allow this scope."}>
                    <input
                      type="checkbox"
                      disabled={!ok}
                      checked={custom.includes(s.scope)}
                      onChange={(e) =>
                        setCustom((prev) =>
                          e.target.checked ? [...prev, s.scope] : prev.filter((x) => x !== s.scope),
                        )
                      }
                    />
                    <code>{s.scope}</code>
                    <span className="muted small">{s.description}</span>
                  </label>
                );
              })}
              {customInvalid && <span className="field-hint field-hint-error">Pick at least one scope.</span>}
            </div>
          )}
        </fieldset>
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
              {!created.api_key.scopes.includes("events:write") && (
                <p className="muted small">This key can&apos;t send events, so the example above will be refused.</p>
              )}
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
                  <th>Access</th>
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
                    <td title={k.scopes.join("\n")}>{scopeSummary(k.scopes, scopeInfo.length || 7)}</td>
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
