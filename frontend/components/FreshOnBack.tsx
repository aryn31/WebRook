"use client";

import { useEffect } from "react";

/**
 * Browsers can restore a page from memory on Back without asking the server, showing it exactly as it was
 * (for example, the dashboard after logging out, or the log-in form after logging in). Reload instead, so the
 * session is checked again.
 */
export function FreshOnBack() {
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) window.location.reload();
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);
  return null;
}
