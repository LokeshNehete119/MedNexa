"use client";

import * as React from "react";
import Link from "next/link";
import { Plus, Search } from "lucide-react";
import { toast } from "sonner";
import { deleteDoctor, listDoctors, updateDoctor, type DoctorOut } from "@/lib/api";
import { useHospital } from "@/contexts/HospitalContext";
import { formatTime } from "@/lib/format";
import { describeDays } from "@/lib/weekdays";
import { PageHeader } from "@/components/page-header";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DoctorFormDialog } from "@/components/doctors/DoctorFormDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

export default function DoctorsPage() {
  const { hospitalId } = useHospital();
  const [doctors, setDoctors] = React.useState<DoctorOut[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [search, setSearch] = React.useState("");
  const [department, setDepartment] = React.useState("");
  const [showInactive, setShowInactive] = React.useState(false);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<DoctorOut | null>(null);
  const [deactivating, setDeactivating] = React.useState<DoctorOut | null>(null);

  const load = React.useCallback(async () => {
    if (!hospitalId) return;
    try {
      const page = await listDoctors({ hospital_id: hospitalId, include_inactive: true, limit: 200 });
      setDoctors(page.items);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Doctors could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [hospitalId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const reactivate = async (doctor: DoctorOut) => {
    try {
      await updateDoctor(doctor.id, { is_active: true });
      toast.success(`${doctor.name} can be booked again`);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The doctor could not be reactivated.");
    }
  };

  const departments = [...new Set(doctors.map((d) => d.department))].sort();
  const q = search.trim().toLowerCase();
  const inactiveCount = doctors.filter((d) => !d.is_active).length;
  const shown = doctors.filter(
    (d) =>
      (showInactive || d.is_active) &&
      (!department || d.department === department) &&
      (!q || [d.name, d.speciality, d.department].some((field) => field.toLowerCase().includes(q)))
  );

  return (
    <>
      <PageHeader
        title="Doctors"
        description="Working days, hours and daily limits here decide which slots patients can book."
        actions={
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus /> Add doctor
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            aria-label="Search doctors"
            placeholder="Name, speciality or department"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 bg-card pl-8"
          />
        </div>
        <NativeSelect
          aria-label="Department"
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          className="w-48"
        >
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </NativeSelect>
        {inactiveCount > 0 && (
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              className="size-3.5 accent-primary"
            />
            Show {inactiveCount} inactive
          </label>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <div className="h-72 animate-pulse" />
        ) : shown.length === 0 ? (
          <div className="px-6 py-10">
            <p className="text-sm font-semibold">{doctors.length ? "No doctors match" : "No doctors yet"}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {doctors.length
                ? "Clear the search or pick another department."
                : "Add a doctor with their working days and hours, and patients can start booking."}
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Doctor</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Works</TableHead>
                <TableHead className="text-right">Patients a day</TableHead>
                <TableHead className="text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((d) => (
                <TableRow key={d.id} className={cn(!d.is_active && "text-muted-foreground")}>
                  <TableCell>
                    <Link href={`/doctors/${d.id}`} className="font-medium text-foreground hover:underline">
                      {d.name}
                    </Link>
                    <span className="block text-[13px] text-muted-foreground">
                      {d.speciality}
                      {d.qualification && `, ${d.qualification}`}
                    </span>
                  </TableCell>
                  <TableCell>{d.department}</TableCell>
                  <TableCell>
                    {d.is_active ? (
                      <>
                        <span className="block">{describeDays(d.available_days)}</span>
                        <span className="text-[13px] text-muted-foreground">
                          <time>{formatTime(d.slot_start_time)}</time> to <time>{formatTime(d.slot_end_time)}</time>,{" "}
                          {d.slot_duration_minutes} min each
                        </span>
                      </>
                    ) : (
                      "Inactive, not bookable"
                    )}
                  </TableCell>
                  <TableCell className="text-right">{d.max_daily_appointments}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Link
                        href={`/doctors/${d.id}/schedule`}
                        className="inline-flex h-7 items-center rounded-md px-2.5 text-[0.8rem] font-medium hover:bg-muted"
                      >
                        Schedule
                      </Link>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditing(d);
                          setFormOpen(true);
                        }}
                      >
                        Edit
                      </Button>
                      {d.is_active ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setDeactivating(d)}
                        >
                          Deactivate
                        </Button>
                      ) : (
                        <Button variant="ghost" size="sm" onClick={() => reactivate(d)}>
                          Reactivate
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <DoctorFormDialog open={formOpen} onOpenChange={setFormOpen} doctor={editing} onSuccess={load} />
      <ConfirmDialog
        open={!!deactivating}
        onOpenChange={(open) => !open && setDeactivating(null)}
        title={`Deactivate ${deactivating?.name ?? "doctor"}?`}
        description="No new appointments can be booked with them, at the desk or by phone. Existing appointments stay as they are. You can reactivate them later."
        confirmLabel="Deactivate"
        onConfirm={async () => {
          if (!deactivating) return;
          try {
            await deleteDoctor(deactivating.id);
            toast.success(`${deactivating.name} deactivated`);
            load();
          } catch (err) {
            toast.error(err instanceof Error ? err.message : "The doctor could not be deactivated.");
          }
        }}
      />
    </>
  );
}
