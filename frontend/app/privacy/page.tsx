import type { Metadata } from "next";
import { Contact, LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Privacy policy", description: "What HookFlow stores about you and why." };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy">
      <p>
        HookFlow is a webhook delivery service run as an independent project. This page explains what it stores,
        why, and for how long. HookFlow doesn&apos;t sell your data, show ads, or use tracking or analytics tools.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>
          <strong>Your account:</strong> your email address and your password, stored only as a one-way hash (Argon2),
          so nobody can read it.
        </li>
        <li>
          <strong>Logins:</strong> for each browser you log in from, its IP address, its browser name (user agent)
          and when it was last used. You can see these and sign them out on the Security page.
        </li>
        <li>
          <strong>Your webhooks:</strong> the endpoints you add, the events you send, and the result of every delivery
          attempt, including the first 4 KiB of each response.
        </li>
        <li>
          <strong>Audit log:</strong> important actions in your account (such as creating an API key), with the IP
          address they came from.
        </li>
        <li>
          <strong>Team:</strong> if you invite someone, their email address and role.
        </li>
      </ul>

      <h2>Why</h2>
      <p>
        Only to run the service: to log you in, deliver your webhooks, show you their history, keep your account
        secure, and stop abuse. Your email address is used to send you verification codes. It isn&apos;t used for
        marketing.
      </p>

      <h2>How long</h2>
      <ul>
        <li>Events, deliveries and attempts are deleted after 30 days.</li>
        <li>Audit log entries are deleted after one year.</li>
        <li>Login sessions end after 7 days, or when you sign them out.</li>
        <li>Your account stays until you ask for it to be deleted.</li>
      </ul>

      <h2>Cookies</h2>
      <p>
        One cookie, <code>hf_session</code>, keeps you logged in. It&apos;s only sent to HookFlow and can&apos;t be
        read by scripts on the page. There are no advertising or tracking cookies.
      </p>

      <h2>Who else handles your data</h2>
      <ul>
        <li>Render hosts the API and the database.</li>
        <li>Vercel hosts the website and dashboard.</li>
        <li>Google (Gmail) sends verification emails.</li>
      </ul>
      <p>
        Webhooks are sent to the endpoint addresses you choose. What happens to the data there is up to whoever runs
        those servers.
      </p>

      <h2>Your choices</h2>
      <p>
        You can change your password and sign out devices on the Security page. To get a copy of your data or have
        your account and its data deleted, contact <Contact />.
      </p>

      <h2>Changes</h2>
      <p>If this policy changes, the date at the top changes too.</p>
    </LegalPage>
  );
}
