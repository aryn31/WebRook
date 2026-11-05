/** A small coloured tile showing what kind of thing an audit entry is about. */
const KINDS: { prefix: string; kind: string; path: string }[] = [
  { prefix: "auth.", kind: "auth", path: "M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6l-7-3Z" },
  { prefix: "api_key.", kind: "key", path: "M8 19a4 4 0 1 1 0-8 4 4 0 0 1 0 8Zm3-7 8.5-8.5M16 7l2.5 2.5" },
  { prefix: "endpoint.", kind: "endpoint", path: "M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm0-5a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" },
  { prefix: "deliver", kind: "delivery", path: "M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4" },
  { prefix: "event.", kind: "delivery", path: "M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4" },
  { prefix: "team.", kind: "team", path: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-5.5 8.5a5.5 5.5 0 0 1 11 0M16 5.5a3 3 0 0 1 0 5.8M18 14.5a5.5 5.5 0 0 1 2.5 5" },
  { prefix: "member", kind: "team", path: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-5.5 8.5a5.5 5.5 0 0 1 11 0M16 5.5a3 3 0 0 1 0 5.8M18 14.5a5.5 5.5 0 0 1 2.5 5" },
  { prefix: "invite", kind: "team", path: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-5.5 8.5a5.5 5.5 0 0 1 11 0M19 8v6M16 11h6" },
];
const OTHER = "M7 3h8l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z";

export function AuditIcon({ action }: { action: string }) {
  const k = KINDS.find((x) => action.startsWith(x.prefix));
  return (
    <span className={`audit-icon ai-${k?.kind ?? "other"}`} aria-hidden>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d={k?.path ?? OTHER} />
      </svg>
    </span>
  );
}
