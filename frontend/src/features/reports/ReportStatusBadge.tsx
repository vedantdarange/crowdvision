import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Clock,
  Flame,
  HeartPulse,
  HelpCircle,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
  Siren,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import type { ReportKind, ReportStatus, SosType } from '@contract/types';
import { Button } from '@/components/ui/button';
import type { GeolocationState } from './useGeolocation';

export const SOS_OPTIONS: ReadonlyArray<{
  value: SosType;
  label: string;
  hint: string;
  Icon: LucideIcon;
}> = [
  {
    value: 'CRUSH_RISK',
    label: 'Crush risk',
    hint: 'Dangerous crowd pressure or bottleneck',
    Icon: AlertTriangle,
  },
  {
    value: 'MEDICAL',
    label: 'Medical',
    hint: 'Injury, fainting, or urgent medical help',
    Icon: HeartPulse,
  },
  {
    value: 'FIRE',
    label: 'Fire',
    hint: 'Smoke, fire, or electrical hazard',
    Icon: Flame,
  },
  {
    value: 'LOST_CHILD',
    label: 'Lost child',
    hint: 'Missing child or separated vulnerable person',
    Icon: Search,
  },
  {
    value: 'OTHER',
    label: 'Other',
    hint: 'Other urgent safety concern',
    Icon: HelpCircle,
  },
];

export function sosTypeLabel(sosType: SosType | null | undefined): string {
  const match = SOS_OPTIONS.find((item) => item.value === sosType);
  return match?.label ?? 'SOS';
}

export function sosTypeIcon(sosType: SosType | null | undefined): LucideIcon {
  const match = SOS_OPTIONS.find((item) => item.value === sosType);
  return match?.Icon ?? Siren;
}

const STATUS_META: Record<
  ReportStatus,
  { label: string; Icon: LucideIcon; className: string }
> = {
  PENDING: {
    label: 'Pending',
    Icon: Clock,
    className: 'bg-warning-bg text-warning border border-warning/30',
  },
  VERIFIED: {
    label: 'Verified',
    Icon: CheckCircle2,
    className: 'bg-safe-bg text-safe border border-safe/30',
  },
  DISMISSED: {
    label: 'Dismissed',
    Icon: XCircle,
    className: 'bg-muted text-muted-foreground border border-border',
  },
};

export function ReportStatusChip({ status }: { status: ReportStatus }) {
  const { label, Icon, className } = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${className}`}
    >
      <Icon size={14} aria-hidden />
      <span>{label}</span>
    </span>
  );
}

export function ReportKindBadge({
  kind,
  sosType,
}: {
  kind: ReportKind;
  sosType: SosType | null;
}) {
  if (kind === 'SOS') {
    const Icon = sosTypeIcon(sosType);
    return (
      <span className="bg-critical-bg text-critical border-critical/40 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-bold tracking-wide uppercase">
        <Icon size={15} aria-hidden />
        <span>SOS · {sosTypeLabel(sosType)}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border bg-card px-2.5 py-1 text-xs font-semibold">
      <Camera size={15} aria-hidden />
      <span>Crowd photo</span>
    </span>
  );
}

export function LocationStatusBox({
  geo,
  reasonText,
}: {
  geo: GeolocationState;
  reasonText: string;
}) {
  return (
    <div className="space-y-2 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-semibold">
          {geo.status === 'locating' ? (
            <Loader2 size={18} className="animate-spin" aria-hidden />
          ) : (
            <MapPin size={18} aria-hidden />
          )}
          <span>
            {geo.status === 'ready' && geo.coords
              ? `Location ready · accuracy ±${geo.coords.accuracy} m`
              : geo.status === 'locating'
                ? 'Capturing high-accuracy GPS location (up to 10 s)...'
                : 'Location required'}
          </span>
        </div>
        <Button
          type="button"
          variant="outline"
          className="min-h-11 gap-2"
          onClick={geo.retry}
          disabled={geo.status === 'locating'}
        >
          <RefreshCw size={16} aria-hidden />
          Retry location
        </Button>
      </div>
      {geo.status === 'ready' && geo.coords && geo.coords.accuracy > 100 && (
        <p className="text-muted-foreground text-xs" role="status">
          Accuracy radius is over 100 m — if indoors, step near an open area and
          retry if needed.
        </p>
      )}
      {geo.error && (
        <div
          role="alert"
          className="bg-warning-bg text-warning rounded-lg border px-3 py-2 text-sm"
        >
          {geo.error}
        </div>
      )}
      <p className="text-muted-foreground text-xs">{reasonText}</p>
    </div>
  );
}
