"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const { isAuthenticated, login, isLoading } = useAuth();
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (!isLoading && isAuthenticated) router.replace("/dashboard");
  }, [isAuthenticated, isLoading, router]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    setSubmitting(true);
    const result = await login(String(form.get("email")), String(form.get("password")));
    if (result.success) {
      router.replace("/dashboard");
    } else {
      setError(result.error ?? "Incorrect email or password");
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <p className="text-[13px] font-medium text-primary">MedNexa</p>
        <h1 className="mt-1 text-[22px] font-semibold">Sign in to the front desk</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Appointments, doctors&apos; schedules and the AI receptionist&apos;s calls.
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4 rounded-lg border border-border bg-card p-6">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" name="email" type="email" autoComplete="username" required autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input id="password" name="password" type="password" autoComplete="current-password" required />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" size="lg" className="w-full" disabled={submitting || isLoading}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        <p className="mt-4 text-[13px] text-muted-foreground">
          Forgotten the password? It is set by whoever runs this server (MEDNEXA_ADMIN_PASSWORD).
        </p>
      </div>
    </main>
  );
}
