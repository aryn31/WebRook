import type { ReactNode } from "react";
import { CONTACT_EMAIL, SiteFooter, SiteHeader } from "./SiteChrome";

export const LEGAL_UPDATED = "4 November 2026";

/** Contact for privacy and terms questions. */
export function Contact() {
  return <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;
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
