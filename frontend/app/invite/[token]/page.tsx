import type { Metadata } from "next";
import { Brand } from "@/components/Brand";
import { InviteCard } from "./InviteCard";

export const metadata: Metadata = { title: "Join a team" };

// Standalone page (no dashboard sidebar). The middleware sends visitors without a session to
// /login?next=/invite/<token>, so by the time this renders there is usually a logged-in user.
export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <main className="invite-page">
      <Brand className="invite-brand" />
      <div className="auth-card invite-card">
        <InviteCard token={token} />
      </div>
    </main>
  );
}
