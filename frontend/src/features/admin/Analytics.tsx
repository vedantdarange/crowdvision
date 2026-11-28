import { lazy, Suspense, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ManagementPage, WriteError } from './ManagementLayout';
import { useAnalytics, downloadAlerts, type Range } from './managementApi';
const Chart = lazy(() => import('./AlertsByZoneChart'));
export function duration(seconds: number | null) {
  if (seconds === null) return 'No data';
  const whole = Math.round(seconds);
  return Math.floor(whole / 60) + ':' + String(whole % 60).padStart(2, '0');
}
function localInput(iso: string) {
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function Analytics({
  range,
  setRange,
}: {
  range: Range;
  setRange: (range: Range) => void;
}) {
  const [from, setFrom] = useState(() => localInput(range.from)),
    [to, setTo] = useState(() => localInput(range.to));
  const { data } = useAnalytics(range);
  const csv = useMutation({ mutationFn: downloadAlerts });
  const hasAlerts = data.alerts_by_zone.some((z) => z.warning || z.critical);
  return (
    <>
      <form
        className="glass police-filters"
        onSubmit={(e) => {
          e.preventDefault();
          setRange({
            from: new Date(from).toISOString(),
            to: new Date(to).toISOString(),
          });
        }}
      >
        <label>
          From (local time)
          <input
            type="datetime-local"
            required
            value={from}
            max={to}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label>
          To (local time)
          <input
            type="datetime-local"
            required
            value={to}
            min={from}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <Button>Apply range</Button>
      </form>
      <div className="grid gap-4 sm:grid-cols-2">
        {[
          ['Average acknowledge time', duration(data.avg_ack_seconds)],
          ['Average resolve time', duration(data.avg_resolve_seconds)],
        ].map(([title, value]) => (
          <section className="glass" key={title}>
            <h2>{title}</h2>
            <p className="text-2xl tabular-nums">{value}</p>
          </section>
        ))}
      </div>
      <section className="glass">
        <header>
          <h2>Alerts per zone</h2>
          <Button
            variant="outline"
            disabled={csv.isPending}
            onClick={() => csv.mutate(range)}
          >
            Download alerts CSV
          </Button>
        </header>
        <WriteError error={csv.error} />
        {hasAlerts ? (
          <>
            <Suspense fallback={<Skeleton className="h-56" />}>
              <Chart rows={data.alerts_by_zone} />
            </Suspense>
            <ul>
              {data.alerts_by_zone.map((z) => (
                <li key={z.zone_id}>
                  {z.zone_name} · Warning {z.warning} · Critical {z.critical}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p>No alerts in this range. Select a wider date range.</p>
        )}
      </section>
      <section className="glass">
        <h2>Peak hours by zone (IST)</h2>
        {data.peak_hours.length ? (
          <ul>
            {data.peak_hours.map((p) => (
              <li key={p.zone_id + '-' + p.hour}>
                {p.zone_name} · {String(p.hour).padStart(2, '0')}:00 IST ·{' '}
                {p.avg_density.toFixed(1)} people/m²
              </li>
            ))}
          </ul>
        ) : (
          <p>No density readings in this range.</p>
        )}
      </section>
      <section className="glass">
        <h2>Reports by status</h2>
        {Object.values(data.reports_by_status).some(Boolean) ? (
          <dl>
            {Object.entries(data.reports_by_status).map(([status, count]) => (
              <div key={status} className="flex gap-3">
                <dt>{status}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p>No reports in this range.</p>
        )}
      </section>
    </>
  );
}
export function Component() {
  const [range, setRange] = useState<Range>(() => {
    const now = Date.now();
    return {
      from: new Date(now - 86400000).toISOString(),
      to: new Date(now).toISOString(),
    };
  });
  return (
    <ManagementPage title="Analytics">
      <Analytics range={range} setRange={setRange} />
    </ManagementPage>
  );
}
