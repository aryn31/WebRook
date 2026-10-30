"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api, ApiError, describeDetails } from "@/lib/api";

function safeNext(): string {
  if (typeof window === "undefined") return "/";
  const next = new URLSearchParams(window.location.search).get("next");
  // Only allow same-site relative paths.
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/";
}

function authErrorText(err: unknown, mode: "login" | "register"): { text: string; details: string[] } {
  if (err instanceof ApiError) {
    const details = describeDetails(err.details);
    switch (err.code) {
      case "invalid_credentials":
        return { text: "Incorrect email or password.", details: [] };
      case "email_taken":
        return {
          text: "An account with this email already exists. Log in instead, or use a different email.",
          details: [],
        };
      case "rate_limited":
        return { text: "Too many attempts. Please wait a minute before trying again.", details: [] };
      case "validation_error":
        return { text: err.message || "Please check the form.", details };
      default:
        return { text: err.message || `Could not ${mode === "login" ? "log in" : "create your account"}.`, details };
    }
  }
  return { text: "Something went wrong. Please try again.", details: [] };
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; details: string[]; code?: string } | null>(null);

  const pwTooShort = mode === "register" && password.length > 0 && password.length < 10;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (mode === "register" && password.length < 10) {
      setError({ text: "Password must be at least 10 characters.", details: [] });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await api.login(email.trim(), password);
      else await api.register(email.trim(), password);
      // Full navigation so middleware sees the fresh cookie.
      window.location.assign(safeNext());
    } catch (err) {
      setError({ ...authErrorText(err, mode), code: err instanceof ApiError ? err.code : undefined });
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <h1 className="auth-title">{mode === "login" ? "Log in" : "Create your account"}</h1>
      <label className="field">
        <span className="field-label">Email</span>
        <input
          type="email"
          className="input"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Password</span>
        <input
          type="password"
          className="input"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={mode === "register" ? 10 : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {mode === "register" && (
          <span className={`field-hint${pwTooShort ? " text-failed" : ""}`}>
            At least 10 characters{pwTooShort ? ` (${password.length}/10)` : ""}.
          </span>
        )}
      </label>
      {error && (
        <div className="alert alert-error" role="alert">
          <div>
            <strong>{error.text}</strong>
            {error.details.length > 0 && (
              <ul className="alert-details">
                {error.details.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            )}
            {error.code === "email_taken" && (
              <div>
                <Link href="/login">Go to log in →</Link>
              </div>
            )}
          </div>
        </div>
      )}
      <button type="submit" className="btn btn-primary btn-block" disabled={busy || !email || !password}>
        {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
      </button>
      <div className="muted small center">
        {mode === "login" ? (
          <>
            New to HookFlow? <Link href="/register">Create an account</Link>
          </>
        ) : (
          <>
            Already have an account? <Link href="/login">Log in</Link>
          </>
        )}
      </div>
    </form>
  );
}
