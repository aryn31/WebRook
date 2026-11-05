/** Two letters from an email address, e.g. "ana.kim@x.com" → "AK". */
export function initials(email: string): string {
  const name = email.split("@")[0].replace(/[^a-zA-Z0-9]+/g, " ").trim();
  const parts = name.split(" ").filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return (letters || "?").toUpperCase();
}

// A stable colour per person, so the same teammate always looks the same.
const HUES = [72, 150, 200, 260, 320, 25];

export function Avatar({ email, size = 28, self }: { email: string; size?: number; self?: boolean }) {
  let h = 0;
  for (const ch of email) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = HUES[h % HUES.length];
  return (
    <span className={`avatar${self ? " avatar-self" : ""}`} aria-hidden
      style={{ width: size, height: size, fontSize: size * 0.38, ...(self ? {} : { ["--av-hue" as string]: hue }) }}>
      {initials(email)}
    </span>
  );
}
