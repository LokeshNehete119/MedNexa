"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  CalendarDays,
  ClipboardList,
  Info,
  LogOut,
  Phone,
  Settings,
  Stethoscope,
  Users,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { useAuth } from "@/contexts/AuthContext";
import { useHospital } from "@/contexts/HospitalContext";
import { cn } from "@/lib/utils";
import type { PhoneLineState } from "@/app/api/phone-line/route";

const NAV = [
  { name: "Today", href: "/dashboard", icon: ClipboardList },
  { name: "Appointments", href: "/appointments", icon: CalendarDays },
  { name: "Doctors", href: "/doctors", icon: Stethoscope },
  { name: "Patients", href: "/patients", icon: Users },
  { name: "Calls", href: "/call-logs", icon: Phone },
  { name: "Hospital info", href: "/hospital-info", icon: Info },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "Settings", href: "/settings", icon: Settings },
];

const PHONE_LINE: Record<PhoneLineState, { label: string; detail: string; tone: string }> = {
  answering: { label: "Phone line answering", detail: "The AI receptionist is taking calls.", tone: "bg-status-booked" },
  needs_setup: {
    label: "Phone line not linked",
    detail: "Set MEDNEXA_TEL_HOSPITAL_ID on the telephony service.",
    tone: "bg-status-moved",
  },
  offline: { label: "Phone line offline", detail: "Calls are not being answered.", tone: "bg-status-cancelled" },
  not_configured: { label: "No phone line", detail: "The telephony service is not set up.", tone: "bg-status-done" },
};

function usePhoneLine(): PhoneLineState | null {
  const [state, setState] = React.useState<PhoneLineState | null>(null);
  React.useEffect(() => {
    let cancelled = false;
    const check = () =>
      fetch("/api/phone-line", { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : null))
        .then((data: { state: PhoneLineState } | null) => !cancelled && data && setState(data.state))
        .catch(() => !cancelled && setState("offline"));
    check();
    const timer = setInterval(check, 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  return state;
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { hospital } = useHospital();
  const { user, logout } = useAuth();
  const phoneLine = usePhoneLine();
  const line = phoneLine ? PHONE_LINE[phoneLine] : null;

  return (
    <aside className="flex h-full w-60 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="px-5 pt-5 pb-4">
        <p className="text-[13px] font-medium text-primary">MedNexa</p>
        <p className="mt-0.5 truncate text-[15px] leading-snug font-semibold" title={hospital?.name}>
          {hospital?.name ?? " "}
        </p>
      </div>

      <nav className="flex-1 overflow-y-auto px-3" aria-label="Main">
        <ul className="space-y-0.5">
          {NAV.map(({ name, href, icon: Icon }) => {
            const active = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
            return (
              <li key={href}>
                <Link
                  href={href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-sidebar-accent font-semibold text-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-primary"
                      : "text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
                  )}
                >
                  <Icon className={cn("size-4 shrink-0", active && "text-primary")} aria-hidden />
                  {name}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="space-y-3 border-t border-sidebar-border px-5 py-4">
        {line && (
          <div title={line.detail}>
            <p className="flex items-center gap-2 text-[13px] font-medium">
              <span aria-hidden className={cn("size-1.5 rounded-full", line.tone)} />
              {line.label}
            </p>
            <p className="mt-0.5 pl-3.5 text-xs text-muted-foreground">{line.detail}</p>
          </div>
        )}
        <div className="flex items-center gap-1">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium">{user?.name}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
          </div>
          <ThemeToggle />
          <button
            type="button"
            onClick={logout}
            className="flex size-8 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
