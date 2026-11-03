import { MeProvider } from "@/components/MeContext";
import { Sidebar } from "@/components/Sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <MeProvider>
      <div className="shell">
        <Sidebar />
        <main className="main">{children}</main>
      </div>
    </MeProvider>
  );
}
