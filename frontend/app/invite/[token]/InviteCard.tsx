"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage, type InvitePreview, type MemberRole, type User } from "@/lib/api";
import { ROLE_LABEL } from "@/components/MeContext";
import { Loading } from "@/components/ui";
import { formatLocal } from "@/lib/format";

const ROLE_SUMMARY: Record<MemberRole, string> = {
  admin: "You'll be able to send events, manage endpoints and API keys, and invite people.",
  developer: "You'll be able to send events, replay deliveries, and manage endpoints and API keys.",
  viewer: "You'll be able to see events, deliveries, endpoints and the audit log, but not change anything.",
};

type State =
  | { kind: "loading" }
  | { kind: "invalid"; message: string }
  | { kind: "error"; error: unknown }
  | { kind: "ready"; preview: InvitePreview; user: User | null };

export function InviteCard({ token }: { token: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [accepting, setAccepting] = useState(false);
  const [acceptErr, setAcceptErr] = useState<unknown>(null);
  const [wrongUser, setWrongUser] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const [preview, me] = await Promise.all([api.previewInvite(token), api.me().catch(() => null)]);
      setState({ kind: "ready", preview, user: me?.user ?? null });
      setWrongUser(!!me && me.user.email.toLowerCase() !== preview.email.toLowerCase());
    } catch (err) {
      if (err instanceof ApiError && (err.code === "invite_invalid" || err.status === 404)) {
        setState({ kind: "invalid", message: err.message });
      } else {
        setState({ kind: "error", error: err });
      }
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function accept() {
    setAccepting(true);
    setAcceptErr(null);
    try {
      await api.acceptInvite(token);
      // The session now works in the team's account; reload so the dashboard starts fresh.
      window.location.assign("/overview");
    } catch (err) {
      setAccepting(false);
      if (err instanceof ApiError && err.code === "invite_wrong_user") {
        setWrongUser(true);
      } else if (err instanceof ApiError && err.code === "invite_invalid") {
        setState({ kind: "invalid", message: err.message });
      } else {
        setAcceptErr(err);
      }
    }
  }

  async function switchUser() {
    setLoggingOut(true);
    try {
      await api.logout();
    } catch {
      // Go to the login page regardless.
    }
    window.location.assign(`/login?next=${encodeURIComponent(`/invite/${token}`)}`);
  }

  if (state.kind === "loading") return <Loading label="Checking your invitation…" />;

  if (state.kind === "invalid") {
    return (
      <div className="stack">
        <div className="auth-head">
          <h1 className="auth-title">This invite link doesn&apos;t work</h1>
          <p className="muted">
            It may have expired (links last 7 days), been revoked, replaced by a newer invite, or already been used.
          </p>
        </div>
        <p className="muted small">Ask the person who invited you to send a new link.</p>
        <Link href="/overview" className="btn btn-block">
          Go to your dashboard
        </Link>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="stack">
        <div className="auth-head">
          <h1 className="auth-title">Couldn&apos;t load this invitation</h1>
        </div>
        <div className="alert alert-error" role="alert">
          <strong>{errorMessage(state.error)}</strong>
          <button type="button" className="btn btn-sm" onClick={() => void load()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const { preview, user } = state;
  return (
    <div className="stack">
      <div className="auth-head">
        <span className="invite-kicker">You&apos;re invited</span>
        <h1 className="auth-title">
          Join {preview.account_owner_email}&apos;s team as {ROLE_LABEL[preview.role].toLowerCase()}
        </h1>
        <p className="muted">{ROLE_SUMMARY[preview.role]}</p>
      </div>

      <dl className="invite-facts">
        <div>
          <dt>Invitation for</dt>
          <dd>{preview.email}</dd>
        </div>
        <div>
          <dt>Logged in as</dt>
          <dd className={wrongUser ? "text-failed" : undefined}>{user?.email ?? "—"}</dd>
        </div>
        <div>
          <dt>Link expires</dt>
          <dd>{formatLocal(preview.expires_at)}</dd>
        </div>
      </dl>

      {wrongUser ? (
        <>
          <div className="alert alert-warning" role="alert">
            <div>
              <strong>This invitation is for {preview.email}.</strong>
              <div>
                You&apos;re logged in as {user?.email ?? "a different account"}. Log in (or sign up) with{" "}
                {preview.email} to accept it.
              </div>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-primary btn-block btn-lg"
            onClick={() => void switchUser()}
            disabled={loggingOut}
          >
            {loggingOut ? "Logging out…" : "Log out and use the right account"}
          </button>
          <Link href="/overview" className="btn btn-ghost btn-block">
            Not now — back to my dashboard
          </Link>
        </>
      ) : (
        <>
          {acceptErr != null && (
            <div className="alert alert-error" role="alert">
              <strong>{errorMessage(acceptErr)}</strong>
            </div>
          )}
          <button
            type="button"
            className="btn btn-primary btn-block btn-lg"
            onClick={() => void accept()}
            disabled={accepting}
          >
            {accepting ? "Joining…" : "Accept and join"}
          </button>
          <p className="muted small center">
            You keep your personal account. Switch between accounts from the sidebar.
          </p>
        </>
      )}
    </div>
  );
}
