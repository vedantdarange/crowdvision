import { useState } from 'react';
import { Link } from 'react-router';
import { EmptyState } from '@/components/EmptyState';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { Button } from '@/components/ui/button';
import { Age } from '@/features/police/Alerts';
import { formatDensity } from '@/lib/format';
import { useMyReports } from './api';
import { ReportKindBadge, ReportStatusChip } from './ReportStatusBadge';

function MyReportsContent({
  page,
  setPage,
}: {
  page: number;
  setPage: (next: number) => void;
}) {
  const {
    data: { data: rows, pagination },
  } = useMyReports(page, 20);

  if (!rows.length && page === 1) {
    return (
      <EmptyState
        title="No reports sent yet"
        description="Share a crowd photo or send an SOS report when you see congestion or need help."
        action={
          <div className="flex flex-wrap justify-center gap-3">
            <Button asChild className="min-h-11">
              <Link to="/report/crowd">Report a crowd</Link>
            </Button>
            <Button asChild variant="outline" className="min-h-11">
              <Link to="/report/sos">Send SOS</Link>
            </Button>
          </div>
        }
      />
    );
  }

  const ordered = [...rows].sort(
    (a, b) =>
      Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id,
  );

  return (
    <div className="space-y-4">
      <ul className="space-y-3">
        {ordered.map((report) => (
          <li
            key={report.id}
            className="space-y-2 rounded-xl border bg-card p-4 shadow-xs"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <ReportKindBadge kind={report.kind} sosType={report.sos_type} />
                <ReportStatusChip status={report.status} />
                <span className="text-muted-foreground text-xs">
                  #{report.id}
                </span>
              </div>
              <Age ts={report.created_at} />
            </div>

            <div className="text-sm font-medium">
              {report.zone_name ?? 'Outside monitored zones'}
              {report.kind === 'CROWD' && report.count !== null && (
                <span>
                  {' '}
                  · {report.count} detected
                  {report.density_hint !== null
                    ? ` (≈ ${formatDensity(report.density_hint)} /m²)`
                    : ''}
                </span>
              )}
            </div>

            {report.note && <p className="text-sm">{report.note}</p>}

            {report.reviewed_at && (
              <div className="text-muted-foreground border-t pt-2 text-xs">
                <span>
                  Reviewed by {report.reviewed_by?.name ?? 'Safety officer'} ·{' '}
                  <Age ts={report.reviewed_at} />
                </span>
                {report.review_note && (
                  <p className="text-foreground mt-1 text-sm">
                    Responder note: {report.review_note}
                  </p>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>

      {pagination.total_pages > 1 && (
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </Button>
          <span className="text-sm">
            Page {pagination.page} of {pagination.total_pages}
          </span>
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            disabled={page >= pagination.total_pages}
            onClick={() => setPage(page + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

export function MyReportsPage() {
  const [page, setPage] = useState(1);

  return (
    <section className="mx-auto max-w-3xl space-y-5 p-4 pb-12">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">My reports</h1>
          <p className="text-muted-foreground text-sm">
            Live review status of crowd photos and SOS alerts you have
            submitted.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" className="min-h-11">
            <Link to="/report/crowd">Report crowd</Link>
          </Button>
          <Button asChild variant="outline" className="min-h-11">
            <Link to="/report/sos">Send SOS</Link>
          </Button>
        </div>
      </header>

      <SuspenseBoundary>
        <MyReportsContent page={page} setPage={setPage} />
      </SuspenseBoundary>
    </section>
  );
}
