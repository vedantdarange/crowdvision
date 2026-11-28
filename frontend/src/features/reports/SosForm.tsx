import { useState } from 'react';
import { Link } from 'react-router';
import { CheckCircle2, Loader2, PhoneCall, Siren } from 'lucide-react';
import type { Report, SosType } from '@contract/types';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatReportError, useSubmitSosReport } from './api';
import {
  LocationStatusBox,
  SOS_OPTIONS,
  sosTypeLabel,
} from './ReportStatusBadge';
import { useGeolocation } from './useGeolocation';

function Emergency112Notice() {
  return (
    <div
      role="note"
      className="bg-critical-bg text-critical border-critical/40 flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm font-semibold"
    >
      <PhoneCall size={18} className="mt-0.5 shrink-0" aria-hidden />
      <p>
        In immediate danger, call{' '}
        <a href="tel:112" className="underline">
          112
        </a>{' '}
        - this app is not a replacement for emergency services
      </p>
    </div>
  );
}

export function SosReportPage() {
  const geo = useGeolocation({ autoRequest: true, timeoutMs: 10000 });
  const submitMutation = useSubmitSosReport();

  const [selectedType, setSelectedType] = useState<SosType | null>(null);
  const [note, setNote] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitted, setSubmitted] = useState<Report | null>(null);

  async function handleConfirmedSend() {
    if (!selectedType || !geo.coords || submitMutation.isPending) return;
    try {
      const report = await submitMutation.mutateAsync({
        sos_type: selectedType,
        lat: geo.coords.lat,
        lng: geo.coords.lng,
        note,
      });
      setConfirmOpen(false);
      setNote('');
      setSubmitted(report);
    } catch {
      setConfirmOpen(false);
    }
  }

  function handleReset() {
    setSubmitted(null);
    setSelectedType(null);
    setNote('');
    submitMutation.reset();
  }

  const submitError = submitMutation.error
    ? formatReportError(submitMutation.error, 'SOS')
    : null;

  return (
    <section className="mx-auto max-w-2xl space-y-5 p-4 pb-12">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-3xl font-semibold">Send SOS</h1>
          <div className="flex items-center gap-3 text-sm">
            <Link
              className="inline-flex min-h-11 items-center underline"
              to="/report/crowd"
            >
              Report crowd photo
            </Link>
            <Link
              className="inline-flex min-h-11 items-center underline"
              to="/my-reports"
            >
              My reports
            </Link>
          </div>
        </div>
        <p className="text-muted-foreground text-sm">
          Alert on-site police responders immediately with the emergency type
          and your GPS location.
        </p>
      </header>

      <Emergency112Notice />

      {submitted ? (
        <div
          role="status"
          className="space-y-4 rounded-2xl border bg-card p-5 shadow-xs"
        >
          <div className="flex items-center gap-2 text-lg font-semibold">
            <CheckCircle2 size={22} className="text-safe" aria-hidden />
            <span>SOS report sent · Reference #{submitted.id}</span>
          </div>
          <p className="text-sm font-medium">
            Type: <strong>{sosTypeLabel(submitted.sos_type)}</strong> ·{' '}
            {submitted.zone_name ?? 'Outside monitored zones'}
          </p>
          <div className="space-y-1 rounded-lg border p-3 text-sm">
            <p className="font-semibold">What happens next</p>
            <p className="text-muted-foreground">
              Police responders received your location in the live triage queue
              and will verify or dispatch help. Watch My reports for live review
              updates, and move to a safe open space if possible.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button asChild className="min-h-11">
              <Link to="/my-reports">View My reports</Link>
            </Button>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              onClick={handleReset}
            >
              Send another SOS
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <fieldset className="space-y-3 rounded-xl border bg-card p-4">
            <legend className="px-1 text-base font-semibold">
              1. Select emergency type
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {SOS_OPTIONS.map(({ value, label, hint, Icon }) => {
                const selected = selectedType === value;
                return (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setSelectedType(value)}
                    className={`flex min-h-16 items-start gap-3 rounded-xl border p-3.5 text-left transition ${
                      selected
                        ? 'border-primary bg-primary/10 ring-primary/40 ring-2'
                        : 'hover:bg-muted'
                    }`}
                  >
                    <Icon size={22} className="mt-0.5 shrink-0" aria-hidden />
                    <span>
                      <strong className="block text-base">{label}</strong>
                      <span className="text-muted-foreground block text-xs">
                        {hint}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <LocationStatusBox
            geo={geo}
            reasonText="GPS coordinates help dispatch responders directly to where help is needed."
          />

          <div className="space-y-2 rounded-xl border bg-card p-4">
            <Label htmlFor="sos-note">Optional note</Label>
            <Textarea
              id="sos-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="Landmark, number of people affected, or clothing/details"
            />
          </div>

          {submitError && (
            <div
              role="alert"
              className="bg-critical-bg text-critical rounded-xl border px-4 py-3 text-sm font-medium"
            >
              {submitError}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              className="min-h-12 gap-2 px-5"
              disabled={
                !selectedType || !geo.coords || submitMutation.isPending
              }
              onClick={() => {
                submitMutation.reset();
                setConfirmOpen(true);
              }}
            >
              <Siren size={18} aria-hidden />
              Send SOS
            </Button>
            {(!selectedType || !geo.coords) && (
              <span className="text-muted-foreground text-xs">
                Select an emergency type and wait for GPS location before
                sending.
              </span>
            )}
          </div>
        </div>
      )}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!open && !submitMutation.isPending) setConfirmOpen(false);
        }}
      >
        <DialogContent>
          <DialogTitle>Confirm SOS request</DialogTitle>
          <DialogDescription>
            Send a{' '}
            <strong>{selectedType ? sosTypeLabel(selectedType) : 'SOS'}</strong>{' '}
            alert to venue safety responders
            {geo.coords ? ` (accuracy ±${geo.coords.accuracy} m)` : ''}?
          </DialogDescription>
          {note.trim() && (
            <p className="rounded-lg border bg-muted/40 p-2.5 text-sm">
              Note: {note.trim()}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2 pt-2">
            <DialogClose asChild>
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                disabled={submitMutation.isPending}
              >
                Cancel
              </Button>
            </DialogClose>
            <Button
              type="button"
              className="min-h-11 gap-2"
              disabled={submitMutation.isPending}
              onClick={() => void handleConfirmedSend()}
            >
              {submitMutation.isPending ? (
                <>
                  <Loader2 size={16} className="animate-spin" aria-hidden />
                  Sending SOS...
                </>
              ) : (
                'Confirm & send SOS'
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
