"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import {
  getDoctor,
  listAppointments,
  type AppointmentOut,
  type DoctorDetailOut,
} from "@/lib/api";
import { useHospital } from "@/contexts/HospitalContext";
import { todayIn } from "@/lib/dates";
import { formatDate, formatTime } from "@/lib/format";
import { describeDays } from "@/lib/weekdays";
import { PageHeader } from "@/components/page-header";
import { BackLink, DetailList } from "@/components/detail-list";
import { DoctorFormDialog } from "@/components/doctors/DoctorFormDialog";
import { Button, buttonVariants } from "@/components/ui/button";

export default function DoctorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { hospital } = useHospital();
  const [doctor, setDoctor] = React.useState<DoctorDetailOut | null>(null);
  const [upcoming, setUpcoming] = React.useState<AppointmentOut[]>([]);
  const [upcomingTotal, setUpcomingTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [editOpen, setEditOpen] = React.useState(false);
  const today = todayIn(hospital?.timezone);

  const load = React.useCallback(async () => {
    try {
      const [d, appts] = await Promise.all([
        getDoctor(id),
        listAppointments({ doctor_id: id, date_from: today, status: "BOOKED", limit: 10 }),
      ]);
      setDoctor(d);
      setUpcoming(appts.items);
      setUpcomingTotal(appts.total);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The doctor could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [id, today]);

  React.useEffect(() => {
    load();
  }, [load]);

  const back = <BackLink href="/doctors">Doctors</BackLink>;
  if (loading) return <div className="h-80 animate-pulse rounded-lg border border-border bg-card" />;
  if (!doctor) {
    return (
      <>
        <PageHeader back={back} title="Doctor not found" />
        <p className="text-sm text-muted-foreground">They may have been removed, or the link is wrong.</p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        back={back}
        title={doctor.name}
        description={
          doctor.is_active
            ? `${doctor.speciality}, ${doctor.department}`
            : "Inactive: no new appointments can be booked"
        }
        actions={
          <>
            <Link href={`/doctors/${doctor.id}/schedule`} className={buttonVariants({ variant: "outline" })}>
              Schedule and leave
            </Link>
            <Button onClick={() => setEditOpen(true)}>Edit details</Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-border bg-card">
          <h2 className="border-b border-border px-4 py-3 text-[15px] font-semibold">Profile and hours</h2>
          <DetailList
            items={[
              { label: "Speciality", value: doctor.speciality },
              { label: "Qualification", value: doctor.qualification },
              { label: "Department", value: doctor.department },
              { label: "Works", value: describeDays(doctor.available_days) },
              {
                label: "Hours",
                value: (
                  <>
                    <time>{formatTime(doctor.slot_start_time)}</time> to <time>{formatTime(doctor.slot_end_time)}</time>
                  </>
                ),
              },
              { label: "Each appointment", value: `${doctor.slot_duration_minutes} minutes` },
              { label: "Patients a day", value: `Up to ${doctor.max_daily_appointments}` },
              { label: "About", value: doctor.bio },
            ]}
          />
        </section>

        <div className="space-y-6">
          <section className="rounded-lg border border-border bg-card">
            <h2 className="border-b border-border px-4 py-3 text-[15px] font-semibold">Leave and changed hours</h2>
            {doctor.upcoming_overrides.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted-foreground">
                Working the usual hours. Add leave on the{" "}
                <Link href={`/doctors/${doctor.id}/schedule`} className="text-foreground underline">
                  schedule page
                </Link>
                .
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {doctor.upcoming_overrides.map((o) => (
                  <li key={o.id} className="flex justify-between gap-4 px-4 py-2.5 text-sm">
                    <span>{formatDate(o.date)}</span>
                    <span className="text-right text-muted-foreground">
                      {o.is_available ? (
                        <>
                          <time>{formatTime(o.start_time ?? doctor.slot_start_time)}</time> to{" "}
                          <time>{formatTime(o.end_time ?? doctor.slot_end_time)}</time>
                        </>
                      ) : (
                        <span className="text-status-cancelled">Not working</span>
                      )}
                      {o.override_reason && `, ${o.override_reason}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-border bg-card">
            <h2 className="border-b border-border px-4 py-3 text-[15px] font-semibold">Coming up</h2>
            {upcoming.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted-foreground">No upcoming appointments.</p>
            ) : (
              <ul className="divide-y divide-border">
                {upcoming.map((a) => (
                  <li key={a.id}>
                    <Link
                      href={`/appointments/${a.id}`}
                      className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 px-4 py-2.5 text-sm hover:bg-muted/40"
                    >
                      <span className="tabular text-base font-semibold">{a.token_number}</span>
                      <span className="truncate font-medium">{a.patient_name}</span>
                      <span className="tabular text-muted-foreground">
                        {formatDate(a.appointment_date)}, {formatTime(a.appointment_time)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {upcomingTotal > upcoming.length && (
              <p className="border-t border-border px-4 py-2.5 text-[13px] text-muted-foreground">
                and {upcomingTotal - upcoming.length} more
              </p>
            )}
          </section>
        </div>
      </div>

      <DoctorFormDialog open={editOpen} onOpenChange={setEditOpen} doctor={doctor} onSuccess={load} />
    </>
  );
}
