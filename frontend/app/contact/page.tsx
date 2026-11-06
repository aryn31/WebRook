import type { Metadata } from "next";
import { CONTACT_EMAIL, SiteFooter, SiteHeader } from "@/components/SiteChrome";
import { ContactForm } from "./ContactForm";
import { ContactLinks } from "./ContactLinks";
import { CopyButton } from "@/components/ui";

export const metadata: Metadata = {
  title: "Contact",
  description: "Questions, help with your account, pricing or a bug: send the HookFlow team a message.",
};

export default function ContactPage() {
  return (
    <div className="lp">
      <SiteHeader active="contact" />
      <main className="lp-wrap contact">
        <div className="contact-head">
          <p className="lp-kicker">Contact</p>
          <h1 className="legal-title">Talk to <em>a person.</em></h1>
          <p className="lp-sub">Questions, help with your account, pricing or a bug. Send a message and we&apos;ll reply by email.</p>
        </div>
        <div className="contact-grid">
          <section className="contact-card">
            <ContactForm />
          </section>
          <aside className="contact-side">
            <div className="contact-support">
              <span className="contact-support-icon" aria-hidden>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3.5 6.5 8.5 6.5 8.5-6.5" /></svg>
              </span>
              <h2>Support</h2>
              <p className="muted">Prefer email? Write to us directly.</p>
              <a className="contact-email mono" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
              <div className="contact-actions">
                <a className="btn btn-primary btn-sm" href={`mailto:${CONTACT_EMAIL}`}>Open email</a>
                <CopyButton text={CONTACT_EMAIL} label="Copy address" />
              </div>
              <p className="contact-note">We usually reply within a day or two.</p>
            </div>
            <ContactLinks />
          </aside>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
