"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";
import { Sidebar } from "@/components/layout/Sidebar";
import { HospitalSetup } from "@/components/hospital-setup";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { useHospital } from "@/contexts/HospitalContext";

export default function DashboardShellLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const { hospital, needsSetup, error, refreshHospital } = useHospital();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [retrying, setRetrying] = React.useState(false);

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/login");
  }, [isAuthenticated, isLoading, router]);

  if (isLoading || !isAuthenticated) return <div className="min-h-screen bg-background" />;

  const retry = async () => {
    setRetrying(true);
    try {
      await refreshHospital();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <div className="hidden h-full shrink-0 md:flex">
        <Sidebar />
      </div>

      {menuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="fixed inset-0 bg-black/40" onClick={() => setMenuOpen(false)} />
          <div className="relative z-10 h-full">
            <Sidebar onNavigate={() => setMenuOpen(false)} />
            <button
              type="button"
              onClick={() => setMenuOpen(false)}
              className="absolute top-4 right-3 rounded-md p-1.5 text-muted-foreground hover:bg-sidebar-accent"
              aria-label="Close menu"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
      )}

      <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex h-12 items-center gap-2 border-b border-border px-4 md:hidden">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            className="-ml-1.5 rounded-md p-1.5 text-muted-foreground hover:bg-muted"
            aria-label="Open menu"
          >
            <Menu className="size-5" />
          </button>
          <span className="truncate text-sm font-semibold">{hospital?.name ?? "MedNexa"}</span>
        </div>

        <main className="flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-8">
          <div className="mx-auto w-full max-w-6xl">
            {error && (
              <div
                role="alert"
                className="mb-6 flex flex-col gap-3 rounded-lg border border-status-cancelled/30 bg-card px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
              >
                <p>
                  <span className="font-medium">The server can&apos;t be reached.</span>{" "}
                  <span className="text-muted-foreground">
                    Changes won&apos;t be saved and figures may be out of date. ({error})
                  </span>
                </p>
                <Button variant="outline" size="sm" onClick={retry} disabled={retrying}>
                  {retrying ? "Retrying…" : "Retry"}
                </Button>
              </div>
            )}
            {needsSetup ? <HospitalSetup /> : children}
          </div>
        </main>
      </div>
    </div>
  );
}
