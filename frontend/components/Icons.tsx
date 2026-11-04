// Small line icons (24px grid, 1.6 stroke). Decorative: always aria-hidden.
type P = { size?: number; className?: string };

function Svg({ size = 18, className, children }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden className={className}>
      {children}
    </svg>
  );
}

export const IconOverview = (p: P) => (
  <Svg {...p}><path d="M3 12h4l2.5-6 5 12 2.5-6h4" /></Svg>
);
export const IconEvents = (p: P) => (
  <Svg {...p}><path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z" /></Svg>
);
export const IconDeliveries = (p: P) => (
  <Svg {...p}><path d="M4 7h13m0 0-3.5-3.5M17 7l-3.5 3.5M20 17H7m0 0 3.5-3.5M7 17l3.5 3.5" /></Svg>
);
export const IconEndpoints = (p: P) => (
  <Svg {...p}><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.2" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></Svg>
);
export const IconKey = (p: P) => (
  <Svg {...p}><circle cx="8" cy="15" r="4" /><path d="m11 12 8.5-8.5M16 7l2.5 2.5M14 9l2 2" /></Svg>
);
export const IconTeam = (p: P) => (
  <Svg {...p}><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0M15.5 5.6a3.2 3.2 0 0 1 0 5.8M17.5 14.4a5.5 5.5 0 0 1 3 5.1" /></Svg>
);
export const IconShield = (p: P) => (
  <Svg {...p}><path d="M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6l-7-3Z" /><path d="m9 12 2.2 2.2L15.5 10" /></Svg>
);
export const IconAudit = (p: P) => (
  <Svg {...p}><path d="M7 3h8l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" /><path d="M14.5 3v4.5H19M9 12h6M9 16h4" /></Svg>
);
export const IconArrow = (p: P) => (
  <Svg {...p}><path d="M5 12h14m-5-5 5 5-5 5" /></Svg>
);
export const IconCheck = (p: P) => (
  <Svg {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></Svg>
);
export const IconLogout = (p: P) => (
  <Svg {...p}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 16l-4-4 4-4M6 12h10" /></Svg>
);
export const IconHome = (p: P) => (
  <Svg {...p}><path d="M4 11 12 4l8 7M6 9.5V20h4.5v-5.5h3V20H18V9.5" /></Svg>
);
