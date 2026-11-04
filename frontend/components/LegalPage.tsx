import type { ReactNode } from "react";
import { SiteFooter, SiteHeader } from "./SiteChrome";

export const REPO_URL = "https://github.com/aryn31/WebRook";
export const LEGAL_UPDATED = "4 November 2026";

/** Contact for privacy and terms questions: an email if configured, otherwise the project's GitHub issues. */
export function Contact() {
  const email = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
  if (email) return <a href={`mailto:${email}`}>{email}</a>;
  return (
    <a href={`${REPO_URL}/issues`} target="_blank" rel="noreferrer">
      an issue on the project&apos;s GitHub
    </a>
  );
}

export function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="lp">
      <SiteHeader />
      <main className="lp-wrap legal">
        <p className="lp-kicker">Legal</p>
        <h1 className="legal-title">{title}</h1>
        <p className="muted">Last updated {LEGAL_UPDATED}</p>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
