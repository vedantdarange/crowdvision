import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Link } from 'react-router';
import {
  Camera,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import type { Report } from '@contract/types';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatDensity } from '@/lib/format';
import { formatReportError, useSubmitCrowdReport } from './api';
import { downscaleCrowdImage } from './imageDownscale';
import { LocationStatusBox } from './ReportStatusBadge';
import { useGeolocation } from './useGeolocation';

interface PreparedPhoto {
  blob: Blob;
  width: number;
  height: number;
  previewUrl: string;
}

const PRIVACY_NOTICE =
  'Your photo is not stored; the count, location and note are kept for up to 30 days.';

export function CrowdReportPage() {
  const geo = useGeolocation({ autoRequest: true, timeoutMs: 10000 });
  const submitMutation = useSubmitCrowdReport();

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const activePreviewUrlRef = useRef<string | null>(null);

  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [downscaling, setDownscaling] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState<Report | null>(null);

  function clearPhotoReference() {
    if (activePreviewUrlRef.current) {
      URL.revokeObjectURL(activePreviewUrlRef.current);
      activePreviewUrlRef.current = null;
    }
    setPhoto(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }

  useEffect(() => {
    return () => {
      if (activePreviewUrlRef.current) {
        URL.revokeObjectURL(activePreviewUrlRef.current);
        activePreviewUrlRef.current = null;
      }
    };
  }, []);

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setPhotoError(null);
    submitMutation.reset();

    if (!file) {
      clearPhotoReference();
      return;
    }

    setDownscaling(true);
    try {
      const result = await downscaleCrowdImage(file, {
        maxSide: 1280,
        quality: 0.8,
      });
      if (activePreviewUrlRef.current) {
        URL.revokeObjectURL(activePreviewUrlRef.current);
      }
      const nextUrl = URL.createObjectURL(result.blob);
      activePreviewUrlRef.current = nextUrl;
      setPhoto({
        blob: result.blob,
        width: result.width,
        height: result.height,
        previewUrl: nextUrl,
      });
    } catch (error) {
      clearPhotoReference();
      setPhotoError(
        error instanceof Error
          ? error.message
          : 'Could not prepare the selected photo.',
      );
    } finally {
      setDownscaling(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!geo.coords || !photo || downscaling || submitMutation.isPending) {
      return;
    }

    try {
      const report = await submitMutation.mutateAsync({
        image: photo.blob,
        lat: geo.coords.lat,
        lng: geo.coords.lng,
        note,
      });
      // Drop image blob & preview object URL immediately once upload finishes.
      clearPhotoReference();
      setNote('');
      setPhotoError(null);
      setSubmitted(report);
    } catch {
      // Error UI reads submitMutation.error directly.
    }
  }

  function handleResetForAnother() {
    setSubmitted(null);
    submitMutation.reset();
    clearPhotoReference();
    setPhotoError(null);
    setNote('');
  }

  const submitError = submitMutation.error
    ? formatReportError(submitMutation.error, 'CROWD')
    : null;

  return (
    <section className="mx-auto max-w-2xl space-y-5 p-4 pb-12">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-3xl font-semibold">Report a crowd</h1>
          <div className="flex items-center gap-3 text-sm">
            <Link
              className="inline-flex min-h-11 items-center underline"
              to="/report/sos"
            >
              Send SOS instead
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
          Take or select a crowd photo to share an automated headcount hint with
          safety teams.
        </p>
      </header>

      <div className="flex items-start gap-2.5 rounded-xl border bg-card p-3.5 text-sm">
        <ShieldCheck size={18} className="mt-0.5 shrink-0" aria-hidden />
        <p>{PRIVACY_NOTICE}</p>
      </div>

      {submitted ? (
        <div
          role="status"
          className="space-y-4 rounded-2xl border bg-card p-5 shadow-xs"
        >
          <div className="flex items-center gap-2 text-lg font-semibold">
            <CheckCircle2 size={22} className="text-safe" aria-hidden />
            <span>Crowd report submitted (#{submitted.id})</span>
          </div>
          <p className="text-base font-medium">
            {submitted.zone_name && submitted.density_hint !== null
              ? `${submitted.count ?? 0} people counted, about ${formatDensity(submitted.density_hint)} per m² in ${submitted.zone_name}`
              : `${submitted.count ?? 0} people counted — outside a monitored zone`}
          </p>
          <p className="text-muted-foreground text-sm">{PRIVACY_NOTICE}</p>
          <div className="flex flex-wrap gap-3">
            <Button asChild className="min-h-11">
              <Link to="/my-reports">View My reports</Link>
            </Button>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              onClick={handleResetForAnother}
            >
              Submit another crowd photo
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <LocationStatusBox
            geo={geo}
            reasonText="Location matches your photo to the right venue zone so responders see accurate density hints."
          />

          <div className="space-y-3 rounded-xl border bg-card p-4">
            <Label
              htmlFor="crowd-photo-input"
              className="text-base font-semibold"
            >
              Crowd photo (camera or gallery)
            </Label>
            <input
              ref={fileInputRef}
              id="crowd-photo-input"
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => void handleFileChange(e)}
              className="block min-h-11 w-full cursor-pointer rounded-lg border border-dashed px-3 py-2 text-sm file:mr-3 file:rounded-md file:border file:px-3 file:py-1.5 file:text-sm file:font-medium"
            />
            <p className="text-muted-foreground text-xs">
              Photos are compressed on your device to JPEG (longest side up to
              1280 px) before upload.
            </p>

            {downscaling && (
              <p role="status" className="flex items-center gap-2 text-sm">
                <Loader2 size={16} className="animate-spin" aria-hidden />
                Optimizing photo on device...
              </p>
            )}

            {photoError && (
              <div
                role="alert"
                className="bg-critical-bg text-critical rounded-lg border px-3 py-2 text-sm"
              >
                {photoError}
              </div>
            )}

            {photo && (
              <div className="space-y-2 rounded-lg border p-3">
                <img
                  src={photo.previewUrl}
                  alt="Selected crowd photo preview"
                  className="max-h-72 w-full rounded-md object-contain"
                />
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="text-muted-foreground">
                    {photo.width} x {photo.height} px ·{' '}
                    {Math.max(1, Math.round(photo.blob.size / 1024))} KB JPEG
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-11 gap-1.5"
                    onClick={clearPhotoReference}
                  >
                    <Trash2 size={15} aria-hidden />
                    Remove photo
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="space-y-2 rounded-xl border bg-card p-4">
            <Label htmlFor="crowd-note">Optional note</Label>
            <Textarea
              id="crowd-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="E.g. queue slowing near east gate steps"
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
              type="submit"
              className="min-h-12 gap-2 px-5"
              disabled={
                !geo.coords || !photo || downscaling || submitMutation.isPending
              }
            >
              {submitMutation.isPending ? (
                <>
                  <Loader2 size={18} className="animate-spin" aria-hidden />
                  Uploading &amp; counting crowd...
                </>
              ) : (
                <>
                  <Camera size={18} aria-hidden />
                  Submit crowd report
                </>
              )}
            </Button>
            {!geo.coords && (
              <span className="text-muted-foreground text-xs">
                Capture your GPS location first to enable submission.
              </span>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
