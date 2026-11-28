import { useState } from 'react';
import { Link } from 'react-router';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { Button } from '@/components/ui/button';
import { LevelBadge } from '@/components/status/LevelBadge';
import {
  Actions,
  Age,
  AlertCard,
  Status,
  label,
  useAlertDialog,
  type Choose,
} from './Alerts';
import { useAlerts, useZones, type Filters } from './data';
const statuses = [
  'NEW',
  'ACKNOWLEDGED',
  'RESPONDING',
  'RESOLVED',
  'AUTO_CLEARED',
];
export function Queue() {
  const { data: zones } = useZones();
  const [tab, setTab] = useState('active'),
    [page, setPage] = useState(1);
  const [fields, setFields] = useState({
    status: '',
    level: '',
    zone_id: '',
    from: '',
    to: '',
  });
  function change(key: keyof typeof fields, value: string) {
    setFields((f) => ({ ...f, [key]: value }));
    setPage(1);
  }
  const filters: Filters = {
    ...fields,
    active: tab === 'active',
    page,
    limit: 10,
    from: fields.from
      ? new Date(fields.from + 'T00:00:00').toISOString()
      : undefined,
    to: fields.to
      ? new Date(fields.to + 'T23:59:59.999').toISOString()
      : undefined,
  };
  const { choose, dialog } = useAlertDialog();
  return (
    <section className="police-page">
      <h1>Alert queue</h1>
      <Tabs
        value={tab}
        onValueChange={(value) => {
          setTab(value);
          setPage(1);
          if (value === 'active' && statuses.slice(3).includes(fields.status))
            change('status', '');
        }}
      >
        <TabsList aria-label="Alert history">
          <TabsTrigger value="active">Active</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>
        <div className="police-filters">
          <label>
            Status
            <select
              value={fields.status}
              onChange={(e) => change('status', e.target.value)}
            >
              <option value="">Any status</option>
              {(tab === 'active' ? statuses.slice(0, 3) : statuses).map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Level
            <select
              value={fields.level}
              onChange={(e) => change('level', e.target.value)}
            >
              <option value="">Any level</option>
              <option value="WARNING">Warning</option>
              <option value="CRITICAL">Critical</option>
            </select>
          </label>
          <label>
            Zone
            <select
              value={fields.zone_id}
              onChange={(e) => change('zone_id', e.target.value)}
            >
              <option value="">All zones</option>
              {zones.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            From
            <input
              type="date"
              max={fields.to || undefined}
              value={fields.from}
              onChange={(e) => change('from', e.target.value)}
            />
          </label>
          <label>
            Through
            <input
              type="date"
              min={fields.from || undefined}
              value={fields.to}
              onChange={(e) => change('to', e.target.value)}
            />
          </label>
        </div>
        {['active', 'all'].map((value) => (
          <TabsContent key={value} value={value}>
            {fields.from && fields.to && fields.from > fields.to ? (
              <p role="alert">Choose an end date on or after the start date.</p>
            ) : (
              <SuspenseBoundary>
                <Results filters={filters} setPage={setPage} choose={choose} />
              </SuspenseBoundary>
            )}
          </TabsContent>
        ))}
      </Tabs>
      {dialog}
    </section>
  );
}
function Results({
  filters,
  setPage,
  choose,
}: {
  filters: Filters;
  setPage: (n: number) => void;
  choose: Choose;
}) {
  const {
    data: { data: rows, pagination },
  } = useAlerts(filters);
  const hasFilter =
    filters.status ||
    filters.zone_id ||
    filters.level ||
    filters.from ||
    filters.to;
  return (
    <div className="glass">
      {!rows.length ? (
        <p>
          {hasFilter
            ? 'No alerts match these filters.'
            : filters.active && !pagination.total
              ? 'No active alerts. All zones within limits.'
              : 'No alerts on this page.'}
        </p>
      ) : (
        <>
          <div className="queue-table">
            <table>
              <caption className="sr-only">Alerts by creation time</caption>
              <thead>
                <tr>
                  {['Zone', 'Level', 'Status', 'Created', 'Actions'].map(
                    (s) => (
                      <th key={s} scope="col">
                        {s}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <Link to={'/police/alerts/' + a.id}>
                        {a.zone_name} · #{a.id}
                      </Link>
                    </td>
                    <td>
                      <LevelBadge level={a.level} />
                    </td>
                    <td>
                      <Status alert={a} />
                    </td>
                    <td>
                      <Age ts={a.created_at} />
                    </td>
                    <td>
                      <Actions alert={a} choose={choose} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="queue-cards">
            {rows.map((a) => (
              <AlertCard key={a.id} alert={a} choose={choose} />
            ))}
          </div>
        </>
      )}
      {(pagination.total_pages > 1 || filters.page > 1) && (
        <nav aria-label="Alert pages" className="police-actions">
          <Button
            disabled={filters.page === 1}
            onClick={() => setPage(filters.page - 1)}
          >
            Previous
          </Button>
          <span>
            Page {filters.page} of {Math.max(1, pagination.total_pages)}
          </span>
          <Button
            disabled={filters.page >= pagination.total_pages}
            onClick={() => setPage(filters.page + 1)}
          >
            Next
          </Button>
        </nav>
      )}
    </div>
  );
}
