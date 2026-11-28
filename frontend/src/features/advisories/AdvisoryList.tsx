import { useState } from 'react';
import { Info, OctagonAlert, Trash2, TriangleAlert } from 'lucide-react';
import type { Advisory } from '@contract/types';
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
import { Age } from '@/features/police/Alerts';
import { useZones } from '@/features/police/data';
import { AdvisoryForm } from './AdvisoryForm';
import { useAdvisories, useRetractAdvisory } from './api';

const SEVERITY_ICONS = {
  INFO: Info,
  WARNING: TriangleAlert,
  URGENT: OctagonAlert,
} as const;

interface RetractSelection {
  advisory: Advisory;
  trigger: HTMLElement;
}

function RetractDialog({
  selection,
  close,
}: {
  selection: RetractSelection;
  close: () => void;
}) {
  const { advisory, trigger } = selection;
  const retractMutation = useRetractAdvisory();

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !retractMutation.isPending) close();
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
        <DialogTitle>Retract advisory?</DialogTitle>
        <DialogDescription>
          Remove &ldquo;{advisory.title}&rdquo; from public pages and send a
          live removal update to connected citizens?
        </DialogDescription>
        <div className="police-actions justify-end pt-2">
          <DialogClose asChild>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={retractMutation.isPending}
            >
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            className="min-h-11"
            disabled={retractMutation.isPending}
            onClick={() =>
              retractMutation.mutate(advisory.id, { onSettled: close })
            }
          >
            Confirm retract
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AdvisoriesContent({
  onRequestRetract,
}: {
  onRequestRetract: (selection: RetractSelection) => void;
}) {
  const { data: zones } = useZones();
  const { data: advisories } = useAdvisories();

  return (
    <div className="police-grid">
      <AdvisoryForm zones={zones} />

      <section className="glass space-y-3" aria-label="Active advisories">
        <h2>Active advisories ({advisories.length})</h2>
        {!advisories.length ? (
          <EmptyState
            title="No active advisories"
            description="Published advisories appear here and reach citizens live."
          />
        ) : (
          <ul className="space-y-3">
            {[...advisories]
              .sort((a, b) => b.created_at.localeCompare(a.created_at))
              .map((advisory) => {
                const Icon = SEVERITY_ICONS[advisory.severity];
                return (
                  <li
                    key={advisory.id}
                    className="space-y-2 rounded-xl border bg-card p-3.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-semibold">
                        <Icon size={14} aria-hidden />
                        <span>{advisory.severity}</span>
                      </span>
                      <span className="text-muted-foreground text-xs">
                        {advisory.zone_name ?? 'All zones (global)'}
                      </span>
                    </div>
                    <h3 className="font-semibold">{advisory.title}</h3>
                    <p className="text-sm">{advisory.body}</p>
                    <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs">
                      <div className="text-muted-foreground space-x-2">
                        <span>{advisory.created_by.name}</span>
                        <span>·</span>
                        <Age ts={advisory.created_at} />
                        {advisory.expires_at && (
                          <>
                            <span>· Expires</span>
                            <Age ts={advisory.expires_at} />
                          </>
                        )}
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        className="min-h-11 gap-1.5"
                        onClick={(event) =>
                          onRequestRetract({
                            advisory,
                            trigger: event.currentTarget,
                          })
                        }
                      >
                        <Trash2 size={15} aria-hidden />
                        Retract
                      </Button>
                    </div>
                  </li>
                );
              })}
          </ul>
        )}
      </section>
    </div>
  );
}

export function PoliceAdvisoriesPage() {
  const [retractTarget, setRetractTarget] = useState<RetractSelection | null>(
    null,
  );

  return (
    <section className="police-page">
      <header>
        <div>
          <h1>Broadcast advisory</h1>
          <p className="text-muted-foreground text-sm">
            Send public venue notices or zone warnings in real time and manage
            active broadcasts.
          </p>
        </div>
      </header>

      <SuspenseBoundary>
        <AdvisoriesContent onRequestRetract={setRetractTarget} />
      </SuspenseBoundary>

      {retractTarget && (
        <RetractDialog
          key={retractTarget.advisory.id}
          selection={retractTarget}
          close={() => setRetractTarget(null)}
        />
      )}
    </section>
  );
}
