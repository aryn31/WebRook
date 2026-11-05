"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, errorMessage } from "@/lib/api";
import { PasswordInput } from "@/components/PasswordInput";
import { leaveTo, useLeaveIfSignedIn } from "@/lib/navigation";

const MIN_PASSWORD = 10;

// Step 1: enter your email and we send a code. Step 2: enter the code and a new password.
export function ForgotPasswordForm({ hasSession = false }: { hasSession?: boolean }) {
  const checking = useLeaveIfSignedIn(hasSession, () => "/overview");
  const [step, setStep] = useState<"email" | "reset">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [wait, setWait] = useState(0);

  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  async function sendCode(e?: FormEvent) {
    e?.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.forgotPassword(email.trim());
      setWait(res.resend_after_seconds);
      if (step === "reset") {
        setNotice("If an account exists for this email, a new code is on its way. The previous code no longer works.");
        setCode("");
      }
      setStep("reset");
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.retryAfter) setWait(err.retryAfter);
    } finally {
      setBusy(false);
    }
  }

  async function reset(e: FormEvent) {
    e.preventDefault();
    if (code.length !== 6 || password.length < MIN_PASSWORD) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.resetPassword(email.trim(), code, password);
      // Logged in with the new password. Full navigation so middleware sees the new cookie.
      leaveTo("/overview");
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.code === "code_expired") setCode("");
      setBusy(false);
    }
  }

  if (checking) return <p className="muted center">Taking you to your dashboard…</p>;

  if (step === "email") {
    return (
      <form onSubmit={sendCode} className="stack" noValidate>
        <div className="auth-head">
          <h1 className="auth-title">Forgot your password?</h1>
          <p className="muted">Enter the email you signed up with and we&apos;ll send you a code to choose a new one.</p>
        </div>
        <label className="field">
          <span className="field-label">Email</span>
          <input
            type="email"
            className="input"
            autoComplete="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        {error && (
          <div className="alert alert-error" role="alert">
            <strong>{error}</strong>
          </div>
        )}
        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy || !email.trim()}>
          {busy ? "Sending…" : "Send reset code"}
        </button>
        <div className="muted small center">
          Remembered it? <Link href="/login">Log in</Link>
        </div>
      </form>
    );
  }

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;

  return (
    <form onSubmit={reset} className="stack" noValidate>
      <div className="auth-head">
        <h1 className="auth-title">Check your email</h1>
        <p className="muted">
          If an account exists for <strong>{email.trim()}</strong>, we sent it a 6-digit code. It expires in 15
          minutes.
        </p>
      </div>
      <label className="field">
        <span className="field-label">Reset code</span>
        <input
          className="input verify-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          placeholder="123456"
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
        />
        <span className="field-hint">Can&apos;t find it? Check your spam folder.</span>
      </label>
      <label className="field">
        <span className="field-label">New password</span>
        <PasswordInput
          autoComplete="new-password"
          maxLength={256}
          value={password}
          aria-invalid={tooShort || undefined}
          onChange={(e) => setPassword(e.target.value)}
        />
        <span className={`field-hint${tooShort ? " field-hint-error" : ""}`}>
          At least {MIN_PASSWORD} characters{tooShort ? ` (${password.length}/${MIN_PASSWORD})` : ""}. You&apos;ll be
          signed out everywhere else.
        </span>
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
      <button
        type="submit"
        className="btn btn-primary btn-block btn-lg"
        disabled={busy || code.length !== 6 || password.length < MIN_PASSWORD}
      >
        {busy ? "Please wait…" : "Reset password and log in"}
      </button>
      <div className="muted small center verify-links">
        <button type="button" className="link-button" onClick={() => sendCode()} disabled={busy || wait > 0}>
          {wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}
        </button>
        <span aria-hidden> · </span>
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setStep("email");
            setCode("");
            setError(null);
            setNotice(null);
          }}
        >
          Use a different email
        </button>
      </div>
    </form>
  );
}
