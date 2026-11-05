"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorMessage, type SystemHealth } from "@/lib/api";
import { Brand } from "./Brand";
import { IconAudit, IconDeliveries, IconEndpoints, IconEvents, IconHome, IconKey, IconLogout, IconOverview, IconShield, IconTeam } from "./Icons";
import { accountLabel, ROLE_LABEL, useMe } from "./MeContext";
import { ThemeToggle } from "./ThemeToggle";
import { initials } from "./Avatar";

const NAV = [
  {
    group: "Monitor",
    items: [
      { href: "/overview", label: "Overview", Icon: IconOverview },
      { href: "/events", label: "Events", Icon: IconEvents },
      { href: "/deliveries", label: "Deliveries", Icon: IconDeliveries },
    ],
  },
  {
    group: "Configure",
    items: [
      { href: "/endpoints", label: "Endpoints", Icon: IconEndpoints },
      { href: "/api-keys", label: "API keys", Icon: IconKey },
    ],
  },
  {
    group: "Account",
    items: [
      { href: "/team", label: "Team", Icon: IconTeam },
      { href: "/audit-log", label: "Audit log", Icon: IconAudit },
      { href: "/security", label: "Security", Icon: IconShield },
    ],
  },
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

/** Current account and role; a picker when the user belongs to more than one account. */
function AccountSwitcher() {
  const { me, switchAccount } = useMe();
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!me) return <div className="user-email"><span className="muted">…</span></div>;

  if (me.accounts.length <= 1) {
    return (
      <div className="user-chip" title={me.user.email}>
        <span className="user-avatar" aria-hidden>{initials(me.user.email)}</span>
        <span className="user-chip-text">
          <span className="user-email">{me.user.email}</span>
          <span className="user-role">{ROLE_LABEL[me.account.role]}</span>
        </span>
      </div>
    );
  }

  async function pick(id: string) {
    if (id === me?.account.id) return;
    setSwitching(true);
    setError(null);
    try {
      await switchAccount(id); // reloads the page on success
    } catch (err) {
      setError(errorMessage(err));
      setSwitching(false);
    }
  }

  return (
    <div className="acct-switch">
      <label className="acct-label" htmlFor="acct-select">Account</label>
      <div className="acct-select-wrap">
        <select
          id="acct-select"
          className="acct-select"
          value={me.account.id}
          disabled={switching}
          onChange={(e) => void pick(e.target.value)}
          title={`${accountLabel(me.account)} · ${ROLE_LABEL[me.account.role]}`}
        >
          {me.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {accountLabel(a)} · {ROLE_LABEL[a.role]}
            </option>
          ))}
        </select>
        <span className="acct-current" aria-hidden>
          <span className="acct-name">{switching ? "Switching…" : accountLabel(me.account)}</span>
          <span className="acct-role">{ROLE_LABEL[me.account.role]}</span>
        </span>
      </div>
      <div className="user-email" title={me.user.email}>
        {me.user.email}
      </div>
      {error && <div className="acct-error" role="alert">{error}</div>}
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [loggingOut, setLoggingOut] = useState(false);

  async function logout() {
    setLoggingOut(true);
    try {
      await api.logout();
    } catch {
      // Even if the call fails, send the user to the login page.
    }
    window.location.replace("/login"); // Back shouldn't return to the dashboard
  }

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  return (
    <aside className="sidebar">
      <Brand href="/overview" className="sidebar-brand" />
      <nav className="nav">
        {NAV.map((g) => (
          <div key={g.group} className="nav-group">
            <div className="nav-group-label">{g.group}</div>
            {g.items.map((n) => (
              <Link key={n.href} href={n.href} className={`nav-link${isActive(n.href) ? " active" : ""}`}>
                <n.Icon className="nav-icon" />
                {n.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">
        <Link href="/" className="nav-link nav-home">
          <IconHome className="nav-icon" />
          Back to website
        </Link>
        <SystemStatus />
        <AccountSwitcher />
        <ThemeToggle className="sidebar-theme" />
        <button type="button" className="btn btn-sm btn-ghost logout" onClick={logout} disabled={loggingOut}>
          <IconLogout size={15} /> {loggingOut ? "Logging out…" : "Log out"}
        </button>
      </div>
    </aside>
  );
}
