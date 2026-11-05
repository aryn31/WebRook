"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, errorMessage } from "@/lib/api";
import { leaveTo } from "@/lib/navigation";

const RESEND_SECONDS = 60;

function safeNext(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/verify-email")) return next;
  return "/overview";
}

export function VerifyEmailForm() {
  const [email, setEmail] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [wait, setWait] = useState(RESEND_SECONDS);
  const [sending, setSending] = useState(false);
  const submitted = useRef("");

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("send_failed")) {
      setError("We couldn't send the email. Send the code again below.");
      setWait(0);
    }
    api
      .me()
      .then((m) => {
        if (m.user.email_verified) leaveTo(safeNext());
        else setEmail(m.user.email);
      })
      .catch(() => {}); // 401 already redirects to /login
  }, []);

  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  const verify = useCallback(async (value: string) => {
    submitted.current = value;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.verifyEmail(value);
      leaveTo(safeNext());
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.code === "code_expired") setCode("");
      setBusy(false);
    }
  }, []);

  function onChange(raw: string) {
    const digits = raw.replace(/\D/g, "").slice(0, 6);
    setCode(digits);
    // Submit as soon as all six digits are in (e.g. pasted or filled from the email), once per value.
    if (digits.length === 6 && digits !== submitted.current && !busy) void verify(digits);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (code.length === 6) void verify(code);
  }

  async function resend() {
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.resendVerification();
      setNotice(`New code sent to ${res.sent_to}. The previous code no longer works.`);
      setWait(res.resend_after_seconds);
      setCode("");
      submitted.current = "";
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.retryAfter) setWait(err.retryAfter);
    } finally {
      setSending(false);
    }
  }

  async function useDifferentEmail() {
    try {
      await api.logout();
    } catch {
      // Go to sign-up either way.
    }
    leaveTo("/register");
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <div className="auth-head">
        <h1 className="auth-title">Check your email</h1>
        <p className="muted">
          We sent a 6-digit code to {email ? <strong>{email}</strong> : "your email address"}. Enter it to finish
          setting up your account. It expires in 15 minutes.
        </p>
      </div>
      <label className="field">
        <span className="field-label">Verification code</span>
        <input
          className="input verify-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          placeholder="123456"
          autoFocus
          value={code}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={!!error || undefined}
        />
        <span className="field-hint">Can&apos;t find it? Check your spam folder.</span>
      </label>
      {error && (
        <div className="alert alert-error" role="alert">
          <strong>{error}</strong>
        </div>
      )}
      {notice && (
        <div className="alert alert-success" role="status">
          {notice}
        </div>
      )}
      <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy || code.length !== 6}>
        {busy ? "Checking…" : "Verify email"}
      </button>
      <div className="muted small center verify-links">
        <button type="button" className="link-button" onClick={resend} disabled={sending || wait > 0}>
          {sending ? "Sending…" : wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}
        </button>
        <span aria-hidden> · </span>
        <button type="button" className="link-button" onClick={useDifferentEmail}>
          Use a different email
        </button>
      </div>
    </form>
  );
}
