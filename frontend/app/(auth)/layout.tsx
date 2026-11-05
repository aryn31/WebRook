import { Brand } from "@/components/Brand";
import { FlowDiagram } from "@/components/FlowDiagram";
import { FreshOnBack } from "@/components/FreshOnBack";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-split">
      <FreshOnBack />
      <aside className="auth-aside" aria-hidden>
        <Brand className="auth-aside-brand" />
        <div className="auth-aside-body">
          <FlowDiagram compact />
          <p className="auth-quote">
            Send the event once.
            <br />
            <em>We make sure it arrives.</em>
          </p>
        </div>
        <ul className="auth-facts">
          <li>Signed with HMAC-SHA256</li>
          <li>Retried with exponential backoff</li>
          <li>Every attempt recorded</li>
        </ul>
      </aside>
      <main className="auth-main">
        <ThemeToggle className="auth-theme" />
        <Brand className="auth-main-brand" />
        <div className="auth-card">{children}</div>
      </main>
    </div>
  );
}
