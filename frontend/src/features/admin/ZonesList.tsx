import { useState } from 'react';
import { Link } from 'react-router';
import {
  AlertTriangle,
  CheckCircle2,
  MapPin,
  Pencil,
  Plus,
  PowerOff,
  XCircle,
} from 'lucide-react';
import type { ZoneState } from '@contract/types';
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiRequestError } from '@/lib/apiClient';
import { useAdminZones, useDeactivateZone } from './api';

interface DeactivateTarget {
  zone: ZoneState;
  trigger: HTMLElement;
}

function formatThresholds(zone: ZoneState): string {
  const density = `${zone.warning_density} / ${zone.critical_density} p/m²`;
  if (
    zone.mode === 'COUNT' &&
    zone.warning_count !== null &&
    zone.critical_count !== null
  ) {
    return `${zone.warning_count} / ${zone.critical_count} people (${density})`;
  }
  return density;
}

function DeactivateDialog({
  target,
  onConflictAlert,
  close,
}: {
  target: DeactivateTarget;
  onConflictAlert: (zone: ZoneState) => void;
  close: () => void;
}) {
  const { zone, trigger } = target;
  const deactivateMutation = useDeactivateZone();

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !deactivateMutation.isPending) close();
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
        <DialogTitle>Deactivate &ldquo;{zone.name}&rdquo;?</DialogTitle>
        <DialogDescription>
          Visitors and monitoring streams will stop tracking this zone, and its
          name can be reused later. Zones with an open alert cannot be
          deactivated.
        </DialogDescription>
        <div className="police-actions justify-end pt-2">
          <DialogClose asChild>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={deactivateMutation.isPending}
            >
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            className="min-h-11"
            disabled={deactivateMutation.isPending}
            onClick={() =>
              deactivateMutation.mutate(zone.id, {
                onError: (error) => {
                  if (
                    error instanceof ApiRequestError &&
                    error.status === 409
                  ) {
                    onConflictAlert(zone);
                  }
                },
                onSettled: close,
              })
            }
          >
            Confirm deactivate
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ZonesTableBody({
  onRequestDeactivate,
  conflictZone,
  clearConflict,
}: {
  onRequestDeactivate: (target: DeactivateTarget) => void;
  conflictZone: ZoneState | null;
  clearConflict: () => void;
}) {
  const { data: zones } = useAdminZones();

  if (!zones.length) {
    return (
      <EmptyState
        title="No zones configured"
        description="Draw your first monitored venue zone on the map to begin crowd counting."
        action={
          <Button asChild className="min-h-11 gap-1.5">
            <Link to="/admin/zones/new">
              <Plus size={16} aria-hidden />
              New zone
            </Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      {conflictZone && (
        <div
          role="alert"
          className="bg-critical-bg text-critical border-critical/40 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm font-medium"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle size={18} aria-hidden />
            <span>
              Resolve its alert first before deactivating{' '}
              <strong>{conflictZone.name}</strong>.
            </span>
          </div>
          <div className="flex items-center gap-2">
            {conflictZone.open_alert_id && (
              <Link
                to={`/police/alerts/${conflictZone.open_alert_id}`}
                className="inline-flex min-h-11 items-center underline"
              >
                Open alert #{conflictZone.open_alert_id}
              </Link>
            )}
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              onClick={clearConflict}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}

      <div className="glass queue-table">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead>Thresholds</TableHead>
              <TableHead>Area</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Sources</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {zones.map((zone) => (
              <TableRow key={zone.id}>
                <TableCell className="font-semibold">
                  <div className="flex items-center gap-2">
                    <MapPin size={15} aria-hidden />
                    <span>{zone.name}</span>
                  </div>
                </TableCell>
                <TableCell>
                  {zone.mode === 'COUNT' ? 'Count' : 'Density'}
                </TableCell>
                <TableCell>{formatThresholds(zone)}</TableCell>
                <TableCell>{zone.area_m2.toFixed(1)} m²</TableCell>
                <TableCell>
                  {zone.is_active ? (
                    <span className="bg-safe-bg text-safe border-safe/30 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold">
                      <CheckCircle2 size={13} aria-hidden />
                      Active
                    </span>
                  ) : (
                    <span className="bg-muted text-muted-foreground inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold">
                      <XCircle size={13} aria-hidden />
                      Inactive
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Link
                    to={`/admin/sources?zone_id=${zone.id}`}
                    className="inline-flex min-h-11 items-center underline"
                  >
                    {zone.sources.length}{' '}
                    {zone.sources.length === 1 ? 'source' : 'sources'}
                  </Link>
                </TableCell>
                <TableCell className="text-right">
                  <div className="police-actions justify-end">
                    <Button
                      asChild
                      variant="outline"
                      className="min-h-11 gap-1.5"
                    >
                      <Link to={`/admin/zones/${zone.id}/edit`}>
                        <Pencil size={15} aria-hidden />
                        Edit
                      </Link>
                    </Button>
                    {zone.is_active && (
                      <Button
                        type="button"
                        variant="outline"
                        className="min-h-11 gap-1.5"
                        onClick={(event) =>
                          onRequestDeactivate({
                            zone,
                            trigger: event.currentTarget,
                          })
                        }
                      >
                        <PowerOff size={15} aria-hidden />
                        Deactivate
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="glass queue-cards">
        {zones.map((zone) => (
          <article key={zone.id} className="alert-card">
            <div className="flex w-full flex-wrap items-center justify-between gap-2">
              <strong className="inline-flex items-center gap-1.5">
                <MapPin size={15} aria-hidden />
                {zone.name}
              </strong>
              {zone.is_active ? (
                <span className="bg-safe-bg text-safe border-safe/30 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold">
                  <CheckCircle2 size={13} aria-hidden />
                  Active
                </span>
              ) : (
                <span className="bg-muted text-muted-foreground inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold">
                  <XCircle size={13} aria-hidden />
                  Inactive
                </span>
              )}
            </div>
            <p className="w-full text-sm">
              {zone.mode === 'COUNT' ? 'Count' : 'Density'} ·{' '}
              {formatThresholds(zone)} · {zone.area_m2.toFixed(1)} m²
            </p>
            <div className="police-actions w-full justify-between">
              <Link
                to={`/admin/sources?zone_id=${zone.id}`}
                className="inline-flex min-h-11 items-center underline"
              >
                {zone.sources.length}{' '}
                {zone.sources.length === 1 ? 'source' : 'sources'}
              </Link>
              <div className="police-actions">
                <Button asChild variant="outline" className="min-h-11 gap-1.5">
                  <Link to={`/admin/zones/${zone.id}/edit`}>
                    <Pencil size={15} aria-hidden />
                    Edit
                  </Link>
                </Button>
                {zone.is_active && (
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-11 gap-1.5"
                    onClick={(event) =>
                      onRequestDeactivate({
                        zone,
                        trigger: event.currentTarget,
                      })
                    }
                  >
                    <PowerOff size={15} aria-hidden />
                    Deactivate
                  </Button>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

export function AdminZonesPage() {
  const [deactivateTarget, setDeactivateTarget] =
    useState<DeactivateTarget | null>(null);
  const [conflictZone, setConflictZone] = useState<ZoneState | null>(null);

  return (
    <section className="police-page">
      <header>
        <div>
          <h1>Zones</h1>
          <p className="text-muted-foreground text-sm">
            Draw venue zone polygons, configure Fruin density/count limits, and
            manage active zones.
          </p>
        </div>
        <Button asChild className="min-h-11 gap-1.5">
          <Link to="/admin/zones/new">
            <Plus size={16} aria-hidden />
            New zone
          </Link>
        </Button>
      </header>

      <SuspenseBoundary>
        <ZonesTableBody
          onRequestDeactivate={setDeactivateTarget}
          conflictZone={conflictZone}
          clearConflict={() => setConflictZone(null)}
        />
      </SuspenseBoundary>

      {deactivateTarget && (
        <DeactivateDialog
          key={deactivateTarget.zone.id}
          target={deactivateTarget}
          onConflictAlert={(zone) => setConflictZone(zone)}
          close={() => setDeactivateTarget(null)}
        />
      )}
    </section>
  );
}
