"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type LoginSession } from "@/lib/api";
import { describeDevice, relative } from "@/lib/format";
import { useMe } from "@/components/MeContext";
import { ConfirmButton, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";
import { PasswordInput } from "@/components/PasswordInput";

const MIN_PASSWORD = 10;

function PasswordCard({ onChanged }: { onChanged: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState<number | null>(null);

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD;
  const mismatch = confirm.length > 0 && confirm !== next;
  const ready = current.length > 0 && next.length >= MIN_PASSWORD && confirm === next;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setErr(null);
    setDone(null);
    try {
      const res = await api.changePassword(current, next);
      setDone(res.signed_out_sessions);
      setCurrent("");
      setNext("");
      setConfirm("");
      onChanged();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  const fieldError = err instanceof ApiError ? (err.details as { field?: string } | null)?.field : undefined;

  return (
    <section className="card">
      <div className="card-head">
        <h2>Password</h2>
        <span className="muted small">Changing it signs you out everywhere else.</span>
      </div>
      <form onSubmit={submit} className="stack security-form">
        <label className="field">
          <span className="field-label">Current password</span>
          <PasswordInput
            autoComplete="current-password"
            value={current}
            maxLength={256}
            aria-invalid={fieldError === "current_password" || undefined}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">New password</span>
          <PasswordInput
            autoComplete="new-password"
            value={next}
            maxLength={256}
            aria-invalid={tooShort || fieldError === "new_password" || undefined}
            onChange={(e) => setNext(e.target.value)}
          />
          <span className={`field-hint${tooShort ? " field-hint-error" : ""}`}>
            At least {MIN_PASSWORD} characters. A few random words work well.
          </span>
        </label>
        <label className="field">
          <span className="field-label">Confirm new password</span>
          <PasswordInput
            autoComplete="new-password"
            value={confirm}
            maxLength={256}
            aria-invalid={mismatch || undefined}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {mismatch && <span className="field-hint field-hint-error">The passwords don&apos;t match.</span>}
        </label>
        <div>
          <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
            {busy ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
      <ErrorBox error={err} />
      {done !== null && (
        <div className="alert alert-success mt" role="status">
          Password changed.{" "}
          {done === 0
            ? "You weren't logged in anywhere else."
            : `${done} other session${done === 1 ? " was" : "s were"} signed out.`}
        </div>
      )}
    </section>
  );
}

function SessionsCard({ reloadKey }: { reloadKey: number }) {
  const [sessions, setSessions] = useState<LoginSession[] | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [actionErr, setActionErr] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      setSessions((await api.listSessions()).data);
    } catch (e) {
      setLoadErr(e);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  async function signOut(s: LoginSession) {
    setActionErr(null);
    setNotice(null);
    try {
      await api.signOutSession(s.id);
      if (s.current) {
        window.location.replace("/login");
        return;
      }
      setSessions((prev) => (prev ?? []).filter((x) => x.id !== s.id));
      setNotice(`Signed out ${describeDevice(s.user_agent)}.`);
    } catch (e) {
      setActionErr(e);
      void load();
    }
  }

  async function signOutOthers() {
    setActionErr(null);
    setNotice(null);
    try {
      const res = await api.signOutOtherSessions();
      const n = res.signed_out_sessions;
      setNotice(n === 0 ? "No other sessions were open." : `Signed out ${n} other session${n === 1 ? "" : "s"}.`);
      await load();
    } catch (e) {
      setActionErr(e);
    }
  }

  const others = (sessions ?? []).filter((s) => !s.current).length;

  return (
    <section className="card">
      <div className="card-head">
        <h2>Where you&apos;re logged in</h2>
        {others > 0 && (
          <ConfirmButton
            label="Sign out all other sessions"
            prompt={`Sign out ${others} other session${others === 1 ? "" : "s"}?`}
            confirmLabel="Sign out"
            small
            onConfirm={signOutOthers}
          />
        )}
      </div>
      <p className="muted small security-intro">
        Each browser you log in from appears here. If you don&apos;t recognise one, sign it out and change your
        password. Sessions end on their own after 7 days.
      </p>
      <ErrorBox error={loadErr} onRetry={load} />
      <ErrorBox error={actionErr} />
      {notice && (
        <div className="alert alert-success" role="status">
          {notice}
        </div>
      )}
      {!sessions && !loadErr && <Loading />}
      {sessions && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Device</th>
                <th>IP address</th>
                <th>Last active</th>
                <th>Logged in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td>
                    <span title={s.user_agent ?? undefined}>{describeDevice(s.user_agent)}</span>
                    {s.current && <span className="badge badge-green security-this">This device</span>}
                  </td>
                  <td className="mono">{s.ip_address ?? <span className="muted">—</span>}</td>
                  <td className="nowrap">{s.current ? "Now" : relative(s.last_seen_at)}</td>
                  <td>
                    <Time iso={s.created_at} />
                  </td>
                  <td className="right">
                    <ConfirmButton
                      label={s.current ? "Log out" : "Sign out"}
                      prompt={s.current ? "Log out of this browser?" : "Sign out this session?"}
                      confirmLabel={s.current ? "Log out" : "Sign out"}
                      small
                      onConfirm={() => signOut(s)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function SecurityPage() {
  const { me } = useMe();
  // Changing the password signs out other sessions, so the list is re-read afterwards.
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <div className="page">
      <PageHeader
        title="Security"
        sub={me ? <>Your login for <strong>{me.user.email}</strong>. This applies to every account you work in.</> : undefined}
      />
      <PasswordCard onChanged={() => setReloadKey((k) => k + 1)} />
      <SessionsCard reloadKey={reloadKey} />
    </div>
  );
}
