import * as React from "react";
import { cn } from "cn";

interface EmptyStateProps {
  icon?: React.ElementType;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}

/** What to do when a list is empty: a short title, one line of direction, an action. */
export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-1 rounded-lg border border-border bg-card px-6 py-10",
        className
      )}
    >
      {Icon && <Icon className="mb-2 size-5 text-muted-foreground" aria-hidden />}
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-3 flex items-center gap-2">{action}</div>}
    </div>
  );
}
