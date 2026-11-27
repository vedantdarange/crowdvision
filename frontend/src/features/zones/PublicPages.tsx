import { lazy, Suspense, useState, useEffect } from 'react';
import { Link, useParams } from 'react-router';
import { ErrorBoundary } from 'react-error-boundary';
import { Info, TriangleAlert, OctagonAlert } from 'lucide-react';
import type { PublicZoneState } from '@contract/types';
import { LevelBadge } from '@/components/status/LevelBadge';
import { TrendIcon } from '@/components/status/TrendIcon';
import { DensityValue } from '@/components/status/DensityValue';
import { ConnectionDot } from '@/components/status/ConnectionDot';
import { relativeTime } from '@/lib/format';
import { LEVELS } from '@/lib/constants';
import { useConnection } from '@/features/realtime/RealtimeProvider';
import { useHelp, useAdvisories, useLiveZones, usePublicZone } from './api';
const ZoneMap = lazy(() => import('./ZoneMap'));
function Reading({ zone }: { zone: PublicZoneState }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const stale = useConnection((s) => s.status !== 'connected');
  return (
    <div className="flex flex-wrap items-center gap-3">
      <LevelBadge level={zone.level} />
      <TrendIcon trend={zone.trend} />
      {zone.level === 'NO_DATA' ? (
        'No live data'
      ) : (
        <DensityValue value={zone.density} />
      )}
      <small>
        {zone.updated_at ? 'Updated ' : ''}
        {relativeTime(zone.updated_at, now)}
        {stale ? ' · May be stale' : ''}
      </small>
    </div>
  );
}
export function LiveMap() {
  const { data: zones } = useLiveZones();
  const status = useConnection((s) => s.status);
  const [selected, select] = useState<number | null>(null),
    [open, setOpen] = useState(false);
  function choose(id: number) {
    select(id);
    setOpen(true);
  }
  return (
    <section className="space-y-4 p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-3xl font-semibold">Live map</h1>
        <ConnectionDot state={status} />
      </header>
      <div aria-label="Map legend" className="flex flex-wrap gap-2">
        {LEVELS.map((l) => (
          <LevelBadge level={l} key={l} />
        ))}
      </div>
      <div className="relative grid min-w-0 overflow-hidden rounded-2xl border bg-card lg:grid-cols-[1fr_21rem]">
        <div className="relative isolate h-[60vh] min-w-0">
          <ErrorBoundary
            fallback={<p>Map unavailable. Browse the zone list.</p>}
          >
            <Suspense fallback={<p>Loading map…</p>}>
              <ZoneMap zones={zones} selected={selected} select={choose} />
            </Suspense>
          </ErrorBoundary>
        </div>
        <div className="absolute inset-x-0 bottom-0 max-h-[65%] overflow-auto rounded-t-xl bg-card p-4 shadow-lg lg:static lg:max-h-[60vh]">
          <button
            className="min-h-11 lg:hidden"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? 'Close' : 'Browse'} zones ({zones.length})
          </button>
          <div className={open ? 'block' : 'hidden lg:block'}>
            <h2 className="text-xl font-semibold">Zones</h2>
            {!zones.length && <p>No active zones.</p>}
            {zones.map((z) => (
              <article className="border-b py-3" key={z.zone_id}>
                <button
                  className="min-h-11 font-semibold aria-pressed:underline"
                  aria-pressed={selected === z.zone_id}
                  onClick={() => choose(z.zone_id)}
                >
                  {z.name}
                </button>
                <Reading zone={z} />
                <Link className="underline" to={'/zones/' + z.zone_id}>
                  View {z.name}
                </Link>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
function Notices({ id }: { id?: number }) {
  const Heading = id ? 'h3' : 'h2';
  const { data } = useAdvisories(id);
  if (!data.length) return <p>No active advisories.</p>;
  return [...data]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((a) => {
      const Icon = { INFO: Info, WARNING: TriangleAlert, URGENT: OctagonAlert }[
        a.severity
      ];
      return (
        <article className="rounded-xl border bg-card p-4" key={a.id}>
          <span className="inline-flex items-center gap-1 rounded border px-2">
            <Icon size={16} />
            {a.severity}
          </span>
          <Heading className="font-semibold">{a.title}</Heading>
          <p>{a.body}</p>
        </article>
      );
    });
}
export function ZoneDetail() {
  const { id } = useParams();
  const {
    data: { state, alternatives },
  } = usePublicZone(Number(id));
  return (
    <section className="space-y-4 p-4">
      <h1 className="text-3xl font-semibold">{state.name}</h1>
      <Reading zone={state} />
      <h2>Zone advisories</h2>
      <Notices id={state.zone_id} />
      <h2>Less crowded nearby</h2>
      {alternatives.length ? (
        alternatives.map((z) => (
          <Link
            className="block underline"
            key={z.zone_id}
            to={'/zones/' + z.zone_id}
          >
            {z.name}
          </Link>
        ))
      ) : (
        <p>No nearby safe alternatives.</p>
      )}
    </section>
  );
}
export function Advisories() {
  return (
    <section className="space-y-4 p-4">
      <h1 className="text-3xl font-semibold">Advisories</h1>
      <Notices />
    </section>
  );
}
export function Help() {
  const { data } = useHelp();
  return (
    <section className="space-y-4 p-4">
      <h1 className="text-3xl font-semibold">Help</h1>
      <h2>Emergency numbers</h2>
      {data.emergency_numbers.map((n) => (
        <a className="block underline" key={n.label} href={'tel:' + n.number}>
          {n.label} · {n.number}
        </a>
      ))}
      {(['medical_points', 'exits'] as const).map((k) => (
        <section key={k}>
          <h2>{k === 'exits' ? 'Exits' : 'Medical points'}</h2>
          {data[k].length ? (
            data[k].map((p) => (
              <p key={p.name}>
                {p.name} {p.note}
              </p>
            ))
          ) : (
            <p>None listed.</p>
          )}
        </section>
      ))}
      <h2>Privacy</h2>
      <p>Photos and video are not stored.</p>
    </section>
  );
}
