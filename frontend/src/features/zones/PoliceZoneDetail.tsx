import { lazy, Suspense, useState } from 'react';
import { Link, useParams } from 'react-router';
import { ErrorBoundary } from 'react-error-boundary';
import { QueryErrorResetBoundary } from '@tanstack/react-query';
import {
  Camera,
  Film,
  Info,
  OctagonAlert,
  Radio,
  TriangleAlert,
  Video,
  WifiOff,
} from 'lucide-react';
import type { Advisory, ZoneState } from '@contract/types';
import { LevelBadge } from '@/components/status/LevelBadge';
import { TrendIcon } from '@/components/status/TrendIcon';
import { DensityValue } from '@/components/status/DensityValue';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Age } from '@/features/police/Alerts';
import {
  HISTORY_RANGES,
  useZone,
  useZoneHistory,
  type HistoryRange,
} from '@/features/police/data';
import { useAdvisories } from './api';
import { formatDensity } from '@/lib/format';

const ZoneChart = lazy(() => import('./ZoneChart'));

export function formatZoneChartSummary(zone: ZoneState): string {
  const trendWord = zone.trend.toLowerCase();
  if (zone.level === 'NO_DATA') {
    return 'No live readings yet.';
  }
  if (zone.mode === 'COUNT') {
    if (zone.count === null) return 'No live readings yet.';
    const unit = zone.count === 1 ? 'person' : 'people';
    const densityPart =
      zone.density !== null
        ? ` (${formatDensity(zone.density)} people per square metre)`
        : '';
    return `Currently ${zone.count} ${unit}${densityPart}, ${trendWord}.`;
  }
  if (zone.density === null) return 'No live readings yet.';
  return `Currently ${formatDensity(zone.density)} people per square metre, ${trendWord}.`;
}

function ChartSkeleton() {
  return (
    <div role="status" className="space-y-3 py-4">
      <span className="sr-only">Loading zone history chart</span>
      <Skeleton className="h-64 w-full" />
      <Skeleton className="h-4 w-48" />
    </div>
  );
}

function ZoneHistoryBody({
  zone,
  range,
}: {
  zone: ZoneState;
  range: HistoryRange;
}) {
  const { data: history } = useZoneHistory(zone.id, range);
  return (
    <Suspense fallback={<ChartSkeleton />}>
      <ZoneChart
        zone={zone}
        historyPoints={history}
        showSeconds={range === '30m'}
      />
    </Suspense>
  );
}

function AdvisoryCard({ advisory }: { advisory: Advisory }) {
  const meta = {
    INFO: { icon: Info, style: 'bg-secondary text-secondary-foreground' },
    WARNING: { icon: TriangleAlert, style: 'bg-warning-bg text-warning' },
    URGENT: { icon: OctagonAlert, style: 'bg-critical-bg text-critical' },
  }[advisory.severity];
  const Icon = meta.icon;

  return (
    <li className="flex flex-col items-start gap-1.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ${meta.style}`}
        >
          <Icon aria-hidden="true" size={14} />
          <span>{advisory.severity}</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {advisory.zone_id === null ? 'Global advisory' : advisory.zone_name}
        </span>
        <small className="text-xs text-muted-foreground">
          <Age ts={advisory.created_at} />
        </small>
      </div>
      <h3 className="font-semibold">{advisory.title}</h3>
      <p className="text-sm text-muted-foreground">{advisory.body}</p>
    </li>
  );
}

function ZoneAdvisoriesList({ zoneId }: { zoneId: number }) {
  const { data: advisories } = useAdvisories(zoneId);
  if (advisories.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No active advisories for this zone.
      </p>
    );
  }
  return (
    <ul>
      {[...advisories]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((advisory) => (
          <AdvisoryCard key={advisory.id} advisory={advisory} />
        ))}
    </ul>
  );
}

export function PoliceZoneDetail() {
  const { id } = useParams();
  const zoneId = Number(id);
  const [range, setRange] = useState<HistoryRange>('30m');

  if (!Number.isInteger(zoneId) || zoneId <= 0) {
    return (
      <section className="police-page">
        <Link to="/police">Operations dashboard</Link>
        <EmptyState
          title="Zone not found"
          description="Choose an active zone from the operations dashboard."
          action={
            <Link to="/police" className="underline">
              Back to dashboard
            </Link>
          }
        />
      </section>
    );
  }

  return (
    <ZoneLiveView zoneId={zoneId} range={range} onRangeChange={setRange} />
  );
}

function ZoneLiveView({
  zoneId,
  range,
  onRangeChange,
}: {
  zoneId: number;
  range: HistoryRange;
  onRangeChange: (next: HistoryRange) => void;
}) {
  const { data: zone } = useZone(zoneId);
  const activeSources = zone.sources.filter((s) => s.is_active);
  const summary = formatZoneChartSummary(zone);

  const thresholdSummary =
    zone.mode === 'COUNT'
      ? `Warning ${zone.warning_count ?? '—'} · Critical ${zone.critical_count ?? '—'} people`
      : `Warning ${zone.warning_density} · Critical ${zone.critical_density} people/m²`;

  return (
    <section className="police-page">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/police">Operations dashboard</Link>
        <Link
          to={`/police/monitor?zone_id=${zone.id}`}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium no-underline hover:bg-muted"
        >
          <Video aria-hidden="true" size={16} />
          Stream to this zone
        </Link>
      </div>

      <header>
        <div>
          <h1>{zone.name}</h1>
          {zone.description && (
            <p className="text-sm text-muted-foreground">{zone.description}</p>
          )}
        </div>
        <div className="police-actions">
          <LevelBadge level={zone.level} />
          <TrendIcon trend={zone.trend} />
        </div>
      </header>

      <section
        aria-label="Live zone readings"
        className="glass grid grid-cols-2 gap-4 sm:grid-cols-4"
      >
        <div>
          <span className="text-xs text-muted-foreground">Count</span>
          <p className="tabular-nums text-2xl font-semibold">
            {zone.count ?? '—'}
          </p>
        </div>
        <div>
          <span className="text-xs text-muted-foreground">Density</span>
          <p className="text-2xl font-semibold">
            <DensityValue value={zone.density} />
          </p>
        </div>
        <div>
          <span className="text-xs text-muted-foreground">
            Thresholds ({zone.mode === 'COUNT' ? 'Count' : 'Density'})
          </span>
          <p className="text-sm font-medium">{thresholdSummary}</p>
          <p className="text-xs text-muted-foreground">
            Area {Math.round(zone.area_m2)} m²
          </p>
        </div>
        <div>
          <span className="text-xs text-muted-foreground">Last update</span>
          <p className="text-sm font-medium">
            <Age ts={zone.live_updated_at} />
          </p>
        </div>
      </section>

      <section className="glass space-y-4" aria-label="Occupancy trend">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="m-0">
              {zone.mode === 'COUNT'
                ? 'Live & historical count'
                : 'Live & historical density'}
            </h2>
            <p role="status" className="text-sm text-muted-foreground">
              {summary}
            </p>
          </div>

          <div
            role="group"
            aria-label="History range"
            className="flex flex-wrap gap-1.5"
          >
            {(Object.keys(HISTORY_RANGES) as HistoryRange[]).map((key) => (
              <Button
                key={key}
                type="button"
                variant={range === key ? 'default' : 'outline'}
                aria-pressed={range === key}
                className="min-h-11"
                onClick={() => onRangeChange(key)}
              >
                {HISTORY_RANGES[key].label}
              </Button>
            ))}
          </div>
        </div>

        <QueryErrorResetBoundary>
          {({ reset }) => (
            <ErrorBoundary
              resetKeys={[zone.id, range]}
              onReset={reset}
              fallbackRender={({ resetErrorBoundary }) => (
                <div
                  role="alert"
                  className="space-y-3 rounded-lg border p-4 text-sm"
                >
                  <p className="font-medium">
                    Could not load zone history samples.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={resetErrorBoundary}
                  >
                    Retry
                  </Button>
                </div>
              )}
            >
              <Suspense fallback={<ChartSkeleton />}>
                <ZoneHistoryBody zone={zone} range={range} />
              </Suspense>
            </ErrorBoundary>
          )}
        </QueryErrorResetBoundary>
      </section>

      <div className="police-grid">
        <section className="glass space-y-3">
          <h2 className="m-0">Camera &amp; video sources</h2>
          {activeSources.length === 0 ? (
            <EmptyState
              title="No sources configured"
              description="Add a webcam or video file source in Camera control."
              action={
                <Link
                  to={`/police/monitor?zone_id=${zone.id}`}
                  className="underline"
                >
                  Open Monitor
                </Link>
              }
            />
          ) : (
            <ul>
              {activeSources.map((source) => {
                const online = source.status === 'ONLINE';
                return (
                  <li key={source.id} className="justify-between">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {source.kind === 'WEBCAM' ? (
                          <Camera aria-hidden="true" size={16} />
                        ) : (
                          <Film aria-hidden="true" size={16} />
                        )}
                        <strong>{source.name}</strong>
                      </div>
                      <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                        <span>Coverage {source.coverage_area_m2} m²</span>
                        <span aria-hidden="true">·</span>
                        <span>
                          {source.last_frame_at ? (
                            <>
                              Last frame <Age ts={source.last_frame_at} />
                            </>
                          ) : (
                            'Last frame: never'
                          )}
                        </span>
                      </p>
                    </div>
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ${
                        online
                          ? 'bg-safe-bg text-safe'
                          : 'bg-no-data-bg text-no-data'
                      }`}
                    >
                      {online ? (
                        <Radio aria-hidden="true" size={14} />
                      ) : (
                        <WifiOff aria-hidden="true" size={14} />
                      )}
                      <span>{online ? 'ONLINE' : 'OFFLINE'}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="glass space-y-3">
          <h2 className="m-0">Zone advisories</h2>
          <SuspenseBoundary>
            <ZoneAdvisoriesList zoneId={zone.id} />
          </SuspenseBoundary>
        </section>
      </div>
    </section>
  );
}
