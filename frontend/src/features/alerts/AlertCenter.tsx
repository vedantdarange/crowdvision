import { Link } from 'react-router';
import { BellRing, Volume2, VolumeX } from 'lucide-react';
import type { Alert, Report } from '@contract/types';
import { LevelBadge } from '@/components/status/LevelBadge';
import { useAlertAction, label } from '@/features/police/Alerts';
import { useBannerFeed } from './useBannerFeed';
import { useAlertAudio } from './useAlertAudio';
import {
  useWebPush,
  type WebPushState,
  type WebPushStatus,
} from '@/features/push';
import { useAlertTitle } from './useAlertTitle';

type Entry = { key: string; critical: boolean; time: string } & (
  { alert: Alert } | { report: Report }
);
export function AlertBanner({
  entry,
  acknowledge,
}: {
  entry: Entry;
  acknowledge: (a: Alert) => void;
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border bg-background px-3 py-1"
    >
      {'alert' in entry ? (
        <>
          <strong>{entry.alert.zone_name}</strong>
          <LevelBadge level={entry.alert.level} />
          <span>Peak {entry.alert.peak_density} people/m²</span>
          <button
            className="min-h-11 font-semibold underline"
            onClick={() => acknowledge(entry.alert)}
          >
            Acknowledge
          </button>
          <Link
            className="inline-flex min-h-11 items-center underline"
            to={'/police/alerts/' + entry.alert.id}
          >
            Open
          </Link>
        </>
      ) : (
        <>
          <strong>SOS - {label(entry.report.sos_type!)}</strong>
          <span>{entry.report.zone_name ?? 'location outside zones'}</span>
          <Link
            className="inline-flex min-h-11 items-center underline"
            to={'/police/reports?focus=' + entry.report.id}
          >
            Open
          </Link>
        </>
      )}
    </div>
  );
}
const PUSH_STATUS_LABELS: Record<WebPushStatus, string> = {
  on: 'Push: On',
  off: 'Push: Off',
  blocked: 'Push: Blocked',
  unsupported: 'Push: Unsupported',
};

function ArmAlertsButton({
  audio,
  push,
}: {
  audio: ReturnType<typeof useAlertAudio>;
  push: WebPushState;
}) {
  const statusNotice =
    push.status === 'blocked'
      ? (push.notice ?? audio.notice)
      : (audio.notice ?? push.notice);

  return (
    <div className="flex flex-wrap items-center gap-3">
      {audio.armed ? (
        <span className="font-semibold">Alerts armed</span>
      ) : (
        <button
          title={
            audio.intent
              ? 'Tap again to enable audio on this page'
              : 'Arm alerts'
          }
          onClick={audio.arm}
          className="inline-flex min-h-11 items-center gap-2 rounded-md bg-amber-100 px-3 font-semibold text-amber-950"
        >
          <BellRing size={18} aria-hidden />
          Alerts not armed - tap to enable
        </button>
      )}
      {audio.armed && push.status === 'off' && push.supported && (
        <button
          type="button"
          onClick={() => void push.subscribe()}
          disabled={push.busy}
          className="inline-flex min-h-11 items-center gap-2 rounded-md border px-3 text-sm font-medium hover:bg-muted disabled:opacity-50"
        >
          {push.busy ? 'Enabling push...' : 'Enable background push'}
        </button>
      )}
      <button
        className="inline-flex min-h-11 items-center gap-2"
        onClick={audio.toggleMute}
        aria-pressed={audio.muted}
      >
        {audio.muted ? <VolumeX size={18} /> : <Volume2 size={18} />} Mute alert
        sound
      </button>
      <span
        data-push-status={push.status}
        className="rounded-md border px-2 py-1 text-xs font-medium"
      >
        {PUSH_STATUS_LABELS[push.status]}
      </span>
      <small>Check volume / silent switch</small>
      {statusNotice && (
        <small role="status" className="text-muted-foreground">
          {statusNotice}
        </small>
      )}
    </div>
  );
}
export function AlertCenter() {
  const feed = useBannerFeed();
  const mutation = useAlertAction();
  const entries: Entry[] = [
    ...feed.alerts.map((alert) => ({
      alert,
      key: 'a' + alert.id,
      critical: alert.level === 'CRITICAL',
      time: alert.created_at,
    })),
    ...feed.reports.map((report) => ({
      report,
      key: 'r' + report.id,
      critical: true,
      time: report.created_at,
    })),
  ].sort(
    (a, b) =>
      Number(b.critical) - Number(a.critical) ||
      b.time.localeCompare(a.time) ||
      a.key.localeCompare(b.key),
  );
  const keys = (critical: boolean) =>
    entries
      .filter((e) => e.critical === critical)
      .map((e) => e.key)
      .sort()
      .join(',');
  const push = useWebPush();
  const audio = useAlertAudio(keys(true), keys(false), {
    onPermissionResult: (permission) => {
      push.reportPermission(permission);
      if (permission === 'granted') {
        void push.subscribe('granted');
      }
    },
  });
  useAlertTitle(entries.length);
  return (
    <section
      aria-label="Alert center"
      className="sticky top-0 z-20 grid max-h-[45svh] gap-2 overflow-y-auto rounded-md border bg-background px-4 py-2"
    >
      <ArmAlertsButton audio={audio} push={push} />
      {feed.failed && (
        <p>
          Could not sync alert banners.{' '}
          <button className="underline" onClick={feed.retry}>
            Retry
          </button>
        </p>
      )}
      {entries.slice(0, 3).map((entry) => (
        <AlertBanner
          key={entry.key}
          entry={entry}
          acknowledge={(alert) =>
            mutation.mutate({ alert, action: 'acknowledge' })
          }
        />
      ))}
      {entries.length > 3 && <span>+{entries.length - 3} more</span>}
    </section>
  );
}
