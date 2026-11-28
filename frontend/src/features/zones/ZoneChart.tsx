import { useMemo } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';
import type { HistoryPoint, Level, ZoneState } from '@contract/types';
import {
  ChartContainer,
  ChartTooltip,
  type ChartConfig,
} from '@/components/ui/chart';
import { EmptyState } from '@/components/EmptyState';
import { useSeries, type SeriesPoint } from '@/features/police/data';
import { formatDensity } from '@/lib/format';

export interface ZoneChartPoint {
  ts: string;
  count: number | null;
  density: number | null;
  level: Level;
}

export interface ZoneChartProps {
  zone: ZoneState;
  historyPoints?: readonly HistoryPoint[];
  /** Explicit point override (useful in unit tests); otherwise merges history + live series. */
  points?: readonly ZoneChartPoint[];
  showSeconds?: boolean;
}

const LEVEL_TEXT: Record<Level, string> = {
  SAFE: 'Safe',
  WARNING: 'Warning',
  CRITICAL: 'Critical',
  NO_DATA: 'No data',
};

const chartConfig = {
  value: {
    label: 'Metric',
    theme: {
      light: '#0f766e',
      dark: '#5eead4',
    },
  },
} satisfies ChartConfig;

export function mergeChartPoints(
  historyPoints: readonly HistoryPoint[],
  livePoints: readonly SeriesPoint[],
): ZoneChartPoint[] {
  const byTs = new Map<string, ZoneChartPoint>();
  for (const p of historyPoints) {
    byTs.set(p.ts, {
      ts: p.ts,
      count: p.count,
      density: p.density,
      level: p.level,
    });
  }
  const lastHistoryTs = historyPoints.at(-1)?.ts ?? '';
  for (const p of livePoints) {
    if (!lastHistoryTs || p.ts >= lastHistoryTs) {
      byTs.set(p.ts, {
        ts: p.ts,
        count: p.count,
        density: p.density,
        level: p.level,
      });
    }
  }
  return [...byTs.values()]
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
    .slice(-300);
}

function formatAxisTime(ts: string, showSeconds: boolean): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    ...(showSeconds ? { second: '2-digit' } : {}),
  });
}

export function ZoneTooltipContent({
  active,
  payload,
  zone,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{
    payload?: ZoneChartPoint & { value: number | null; timeLabel: string };
  }>;
  zone: ZoneState;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;

  const isCount = zone.mode === 'COUNT';
  const metricText =
    row.value === null
      ? 'No data'
      : isCount
        ? `${row.count ?? '—'} people (${formatDensity(row.density)} /m²)`
        : `${formatDensity(row.density)} people/m² (${row.count ?? '—'} people)`;

  return (
    <div className="grid min-w-36 gap-1 rounded-lg border border-border/60 bg-background px-3 py-2 text-xs shadow-lg">
      <p className="font-medium text-foreground">
        {new Date(row.ts).toLocaleTimeString()}
      </p>
      <p className="tabular-nums font-semibold text-foreground">{metricText}</p>
      <p className="text-muted-foreground">
        Level:{' '}
        <strong className="text-foreground">{LEVEL_TEXT[row.level]}</strong>
      </p>
    </div>
  );
}

export default function ZoneChart({
  zone,
  historyPoints = [],
  points,
  showSeconds = true,
}: ZoneChartProps) {
  const liveSeries = useSeries((s) => s.zones[zone.id]);

  const merged = useMemo(() => {
    if (points) return points.slice(-300);
    return mergeChartPoints(historyPoints, liveSeries ?? []);
  }, [points, historyPoints, liveSeries]);

  const isCount = zone.mode === 'COUNT';
  const warningThreshold = isCount ? zone.warning_count : zone.warning_density;
  const criticalThreshold = isCount
    ? zone.critical_count
    : zone.critical_density;

  const chartData = useMemo(
    () =>
      merged.map((p) => ({
        ...p,
        value: isCount ? p.count : p.density,
        timeLabel: formatAxisTime(p.ts, showSeconds),
      })),
    [merged, isCount, showSeconds],
  );

  if (chartData.length === 0) {
    return (
      <EmptyState
        title="No history samples yet"
        description="Start a camera or video feed in Monitor to stream live occupancy samples."
      />
    );
  }

  const maxData = chartData.reduce(
    (max, item) => (item.value !== null && item.value > max ? item.value : max),
    0,
  );
  const maxThreshold = Math.max(
    warningThreshold ?? 0,
    criticalThreshold ?? 0,
    isCount ? 1 : 0.5,
  );
  const yMax = Math.ceil(Math.max(maxData, maxThreshold) * 1.15 * 10) / 10;

  return (
    <div className="space-y-2">
      <ChartContainer config={chartConfig} className="h-64 w-full">
        <LineChart
          data={chartData}
          margin={{ top: 14, right: 20, bottom: 4, left: 4 }}
        >
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="timeLabel"
            tickLine={false}
            axisLine={false}
            minTickGap={28}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            domain={[0, yMax]}
            tickLine={false}
            axisLine={false}
            width={42}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => (isCount ? String(v) : v.toFixed(1))}
          />
          <ChartTooltip
            content={<ZoneTooltipContent zone={zone} />}
            isAnimationActive={false}
          />
          {warningThreshold !== null && (
            <ReferenceLine
              y={warningThreshold}
              stroke="#f59e0b"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              ifOverflow="extendDomain"
              label={{
                value: `Warning (${warningThreshold})`,
                position: 'insideTopRight',
                fill: 'var(--level-warning)',
                fontSize: 11,
              }}
            />
          )}
          {criticalThreshold !== null && (
            <ReferenceLine
              y={criticalThreshold}
              stroke="#ef4444"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              ifOverflow="extendDomain"
              label={{
                value: `Critical (${criticalThreshold})`,
                position: 'insideTopRight',
                fill: 'var(--level-critical)',
                fontSize: 11,
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="value"
            name={isCount ? 'Count' : 'Density'}
            stroke="var(--color-value)"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ChartContainer>
      <p className="text-xs text-muted-foreground">
        {isCount ? 'People count' : 'Density (people/m²)'} · Showing{' '}
        {chartData.length} point{chartData.length === 1 ? '' : 's'} (max 300)
      </p>
    </div>
  );
}
