import { memo } from 'react';
import { TriangleAlert } from 'lucide-react';
import type { FrameResult } from '@contract/types';
import { DensityValue } from '@/components/status/DensityValue';
import { LevelBadge } from '@/components/status/LevelBadge';
import type { LatencyStats } from './useFrameStreamer';

interface MonitorHudProps {
  lastResult: FrameResult | null;
  fps: number;
  latencyMs: LatencyStats;
  drops: number;
}

function MonitorHudBase({
  lastResult,
  fps,
  latencyMs,
  drops,
}: MonitorHudProps) {
  const hasResult = Boolean(lastResult && lastResult.ok);
  const isBusy = lastResult?.error === 'DETECTOR_BUSY';

  return (
    <div
      className="@container rounded-lg border bg-card p-4 text-sm"
      role="region"
      aria-label="Monitor statistics"
    >
      <div className="grid grid-cols-1 gap-x-4 gap-y-3 @[300px]:grid-cols-2 @[540px]:grid-cols-4">
        <div className="min-w-0">
          <span className="text-muted-foreground">Source count</span>
          <p className="tabular-nums text-lg font-semibold">
            {hasResult && lastResult ? lastResult.count : '—'}
          </p>
        </div>

        <div className="min-w-0">
          <span className="text-muted-foreground">Zone smoothed</span>
          <p className="tabular-nums text-lg font-semibold">
            {hasResult && lastResult && lastResult.smoothed_count !== null
              ? lastResult.smoothed_count
              : '—'}
          </p>
        </div>

        <div className="min-w-0">
          <span className="text-muted-foreground">Zone density</span>
          <p className="text-lg leading-snug font-semibold break-words">
            <DensityValue
              value={hasResult && lastResult ? lastResult.density : null}
            />
          </p>
        </div>

        <div className="min-w-0">
          <span className="text-muted-foreground">Zone level</span>
          <div className="mt-0.5">
            <LevelBadge
              level={
                hasResult && lastResult?.level ? lastResult.level : 'NO_DATA'
              }
            />
          </div>
        </div>

        <div className="min-w-0">
          <span className="text-muted-foreground">FPS</span>
          <p className="tabular-nums font-medium">{fps.toFixed(1)}</p>
        </div>

        <div className="min-w-0">
          <span className="text-muted-foreground">Latency</span>
          <p className="tabular-nums font-medium break-words">
            p50: {latencyMs.p50} ms · p95: {latencyMs.p95} ms
          </p>
        </div>

        <div className="min-w-0">
          <span className="text-muted-foreground">Drops</span>
          <p className="tabular-nums font-medium">{drops}</p>
        </div>

        <div className="flex min-w-0 items-center">
          {isBusy && (
            <span
              role="status"
              className="inline-flex items-center gap-1.5 rounded-md bg-warning-bg px-2.5 py-1 text-xs font-medium text-warning"
            >
              <TriangleAlert aria-hidden="true" size={14} />
              <span>Detector busy</span>
            </span>
          )}
          {!hasResult && !isBusy && (
            <span className="text-xs text-muted-foreground">No data yet</span>
          )}
        </div>
      </div>
    </div>
  );
}

export const MonitorHud = memo(MonitorHudBase);
