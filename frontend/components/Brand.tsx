import Link from "next/link";

/** The HookFlow mark: a signal wave leaving a source and arriving at a destination. */
export function LogoMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className="logo-mark">
      <rect width="24" height="24" rx="7" className="logo-tile" />
      <path d="M5.5 15.5c2.2 0 2.6-7 6.5-7s4.3 7 6.5 7" className="logo-wave" />
      <circle cx="5.5" cy="15.5" r="1.6" className="logo-src" />
      <circle cx="18.5" cy="15.5" r="2.1" className="logo-dst" />
    </svg>
  );
}

export function Brand({ href = "/", size = 24, className = "" }: { href?: string; size?: number; className?: string }) {
  return (
    <Link href={href} className={`brand ${className}`}>
      <LogoMark size={size} />
      <span className="brand-word">HookFlow</span>
    </Link>
  );
}
