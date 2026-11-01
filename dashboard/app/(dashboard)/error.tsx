"use client";

import * as React from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error("Dashboard error caught by boundary:", error);
  }, [error]);

  return (
    <div className="max-w-lg py-10">
      <h1 className="text-[22px] font-semibold">This page couldn&apos;t be shown</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {error.message || "Something failed while loading it."} Try again; if it keeps happening, check that the
        API server is running and that this server&apos;s BACKEND_URL points to it.
      </p>
      {error.digest && <p className="mt-2 text-[13px] text-muted-foreground">Reference: {error.digest}</p>}
      <div className="mt-5 flex gap-2">
        <Button onClick={() => reset()}>Try again</Button>
        <Link href="/dashboard" className={buttonVariants({ variant: "outline" })}>
          Go to Today
        </Link>
      </div>
    </div>
  );
}
