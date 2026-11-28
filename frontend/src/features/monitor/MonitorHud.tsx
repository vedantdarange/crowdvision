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

export function MonitorHud({
  lastResult,
  fps,
  latencyMs,
  drops,
}: MonitorHudProps) {
  const hasResult = Boolean(lastResult && lastResult.ok);
  const isBusy = lastResult?.error === 'DETECTOR_BUSY';

  return (
    <div
      className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border bg-card p-4 text-sm sm:grid-cols-4"
      role="region"
      aria-label="Monitor statistics"
    >
      <div>
        <span className="text-muted-foreground">Source count</span>
        <p className="tabular-nums text-lg font-semibold">
          {hasResult && lastResult ? lastResult.count : '—'}
        </p>
      </div>

      <div>
        <span className="text-muted-foreground">Zone smoothed</span>
        <p className="tabular-nums text-lg font-semibold">
          {hasResult && lastResult && lastResult.smoothed_count !== null
            ? lastResult.smoothed_count
            : '—'}
        </p>
      </div>

      <div>
        <span className="text-muted-foreground">Zone density</span>
        <p className="text-lg font-semibold">
          <DensityValue
            value={hasResult && lastResult ? lastResult.density : null}
          />
        </p>
      </div>

      <div>
        <span className="text-muted-foreground">Zone level</span>
        <div className="mt-0.5">
          <LevelBadge
            level={
              hasResult && lastResult?.level ? lastResult.level : 'NO_DATA'
            }
          />
        </div>
      </div>

      <div>
        <span className="text-muted-foreground">FPS</span>
        <p className="tabular-nums font-medium">{fps.toFixed(1)}</p>
      </div>

      <div>
        <span className="text-muted-foreground">Latency</span>
        <p className="tabular-nums font-medium">
          p50: {latencyMs.p50} ms · p95: {latencyMs.p95} ms
        </p>
      </div>

      <div>
        <span className="text-muted-foreground">Drops</span>
        <p className="tabular-nums font-medium">{drops}</p>
      </div>

      <div className="flex items-center">
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
  );
}
