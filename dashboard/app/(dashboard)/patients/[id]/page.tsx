"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { getPatient, getPatientAppointments, type AppointmentOut, type PatientOut } from "@/lib/api";
import { describePatient, formatDate, formatDateTime, formatTime } from "@/lib/format";
import { PageHeader } from "@/components/page-header";
import { BackLink, DetailList } from "@/components/detail-list";
import { AppointmentStatusLabel, BookingSourceLabel } from "@/components/status";
import { BookAppointmentDialog } from "@/components/appointments/BookAppointmentDialog";
import { PatientFormDialog } from "@/components/patients/PatientFormDialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function PatientDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [patient, setPatient] = React.useState<PatientOut | null>(null);
  const [appointments, setAppointments] = React.useState<AppointmentOut[]>([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [editOpen, setEditOpen] = React.useState(false);
  const [bookOpen, setBookOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [p, history] = await Promise.all([getPatient(id), getPatientAppointments(id, { limit: 100 })]);
      setPatient(p);
      setAppointments(history.items);
      setTotal(history.total);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The patient could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  React.useEffect(() => {
    load();
  }, [load]);

  const back = <BackLink href="/patients">Patients</BackLink>;
  if (loading) return <div className="h-80 animate-pulse rounded-lg border border-border bg-card" />;
  if (!patient) {
    return (
      <>
        <PageHeader back={back} title="Patient not found" />
        <p className="text-sm text-muted-foreground">The link may be wrong.</p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        back={back}
        title={patient.name}
        description={[patient.phone, describePatient(patient)].filter(Boolean).join(", ")}
        actions={
          <>
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              Edit details
            </Button>
            <Button onClick={() => setBookOpen(true)}>Book appointment</Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <section className="self-start rounded-lg border border-border bg-card">
          <h2 className="border-b border-border px-4 py-3 text-[15px] font-semibold">Details</h2>
          <DetailList
            items={[
              { label: "Phone", value: patient.phone },
              { label: "Age and gender", value: describePatient(patient) },
              { label: "Email", value: patient.email },
              { label: "Address", value: patient.address },
              { label: "Registered", value: formatDateTime(patient.created_at) },
            ]}
          />
        </section>

        <section className="overflow-hidden rounded-lg border border-border bg-card">
          <h2 className="border-b border-border px-4 py-3 text-[15px] font-semibold">
            Appointments <span className="tabular font-normal text-muted-foreground">{total}</span>
          </h2>
          {appointments.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground">No appointments yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>When</TableHead>
                  <TableHead>Doctor</TableHead>
                  <TableHead>Token</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Booked via</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {appointments.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <Link href={`/appointments/${a.id}`} className="font-medium hover:underline">
                        {formatDate(a.appointment_date)}
                      </Link>
                      <time className="block text-[13px] text-muted-foreground">{formatTime(a.appointment_time)}</time>
                    </TableCell>
                    <TableCell>
                      {a.doctor_name}
                      <span className="block text-[13px] text-muted-foreground">{a.department}</span>
                    </TableCell>
                    <TableCell>{a.token_number}</TableCell>
                    <TableCell>
                      <AppointmentStatusLabel status={a.status} />
                    </TableCell>
                    <TableCell>
                      <BookingSourceLabel source={a.booking_source} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </section>
      </div>

      <PatientFormDialog open={editOpen} onOpenChange={setEditOpen} patient={patient} onSuccess={load} />
      <BookAppointmentDialog
        open={bookOpen}
        onOpenChange={setBookOpen}
        defaultPatient={patient}
        onSuccess={load}
      />
    </>
  );
}
