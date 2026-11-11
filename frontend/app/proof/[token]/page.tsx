import type { Metadata } from "next";
import { ProofPage } from "./ProofPage";

export const metadata: Metadata = {
  title: "Proof of delivery · HookFlow",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ProofPage token={token} />;
}
