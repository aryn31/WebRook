import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ForgotPasswordForm } from "./ForgotPasswordForm";

export const metadata: Metadata = { title: "Reset your password" };

export default async function ForgotPasswordPage() {
  const hasSession = (await cookies()).has("hf_session");
  return <ForgotPasswordForm hasSession={hasSession} />;
}
