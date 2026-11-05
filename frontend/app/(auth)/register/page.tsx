import type { Metadata } from "next";
import { cookies } from "next/headers";
import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = { title: "Create account" };

export default async function RegisterPage() {
  const hasSession = (await cookies()).has("hf_session");
  return <AuthForm mode="register" hasSession={hasSession} />;
}
