"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type LoginSession } from "@/lib/api";
import { describeDevice, relative } from "@/lib/format";
import { useMe } from "@/components/MeContext";
import { ConfirmButton, ErrorBox, Loading, PageHeader, Time } from "@/components/ui";
import { PasswordInput } from "@/components/PasswordInput";

const MIN_PASSWORD = 10;

function DeviceIcon({ ua }: { ua: string | null }) {
  const kind = !ua ? "other" : /iPhone|Android|Mobile/.test(ua) ? "phone" : /Mozilla\//.test(ua) ? "laptop" : "terminal";
  const paths: Record<string, string> = {
    phone: "M8 2.5h8a1.5 1.5 0 0 1 1.5 1.5v16a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20V4A1.5 1.5 0 0 1 8 2.5ZM11 18.5h2",
    laptop: "M4.5 6A1.5 1.5 0 0 1 6 4.5h12A1.5 1.5 0 0 1 19.5 6v9h-15V6ZM2.5 18.5h19",
    terminal: "M3.5 5.5h17v13h-17zM7 10l2.5 2L7 14M12 14h4",
    other: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 8v5M12 16h.01",
  };
  return (
    <span className="device-icon" aria-hidden>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={paths[kind]} /></svg>
    </span>
  );
}

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
      <div className="security-split">
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
      <aside className="security-tips">
        <div className="security-tips-title">A strong password</div>
        <ul>
          <li>Is at least 10 characters. Longer is better.</li>
          <li>Isn&apos;t used on any other site.</li>
          <li>Can be a few random words, like <span className="mono">plum-river-candle-orbit</span>.</li>
          <li>Lives in a password manager, so you don&apos;t have to remember it.</li>
        </ul>
        <p className="muted small">Forgot it? Use &quot;Forgot password?&quot; on the log-in page to reset it by email.</p>
      </aside>
      </div>
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
                    <span className="person">
                      <DeviceIcon ua={s.user_agent} />
                      <span title={s.user_agent ?? undefined}>{describeDevice(s.user_agent)}</span>
                      {s.current && <span className="badge badge-green security-this">This device</span>}
                    </span>
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
