"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, type Account, type Me, type Permission, type Role } from "@/lib/api";

type MeState = {
  /** null while loading. */
  me: Me | null;
  /** True if the current role (in the current account) allows this. False while loading. */
  can: (p: Permission) => boolean;
  /** Re-fetch, e.g. after switching accounts or accepting an invite. */
  refresh: () => Promise<Me | null>;
  /** Switch account, then reload the page so every view shows the new account's data. */
  switchAccount: (accountId: string) => Promise<void>;
};

const Ctx = createContext<MeState>({
  me: null,
  can: () => false,
  refresh: async () => null,
  switchAccount: async () => {},
});

export function MeProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);

  const refresh = useCallback(async () => {
    try {
      const m = await api.me();
      if (!m.user.email_verified) {
        const { pathname, search } = window.location;
        window.location.assign(`/verify-email?next=${encodeURIComponent(pathname + search)}`);
        return null;
      }
      setMe(m);
      return m;
    } catch {
      return null; // 401 redirects to /login inside the client
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const switchAccount = useCallback(async (accountId: string) => {
    await api.switchAccount(accountId);
    // Data on screen belongs to the old account; a full reload is the simplest way to drop all of it.
    window.location.assign("/overview");
  }, []);

  const can = useCallback((p: Permission) => !!me?.permissions.includes(p), [me]);

  return <Ctx.Provider value={{ me, can, refresh, switchAccount }}>{children}</Ctx.Provider>;
}

export function useMe(): MeState {
  return useContext(Ctx);
}

/** Small note shown in place of an action the current role can't take. */
export function RoleNote({ action }: { action: string }) {
  const { me } = useMe();
  if (!me) return null;
  return (
    <span className="muted small" title="Ask an account admin to change your role.">
      Your role ({me.account.role}) can&apos;t {action}.
    </span>
  );
}

/** How an account is named in the UI: your own is "Personal", a team is named after its owner. */
export function accountLabel(a: Pick<Account, "personal" | "owner_email">): string {
  return a.personal ? "Personal" : `${a.owner_email}'s team`;
}

export const ROLE_LABEL: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  developer: "Developer",
  viewer: "Viewer",
};
