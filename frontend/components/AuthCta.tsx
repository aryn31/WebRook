"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { IconArrow } from "./Icons";

// The public pages always render the logged-out buttons (Log in / Sign up) first, then ask the API whether the
// visitor has a valid session. Only a confirmed session swaps them: "Dashboard" once the email is verified, or
// "Verify email" for someone who signed up but hasn't entered their code yet (the dashboard would only send them
// back there). A leftover or expired cookie never hides the login buttons, and a slow backend never delays the page.

type Session = "none" | "unverified" | "verified";

let sessionCheck: Promise<Session> | null = null;

function checkSession(): Promise<Session> {
  sessionCheck ??= fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store" })
    .then(async (r): Promise<Session> => {
      if (!r.ok) return "none";
      const me = await r.json();
      return me?.user?.email_verified ? "verified" : "unverified";
    })
    .catch((): Session => "none");
  return sessionCheck;
}

function useSession(): Session {
  const [session, setSession] = useState<Session>("none");
  useEffect(() => {
    let alive = true;
    void checkSession().then((s) => alive && setSession(s));
    return () => {
      alive = false;
    };
  }, []);
  return session;
}

type Variant = "nav" | "hero" | "final";

/** Sign-up and log-in buttons, or a dashboard link for visitors who are already logged in. */
export function AuthCta({ variant, secondary }: { variant: Variant; secondary?: ReactNode }) {
  const session = useSession();
  const signedIn = session === "verified";

  if (session === "unverified") {
    return variant === "nav" ? (
      <Link href="/verify-email" className="btn btn-primary">Verify email</Link>
    ) : (
      <Link href="/verify-email" className="btn btn-signal btn-lg">
        Finish signing up <IconArrow size={16} />
      </Link>
    );
  }

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
