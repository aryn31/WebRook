import type { Metadata } from "next";
import { cookies } from "next/headers";
import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = { title: "Log in" };

export default async function LoginPage() {
  const hasSession = (await cookies()).has("hf_session");
  return <AuthForm mode="login" hasSession={hasSession} />;
}
