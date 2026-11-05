import Link from "next/link";
import { API_PUBLIC_URL } from "@/lib/api";
import { AuthCta } from "./AuthCta";
import { Brand } from "./Brand";
import { ThemeToggle } from "./ThemeToggle";

export const DOCS_URL = `${API_PUBLIC_URL}/docs`;

/** Top bar for the public pages (home and platform). */
export function SiteHeader({ active }: { active?: "home" | "platform" }) {
  return (
    <header className="lp-nav">
      <div className="lp-wrap lp-nav-inner">
        <Brand />
        <nav className="lp-links" aria-label="Site">
          <Link href="/platform" className={active === "platform" ? "active" : ""} aria-current={active === "platform" ? "page" : undefined}>
            Platform
          </Link>
          <Link href="/#demo">Live demo</Link>
          <Link href="/#developers">Developers</Link>
          <a href={DOCS_URL} target="_blank" rel="noreferrer">API reference</a>
        </nav>
        <div className="lp-nav-actions">
          <ThemeToggle className="nav-theme" />
          <AuthCta variant="nav" />
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-wrap lp-footer-inner">
        <Brand />
        <span className="muted small">Reliable webhook delivery.</span>
        <nav className="lp-footer-links" aria-label="Footer">
          <Link href="/platform">Platform</Link>
          <a href={DOCS_URL} target="_blank" rel="noreferrer">API reference</a>
          <Link href="/login">Log in</Link>
          <Link href="/register">Sign up</Link>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
        </nav>
        <ThemeToggle />
      </div>
    </footer>
  );
}
