"use client";

import * as React from "react";
import { Plus, Search } from "lucide-react";
import { toast } from "sonner";
import { deleteHospitalInfo, listHospitalInfo, updateHospitalInfo, type HospitalInfoOut } from "@/lib/api";
import { useHospital } from "@/contexts/HospitalContext";
import { PageHeader } from "@/components/page-header";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { HospitalInfoDialog } from "@/components/hospital-info/HospitalInfoDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export default function HospitalInfoPage() {
  const { hospitalId } = useHospital();
  const [entries, setEntries] = React.useState<HospitalInfoOut[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [search, setSearch] = React.useState("");
  const [showUnused, setShowUnused] = React.useState(false);

  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<HospitalInfoOut | null>(null);
  const [defaultCategory, setDefaultCategory] = React.useState<string | undefined>();
  const [retiring, setRetiring] = React.useState<HospitalInfoOut | null>(null);

  const load = React.useCallback(async () => {
    if (!hospitalId) return;
    try {
      const page = await listHospitalInfo(hospitalId, { include_inactive: true, limit: 200 });
      setEntries(page.items);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Hospital information could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [hospitalId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const openDialog = (entry: HospitalInfoOut | null, category?: string) => {
    setEditing(entry);
    setDefaultCategory(category);
    setDialogOpen(true);
  };

  const restore = async (entry: HospitalInfoOut) => {
    try {
      await updateHospitalInfo(entry.id, { is_active: true });
      toast.success("The receptionist will use this answer again");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The answer could not be restored.");
    }
  };

  const categories = [...new Set(entries.map((e) => e.category))].sort();
  const unusedCount = entries.filter((e) => !e.is_active).length;
  const q = search.trim().toLowerCase();
  const shown = entries.filter(
    (e) =>
      (showUnused || e.is_active) &&
      (!q || [e.question, e.answer, e.category].some((field) => field.toLowerCase().includes(q)))
  );
  const groups = categories
    .map((category) => ({ category, items: shown.filter((e) => e.category === category) }))
    .filter((g) => g.items.length > 0);

  return (
    <>
      <PageHeader
        title="Hospital info"
        description="What the AI receptionist tells callers about timings, directions, parking, billing and more. Changes apply to the next call."
        actions={
          <Button onClick={() => openDialog(null)}>
            <Plus /> Add answer
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            aria-label="Search answers"
            placeholder="Search questions and answers"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 bg-card pl-8"
          />
        </div>
        {unusedCount > 0 && (
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={showUnused}
              onChange={(e) => setShowUnused(e.target.checked)}
              className="size-3.5 accent-primary"
            />
            Show {unusedCount} not in use
          </label>
        )}
      </div>

      {loading ? (
        <div className="h-72 animate-pulse rounded-lg border border-border bg-card" />
      ) : groups.length === 0 ? (
        <div className="rounded-lg border border-border bg-card px-6 py-10">
          <p className="text-sm font-semibold">{entries.length ? "Nothing matches" : "No answers yet"}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {entries.length
              ? "Try other words."
              : "Add the questions callers ask most (OPD timings, parking, reports), and the receptionist will answer them."}
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <section key={group.category} className="rounded-lg border border-border bg-card">
              <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
                <h2 className="text-[15px] font-semibold">{group.category}</h2>
                <Button variant="ghost" size="sm" onClick={() => openDialog(null, group.category)}>
                  <Plus /> Add
                </Button>
              </header>
              <ul className="divide-y divide-border">
                {group.items.map((entry) => (
                  <li
                    key={entry.id}
                    className={cn("grid gap-3 px-4 py-3 sm:grid-cols-[1fr_auto]", !entry.is_active && "opacity-60")}
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium">
                        {entry.question}
                        {!entry.is_active && <span className="ml-2 font-normal text-muted-foreground">(not in use)</span>}
                      </p>
                      <p className="mt-1 max-w-[70ch] text-sm whitespace-pre-line text-muted-foreground">{entry.answer}</p>
                    </div>
                    <div className="flex items-start gap-1">
                      <Button variant="ghost" size="sm" onClick={() => openDialog(entry)}>
                        Edit
                      </Button>
                      {entry.is_active ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setRetiring(entry)}
                        >
                          Stop using
                        </Button>
                      ) : (
                        <Button variant="ghost" size="sm" onClick={() => restore(entry)}>
                          Use again
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <HospitalInfoDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        entry={editing}
        defaultCategory={defaultCategory}
        existingCategories={categories}
        onSuccess={load}
      />
      <ConfirmDialog
        open={!!retiring}
        onOpenChange={(open) => !open && setRetiring(null)}
        title="Stop using this answer?"
        description="The receptionist won't give this answer on calls any more. It stays here, so you can use it again later."
        confirmLabel="Stop using"
        onConfirm={async () => {
          if (!retiring) return;
          try {
            await deleteHospitalInfo(retiring.id);
            toast.success("The receptionist won't use this answer");
            load();
          } catch (err) {
            toast.error(err instanceof Error ? err.message : "The answer could not be changed.");
          }
        }}
      />
    </>
  );
}
