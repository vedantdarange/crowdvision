import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ErrorBoundary } from 'react-error-boundary';
import { CheckCircle2, MapPin, XCircle } from 'lucide-react';
import type { Report, ReportKind, ReportStatus } from '@contract/types';
import { EmptyState } from '@/components/EmptyState';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Age } from '@/features/police/Alerts';
import { useZones } from '@/features/police/data';
import { formatDensity } from '@/lib/format';
import {
  compareReportsPendingFirst,
  useReports,
  useReviewReport,
  type ReportFilters,
} from './api';
import { ReportKindBadge, ReportStatusChip } from './ReportStatusBadge';

const ReportPinMap = lazy(() => import('./ReportPinMap'));

interface ReviewSelection {
  report: Report;
  status: 'VERIFIED' | 'DISMISSED';
  trigger: HTMLElement;
}

function ReviewDialog({
  selection,
  close,
}: {
  selection: ReviewSelection;
  close: () => void;
}) {
  const { report, status, trigger } = selection;
  const [note, setNote] = useState('');
  const reviewMutation = useReviewReport();
  const actionLabel = status === 'VERIFIED' ? 'Verify' : 'Dismiss';

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !reviewMutation.isPending) close();
      }}
    >
      <DialogContent
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          (trigger.isConnected
            ? trigger
            : document.getElementById('main')
          )?.focus();
        }}
      >
        <DialogTitle>
          {actionLabel} report #{report.id}
        </DialogTitle>
        <DialogDescription>
          {report.kind === 'SOS'
            ? `SOS report (${report.sos_type ?? 'OTHER'})`
            : 'Crowd photo report'}{' '}
          in {report.zone_name ?? 'Outside monitored zones'} by{' '}
          {report.created_by.name}.
        </DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!reviewMutation.isPending) {
              reviewMutation.mutate(
                { report, status, review_note: note },
                { onSettled: close },
              );
            }
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="report-review-note">Optional review note</Label>
            <Textarea
              id="report-review-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="E.g. Stewards dispatched to entrance barricade"
            />
          </div>
          <div className="police-actions justify-end">
            <DialogClose asChild>
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                disabled={reviewMutation.isPending}
              >
                Cancel
              </Button>
            </DialogClose>
            <Button
              type="submit"
              className="min-h-11"
              disabled={reviewMutation.isPending}
            >
              Confirm {actionLabel.toLowerCase()}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReportQueueBody({
  filters,
  setPage,
  onClearFilters,
  focusId,
  chooseReview,
}: {
  filters: ReportFilters;
  setPage: (page: number) => void;
  onClearFilters: () => void;
  focusId: number | null;
  chooseReview: (selection: ReviewSelection) => void;
}) {
  const {
    data: { data: rawRows, pagination },
  } = useReports(filters);
  const { data: zones } = useZones();

  const ordered = useMemo(
    () => [...rawRows].sort(compareReportsPendingFirst),
    [rawRows],
  );

  const [selectedPinId, setSelectedPinId] = useState<number | null>(focusId);
  const cardRefs = useRef(new Map<number, HTMLElement>());
  const scrolledFocusRef = useRef<number | null>(null);

  useEffect(() => {
    if (focusId !== null) {
      setSelectedPinId(focusId);
    }
  }, [focusId]);

  useEffect(() => {
    if (focusId === null || scrolledFocusRef.current === focusId) return;
    const target = cardRefs.current.get(focusId);
    if (!target) return;
    scrolledFocusRef.current = focusId;
    const reducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    if (typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'center',
      });
    }
  }, [focusId, ordered]);

  const activeReport =
    ordered.find((r) => r.id === selectedPinId) ??
    ordered.find((r) => r.id === focusId) ??
    ordered[0] ??
    null;

  const hasActiveFilter = Boolean(filters.kind || filters.status);
  const focusMissing =
    focusId !== null && !ordered.some((r) => r.id === focusId);

  if (!ordered.length) {
    return (
      <EmptyState
        title="No matching reports"
        description={
          hasActiveFilter
            ? 'No citizen reports match these filters.'
            : 'No crowd photos or SOS alerts have been submitted yet.'
        }
        action={
          hasActiveFilter ? (
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              onClick={onClearFilters}
            >
              Reset filters
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="police-grid">
      <div className="space-y-3">
        {focusMissing && hasActiveFilter && (
          <div
            role="status"
            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card p-3 text-sm"
          >
            <span>Report #{focusId} is hidden by the current filters.</span>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              onClick={onClearFilters}
            >
              Show all reports
            </Button>
          </div>
        )}

        <ul className="space-y-3">
          {ordered.map((report) => {
            const isSos = report.kind === 'SOS';
            const isFocused = focusId === report.id;
            const isPinned = activeReport?.id === report.id;

            return (
              <li
                key={report.id}
                ref={(el) => {
                  if (el) cardRefs.current.set(report.id, el);
                  else cardRefs.current.delete(report.id);
                }}
                data-report-id={report.id}
                data-focused={isFocused ? 'true' : undefined}
                tabIndex={isFocused ? -1 : undefined}
                className={`space-y-2 rounded-xl border bg-card p-4 transition ${
                  isSos ? 'border-l-4 border-l-red-600 shadow-sm' : ''
                } ${isFocused ? 'ring-primary bg-primary/5 ring-2' : ''}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <ReportKindBadge
                      kind={report.kind}
                      sosType={report.sos_type}
                    />
                    <ReportStatusChip status={report.status} />
                    <span className="text-muted-foreground text-xs">
                      #{report.id} · {report.created_by.name}
                    </span>
                  </div>
                  <Age ts={report.created_at} />
                </div>

                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  <strong>
                    {report.zone_name ?? 'Outside monitored zones'}
                  </strong>
                  <span className="text-muted-foreground text-xs">
                    GPS: {report.lat.toFixed(5)}, {report.lng.toFixed(5)}
                  </span>
                  {report.kind === 'CROWD' && report.count !== null && (
                    <span>
                      {report.count} counted
                      {report.density_hint !== null
                        ? ` (≈ ${formatDensity(report.density_hint)} /m²)`
                        : ''}
                    </span>
                  )}
                </div>

                {report.note && <p className="text-sm">{report.note}</p>}

                {report.reviewed_at && (
                  <p className="text-muted-foreground text-xs">
                    Reviewed by {report.reviewed_by?.name ?? 'Safety officer'} ·{' '}
                    <Age ts={report.reviewed_at} />
                    {report.review_note ? ` — "${report.review_note}"` : ''}
                  </p>
                )}

                <div className="police-actions pt-1">
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-11 gap-1.5"
                    aria-pressed={isPinned}
                    onClick={() => setSelectedPinId(report.id)}
                  >
                    <MapPin size={15} aria-hidden />
                    {isPinned ? 'Showing pin' : 'Pin on map'}
                  </Button>

                  {report.status === 'PENDING' && (
                    <>
                      <Button
                        type="button"
                        className="min-h-11 gap-1.5"
                        onClick={(event) =>
                          chooseReview({
                            report,
                            status: 'VERIFIED',
                            trigger: event.currentTarget,
                          })
                        }
                      >
                        <CheckCircle2 size={16} aria-hidden />
                        Verify
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        className="min-h-11 gap-1.5"
                        onClick={(event) =>
                          chooseReview({
                            report,
                            status: 'DISMISSED',
                            trigger: event.currentTarget,
                          })
                        }
                      >
                        <XCircle size={16} aria-hidden />
                        Dismiss
                      </Button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        {pagination.total_pages > 1 && (
          <div className="police-actions">
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={filters.page <= 1}
              onClick={() => setPage(filters.page - 1)}
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
              disabled={filters.page >= pagination.total_pages}
              onClick={() => setPage(filters.page + 1)}
            >
              Next
            </Button>
          </div>
        )}
      </div>

      {activeReport && (
        <aside
          aria-label="Selected report location"
          className="glass h-fit space-y-3"
        >
          <div>
            <h2>Report #{activeReport.id} location</h2>
            <p className="text-muted-foreground text-sm">
              {activeReport.zone_name ?? 'Outside monitored zones'} ·{' '}
              {activeReport.lat.toFixed(5)}, {activeReport.lng.toFixed(5)}
            </p>
          </div>
          <div className="police-map">
            <ErrorBoundary
              fallback={
                <p className="text-muted-foreground p-4 text-sm">
                  Map unavailable. Location: {activeReport.lat.toFixed(5)},{' '}
                  {activeReport.lng.toFixed(5)}
                </p>
              }
            >
              <Suspense
                fallback={
                  <p className="text-muted-foreground p-4 text-sm">
                    Loading location map...
                  </p>
                }
              >
                <ReportPinMap zones={zones} report={activeReport} />
              </Suspense>
            </ErrorBoundary>
          </div>
        </aside>
      )}
    </div>
  );
}

export function ReportReviewPage() {
  const [searchParams] = useSearchParams();
  const focusParam = searchParams.get('focus');
  const parsedFocus = focusParam ? Number(focusParam) : null;
  const focusId =
    parsedFocus !== null && Number.isFinite(parsedFocus) ? parsedFocus : null;

  const [kind, setKind] = useState<ReportKind | ''>('');
  const [status, setStatus] = useState<ReportStatus | ''>('');
  const [page, setPage] = useState(1);
  const [review, setReview] = useState<ReviewSelection | null>(null);

  const filters: ReportFilters = {
    kind,
    status,
    page,
    limit: 20,
  };

  function clearFilters() {
    setKind('');
    setStatus('');
    setPage(1);
  }

  return (
    <section className="police-page">
      <header>
        <div>
          <h1>Report review</h1>
          <p className="text-muted-foreground text-sm">
            Citizen crowd reports and SOS requests sorted with pending items
            first.
          </p>
        </div>
      </header>

      <div className="police-filters">
        <label>
          Kind
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as ReportKind | '');
              setPage(1);
            }}
          >
            <option value="">All kinds</option>
            <option value="SOS">SOS</option>
            <option value="CROWD">Crowd photo</option>
          </select>
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as ReportStatus | '');
              setPage(1);
            }}
          >
            <option value="">All (pending first)</option>
            <option value="PENDING">Pending</option>
            <option value="VERIFIED">Verified</option>
            <option value="DISMISSED">Dismissed</option>
          </select>
        </label>
      </div>

      <SuspenseBoundary>
        <ReportQueueBody
          filters={filters}
          setPage={setPage}
          onClearFilters={clearFilters}
          focusId={focusId}
          chooseReview={setReview}
        />
      </SuspenseBoundary>

      {review && (
        <ReviewDialog
          key={`${review.report.id}-${review.status}`}
          selection={review}
          close={() => setReview(null)}
        />
      )}
    </section>
  );
}
