import { MeProvider } from "@/components/MeContext";
import { Sidebar } from "@/components/Sidebar";
import { FreshOnBack } from "@/components/FreshOnBack";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <MeProvider>
      <FreshOnBack />
      <div className="shell">
        <Sidebar />
        <main className="main">{children}</main>
      </div>
    </MeProvider>
  );
}
