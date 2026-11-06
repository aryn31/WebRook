"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DOCS_URL } from "@/components/SiteChrome";

/** Shortcuts beside the contact form. The password link depends on whether the visitor is logged in. */
export function ContactLinks() {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store" })
      .then((r) => setSignedIn(r.ok))
      .catch(() => {});
  }, []);

  return (
    <div className="contact-links">
      <div className="contact-links-title">Find an answer faster</div>
      <a href={DOCS_URL} target="_blank" rel="noreferrer">API reference <span aria-hidden>↗</span></a>
      <Link href="/platform">How HookFlow delivers</Link>
      <Link href="/#demo">Try the live demo</Link>
      {signedIn ? (
        <Link href="/security">Change your password</Link>
      ) : (
        <Link href="/forgot-password">Reset your password</Link>
      )}
    </div>
  );
}
