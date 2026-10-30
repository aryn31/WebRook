"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type User } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview", icon: "◧" },
  { href: "/events", label: "Events", icon: "⚡" },
  { href: "/deliveries", label: "Deliveries", icon: "⇄" },
  { href: "/endpoints", label: "Endpoints", icon: "◎" },
  { href: "/api-keys", label: "API keys", icon: "⚿" },
];

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
