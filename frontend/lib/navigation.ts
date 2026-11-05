"use client";

import { useEffect, useState } from "react";

/**
 * Leave the page without keeping it in the browser history, so Back doesn't return to it.
 * Used after logging in or out, where going back to the previous page makes no sense.
 */
export function leaveTo(path: string) {
  window.location.replace(path);
}

/**
 * On the log-in, sign-up and reset pages: if this browser is already logged in, go to the dashboard instead.
 * `hasSession` comes from the server (the session cookie can't be read from JavaScript); the cookie may be stale,
 * so the API confirms it. Returns true while checking, so the page can hold off showing the form.
 */
export function useLeaveIfSignedIn(hasSession: boolean, next: () => string): boolean {
  const [checking, setChecking] = useState(hasSession);
  useEffect(() => {
    if (!hasSession) return;
    let cancelled = false;
    fetch("/api/v1/auth/me", { credentials: "include", cache: "no-store", headers: { Accept: "application/json" } })
      .then(async (r) => {
        if (!r.ok) throw new Error("not signed in");
        const me = await r.json();
        if (cancelled) return;
        const dest = next();
        leaveTo(me?.user?.email_verified ? dest : `/verify-email?next=${encodeURIComponent(dest)}`);
      })
      .catch(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hasSession]);
  return checking;
}
