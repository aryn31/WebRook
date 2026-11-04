import type { Metadata } from "next";
import { VerifyEmailForm } from "./VerifyEmailForm";

export const metadata: Metadata = { title: "Verify your email" };

export default function VerifyEmailPage() {
  return <VerifyEmailForm />;
}
