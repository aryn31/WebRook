import type { Metadata } from "next";
import Link from "next/link";
import { Contact, LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Terms of service", description: "The rules for using HookFlow." };

export default function TermsPage() {
  return (
    <LegalPage title="Terms of service">
      <p>
        By creating a HookFlow account you agree to these terms. HookFlow is an independent project offered free of
        charge.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>Use an email address you own; you&apos;ll be asked to confirm it.</li>
        <li>Keep your password and API keys secret. You&apos;re responsible for what&apos;s done with them.</li>
        <li>You&apos;re responsible for the people you invite to your team and the roles you give them.</li>
      </ul>

      <h2>Acceptable use</h2>
      <p>Don&apos;t use HookFlow to:</p>
      <ul>
        <li>send requests to servers you don&apos;t own or aren&apos;t allowed to send to;</li>
        <li>send spam, malware, or anything illegal;</li>
        <li>attack, overload or probe other systems, including HookFlow itself;</li>
        <li>get around the rate limits and quotas.</li>
      </ul>
      <p>Accounts that break these rules may be suspended or deleted without notice.</p>

      <h2>Limits and availability</h2>
      <p>
        The service runs within the limits listed on the <Link href="/platform#limits">Platform</Link> page, which may
        change. It&apos;s provided on a best-effort basis: there&apos;s no uptime guarantee, and the free hosting it
        runs on can pause or restart. Don&apos;t rely on it as the only copy of important data.
      </p>

      <h2>Your data</h2>
      <p>
        You own what you send through HookFlow. You allow HookFlow to store and transmit it only to provide the
        service, as described in the <Link href="/privacy">privacy policy</Link>.
      </p>

      <h2>No warranty</h2>
      <p>
        HookFlow is provided &quot;as is&quot;, without warranties of any kind. To the extent the law allows, its
        operator isn&apos;t liable for lost data, missed or duplicate deliveries, or any indirect damages from using
        it.
      </p>

      <h2>Ending</h2>
      <p>
        You can stop using HookFlow at any time and ask for your account to be deleted. The service may be changed
        or shut down; if so, we&apos;ll try to give notice on this site.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about these terms: <Contact />.
      </p>
    </LegalPage>
  );
}
