export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="brand brand-lg">
          <span className="brand-mark" aria-hidden>H</span> HookFlow
        </div>
        {children}
      </div>
    </div>
  );
}
