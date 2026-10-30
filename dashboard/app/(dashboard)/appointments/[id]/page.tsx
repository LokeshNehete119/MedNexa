"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { getAppointment, type AppointmentOut } from "@/lib/api";
import { formatDate, formatDateTime, formatTime } from "@/lib/format";
import { PageHeader } from "@/components/page-header";
import { BackLink, DetailList } from "@/components/detail-list";
import { AppointmentStatusLabel, BookingSourceLabel } from "@/components/status";
import { CancelAppointmentDialog } from "@/components/appointments/CancelAppointmentDialog";
import { RescheduleAppointmentDialog } from "@/components/appointments/RescheduleAppointmentDialog";
import { Button } from "@/components/ui/button";

export default function AppointmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [appointment, setAppointment] = React.useState<AppointmentOut | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [rescheduleOpen, setRescheduleOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setAppointment(await getAppointment(id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The appointment could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  React.useEffect(() => {
    load();
  }, [load]);

  const back = <BackLink href="/appointments">Appointments</BackLink>;

  if (loading) return <div className="h-80 animate-pulse rounded-lg border border-border bg-card" />;
  if (!appointment) {
    return (
      <>
        <PageHeader back={back} title="Appointment not found" />
        <p className="text-sm text-muted-foreground">It may have been removed, or the link is wrong.</p>
      </>
    );
  }

  const a = appointment;
  return (
    <>
      <PageHeader
        back={back}
        title={a.patient_name}
        description={
          <>
            {formatDate(a.appointment_date)} at <time>{formatTime(a.appointment_time)}</time> with {a.doctor_name}
          </>
        }
        actions={
          a.status === "BOOKED" && (
            <>
              <Button variant="outline" onClick={() => setRescheduleOpen(true)}>
                Reschedule
              </Button>
              <Button variant="destructive" onClick={() => setCancelOpen(true)}>
                Cancel appointment
              </Button>
            </>
          )
        }
      />

      <div className="grid gap-4 lg:grid-cols-[12rem_1fr]">
        <div className="rounded-lg border border-border bg-card px-4 py-5">
          <p className="text-[13px] text-muted-foreground">Token</p>
          <p className="tabular text-6xl leading-none font-semibold tracking-tight">{a.token_number}</p>
          <div className="mt-4">
            <AppointmentStatusLabel status={a.status} />
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card">
          <DetailList
            items={[
              {
                label: "Patient",
                value: (
                  <Link href={`/patients/${a.patient_id}`} className="font-medium hover:underline">
                    {a.patient_name}
                  </Link>
                ),
              },
              { label: "Phone", value: a.patient_phone },
              {
                label: "Doctor",
                value: (
                  <>
                    <Link href={`/doctors/${a.doctor_id}`} className="font-medium hover:underline">
                      {a.doctor_name}
                    </Link>
                    <span className="text-muted-foreground">, {a.department}</span>
                  </>
                ),
              },
              {
                label: "Slot",
                value: (
                  <>
                    {formatDate(a.appointment_date)}, <time>{formatTime(a.appointment_time)}</time> (
                    {a.slot_duration_minutes} min)
                  </>
                ),
              },
              { label: "Booked via", value: <BookingSourceLabel source={a.booking_source} /> },
              { label: "Booked on", value: formatDateTime(a.created_at) },
              { label: "Notes", value: a.notes },
              {
                label: "Rescheduled from",
                value: a.rescheduled_from_id && (
                  <Link href={`/appointments/${a.rescheduled_from_id}`} className="hover:underline">
                    The original appointment
                  </Link>
                ),
              },
              { label: "Cancelled on", value: a.cancelled_at && formatDateTime(a.cancelled_at) },
              { label: "Reason", value: a.cancellation_reason },
            ]}
          />
        </div>
      </div>

      <CancelAppointmentDialog open={cancelOpen} onOpenChange={setCancelOpen} appointment={a} onSuccess={load} />
      <RescheduleAppointmentDialog
        open={rescheduleOpen}
        onOpenChange={setRescheduleOpen}
        appointment={a}
        onSuccess={load}
      />
    </>
  );
}
