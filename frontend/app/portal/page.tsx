import type { Metadata } from "next";
import { PortalApp } from "./PortalApp";

export const metadata: Metadata = { title: "Webhooks", robots: { index: false, follow: false } };

export default function PortalPage() {
  return <PortalApp />;
}
