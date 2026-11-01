"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type SystemHealth, type User } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview", icon: "◧" },
  { href: "/events", label: "Events", icon: "⚡" },
  { href: "/deliveries", label: "Deliveries", icon: "⇄" },
  { href: "/endpoints", label: "Endpoints", icon: "◎" },
  { href: "/api-keys", label: "API keys", icon: "⚿" },
  { href: "/audit-log", label: "Audit log", icon: "☰" },
];

const STATUS_POLL_MS = 60_000;

/** One line telling the user whether deliveries are flowing. Hidden until there's something to say. */
function SystemStatus() {
  const [health, setHealth] = useState<SystemHealth | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.systemHealth().then((h) => alive && setHealth(h));
    void load();
    const timer = window.setInterval(load, STATUS_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!health) return null;
  let tone: "ok" | "warn" | "bad";
  let text: string;
  let detail: string;
  if (health.status !== "ok") {
    const down = Object.entries(health.checks)
      .filter(([, v]) => v !== "ok")
      .map(([k]) => k);
    tone = "bad";
    text = "Service problem";
    detail = `Unavailable: ${down.join(", ") || "unknown"}. Events sent now may be rejected; retry shortly.`;
  } else if (health.worker === "stale") {
    tone = "warn";
    text = "Deliveries delayed";
    detail = "The delivery worker hasn't checked in for over 2 minutes. Events are saved and will be sent once it's back.";
  } else if (health.worker === "ok") {
    tone = "ok";
    text = "All systems normal";
    detail = "API, database, queue and delivery worker are running.";
  } else {
    return null; // worker status not known yet (e.g. just started)
  }
  return (
    <div className={`sys-status sys-${tone}`} title={detail} role="status">
      <span className="sys-dot" aria-hidden />
      {text}
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    api.me().then((r) => setUser(r.user)).catch(() => {
      /* 401 redirects to /login inside the client */
    });
  }, []);

  async function logout() {
    setLoggingOut(true);
    try {
      await api.logout();
    } catch {
      // Even if the call fails, send the user to the login page.
    }
    window.location.assign("/login");
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/"));

  return (
    <aside className="sidebar">
      <Link href="/" className="brand">
        <span className="brand-mark" aria-hidden>H</span> HookFlow
      </Link>
      <nav className="nav">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className={`nav-link${isActive(n.href) ? " active" : ""}`}>
            <span className="nav-icon" aria-hidden>{n.icon}</span>
            {n.label}
          </Link>
        ))}
      </nav>
      <div className="sidebar-foot">
        <SystemStatus />
        <div className="user-email" title={user?.email}>
          {user ? user.email : <span className="muted">…</span>}
        </div>
        <button type="button" className="btn btn-sm btn-ghost" onClick={logout} disabled={loggingOut}>
          {loggingOut ? "Logging out…" : "Log out"}
        </button>
      </div>
    </aside>
  );
}
