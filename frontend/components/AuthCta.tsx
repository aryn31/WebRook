"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { IconArrow } from "./Icons";

// The public pages always render the logged-out buttons (Log in / Sign up) first, then ask the API whether the
// visitor has a valid session. Only a confirmed session swaps them for "Dashboard". A leftover or expired cookie
// therefore never hides the login buttons, and a slow or sleeping backend never delays the page.

let sessionCheck: Promise<boolean> | null = null;

function checkSession(): Promise<boolean> {
  sessionCheck ??= fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store" })
    .then((r) => r.ok)
    .catch(() => false);
  return sessionCheck;
}

function useSignedIn(): boolean {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    let alive = true;
    void checkSession().then((ok) => alive && setSignedIn(ok));
    return () => {
      alive = false;
    };
  }, []);
  return signedIn;
}

type Variant = "nav" | "hero" | "final";

/** Sign-up and log-in buttons, or a dashboard link for visitors who are already logged in. */
export function AuthCta({ variant, secondary }: { variant: Variant; secondary?: ReactNode }) {
  const signedIn = useSignedIn();

  if (variant === "nav") {
    return signedIn ? (
      <Link href="/overview" className="btn btn-primary">Dashboard</Link>
    ) : (
      <>
        <Link href="/login" className="btn btn-ghost">Log in</Link>
        <Link href="/register" className="btn btn-primary">Sign up</Link>
      </>
    );
  }

  if (signedIn) {
    return (
      <Link href="/overview" className="btn btn-signal btn-lg">
        Open dashboard <IconArrow size={16} />
      </Link>
    );
  }
  return (
    <>
      <Link href="/register" className="btn btn-signal btn-lg">
        Sign up free <IconArrow size={16} />
      </Link>
      {secondary ?? (
        <Link href="/login" className={`btn btn-lg ${variant === "hero" ? "btn-glass" : "lp-final-login"}`}>
          Log in
        </Link>
      )}
    </>
  );
}
