import { Suspense, useEffect, useState } from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import { QueryErrorResetBoundary } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { Camera, Film, Plus, Radio, WifiOff } from 'lucide-react';
import { toast } from 'sonner';
import type { SourceInfo, SourceKind, ZoneState } from '@contract/types';
import { ApiRequestError } from '@/lib/apiClient';
import { useCreateSource, useSources } from '@/features/police/data';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

const createSourceSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, 'Enter a source name.')
    .max(255, 'Source name must be at most 255 characters.'),
  kind: z.enum(['WEBCAM', 'VIDEO_FILE']),
});

type CreateSourceValues = z.infer<typeof createSourceSchema>;

export interface SourcePickerProps {
  zones: ZoneState[];
  selectedZoneId: number;
  selectedSourceId: number | null;
  onSelectZone: (zoneId: number) => void;
  onSelectSource: (source: SourceInfo | null) => void;
  defaultKind?: SourceKind;
  disabled?: boolean;
}

function SourceStatusChip({ status }: { status: SourceInfo['status'] }) {
  const online = status === 'ONLINE';
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ${
        online ? 'bg-safe-bg text-safe' : 'bg-no-data-bg text-no-data'
      }`}
    >
      {online ? (
        <Radio aria-hidden="true" size={14} />
      ) : (
        <WifiOff aria-hidden="true" size={14} />
      )}
      <span>{online ? 'Online' : 'Offline'}</span>
    </span>
  );
}

function SourceListSection({
  zoneId,
  selectedSourceId,
  onSelectSource,
  defaultKind,
  disabled,
}: {
  zoneId: number;
  selectedSourceId: number | null;
  onSelectSource: (source: SourceInfo | null) => void;
  defaultKind: SourceKind;
  disabled: boolean;
}) {
  const { data: allSources } = useSources(zoneId);
  const activeSources = allSources.filter((s) => s.is_active);
  const selectedSource =
    activeSources.find((s) => s.id === selectedSourceId) ?? null;

  const [showCreate, setShowCreate] = useState(false);
  const createSource = useCreateSource();

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateSourceValues>({
    resolver: zodResolver(createSourceSchema),
    defaultValues: { name: '', kind: defaultKind },
  });

  // Auto-select the first active source of the zone if none is selected.
  useEffect(() => {
    if (selectedSourceId === null && activeSources[0]) {
      onSelectSource(activeSources[0]);
    } else if (
      selectedSourceId !== null &&
      activeSources.length > 0 &&
      !activeSources.some((s) => s.id === selectedSourceId)
    ) {
      onSelectSource(activeSources[0] ?? null);
    } else if (selectedSourceId !== null && activeSources.length === 0) {
      onSelectSource(null);
    }
  }, [activeSources, selectedSourceId, onSelectSource]);

  const formOpen = showCreate || activeSources.length === 0;

  async function onSubmit(values: CreateSourceValues) {
    try {
      const created = await createSource.mutateAsync({
        zone_id: zoneId,
        name: values.name.trim(),
        kind: values.kind,
      });
      toast.success(`Source "${created.name}" created`);
      reset({ name: '', kind: values.kind });
      setShowCreate(false);
      onSelectSource(created);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        if (error.status === 422 && error.details) {
          let mapped = false;
          for (const field of ['name', 'kind'] as const) {
            const msgs = error.details[field];
            if (Array.isArray(msgs) && typeof msgs[0] === 'string') {
              setError(field, { message: msgs[0] }, { shouldFocus: !mapped });
              mapped = true;
            }
          }
          if (mapped) return;
        }
        setError('root', { message: error.message });
        toast.error(error.message);
      } else {
        setError('root', {
          message: 'Could not create source. Please try again.',
        });
      }
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1 space-y-1.5">
          <Label htmlFor="monitor-source-select">Camera / feed source</Label>
          <select
            id="monitor-source-select"
            value={selectedSource ? String(selectedSource.id) : ''}
            disabled={disabled || activeSources.length === 0}
            onChange={(e) => {
              const id = Number(e.target.value);
              const next = activeSources.find((s) => s.id === id) ?? null;
              onSelectSource(next);
            }}
            className="block h-11 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
          >
            {activeSources.length === 0 ? (
              <option value="">No sources in this zone yet</option>
            ) : (
              activeSources.map((s) => (
                <option key={s.id} value={String(s.id)}>
                  {s.name} ({s.kind === 'WEBCAM' ? 'Webcam' : 'Video file'})
                </option>
              ))
            )}
          </select>
        </div>

        {activeSources.length > 0 && (
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            onClick={() => setShowCreate((v) => !v)}
            aria-expanded={formOpen}
          >
            <Plus aria-hidden="true" size={16} />
            {showCreate ? 'Cancel' : 'New source'}
          </Button>
        )}
      </div>

      {selectedSource && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-muted/40 px-3 py-2 text-xs">
          <span className="inline-flex items-center gap-1.5 font-medium">
            {selectedSource.kind === 'WEBCAM' ? (
              <Camera aria-hidden="true" size={14} />
            ) : (
              <Film aria-hidden="true" size={14} />
            )}
            {selectedSource.kind === 'WEBCAM' ? 'Webcam' : 'Video file'}
          </span>
          <SourceStatusChip status={selectedSource.status} />
          <span className="text-muted-foreground">
            Coverage:{' '}
            <strong className="tabular-nums text-foreground">
              {selectedSource.coverage_area_m2} m²
            </strong>{' '}
            <span>(set by an admin in /admin/sources)</span>
          </span>
        </div>
      )}

      {formOpen && (
        <form
          noValidate
          onSubmit={handleSubmit(onSubmit)}
          className="space-y-3 rounded-lg border bg-card/80 p-3"
          aria-label="Create new source"
        >
          <p className="text-sm font-medium">
            {activeSources.length === 0
              ? 'No sources yet — create one for this zone'
              : 'Add a source to this zone'}
          </p>
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_11rem]">
            <div className="space-y-1.5">
              <Label htmlFor="new-source-name">Source name</Label>
              <Input
                id="new-source-name"
                placeholder="e.g. Gate East Webcam"
                aria-invalid={!!errors.name}
                aria-describedby={
                  errors.name ? 'new-source-name-error' : undefined
                }
                {...register('name')}
              />
              {errors.name && (
                <p
                  id="new-source-name-error"
                  role="alert"
                  className="text-xs font-medium text-destructive"
                >
                  {errors.name.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="new-source-kind">Kind</Label>
              <select
                id="new-source-kind"
                aria-invalid={!!errors.kind}
                aria-describedby={
                  errors.kind ? 'new-source-kind-error' : undefined
                }
                {...register('kind')}
                className="block h-11 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring"
              >
                <option value="WEBCAM">Webcam</option>
                <option value="VIDEO_FILE">Video file</option>
              </select>
              {errors.kind && (
                <p
                  id="new-source-kind-error"
                  role="alert"
                  className="text-xs font-medium text-destructive"
                >
                  {errors.kind.message}
                </p>
              )}
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Coverage defaults to the zone area (set by an admin in
            /admin/sources).
          </p>

          {errors.root && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {errors.root.message}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button type="submit" className="min-h-11" disabled={isSubmitting}>
              {isSubmitting ? 'Creating…' : 'Create source'}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export function SourcePicker({
  zones,
  selectedZoneId,
  selectedSourceId,
  onSelectZone,
  onSelectSource,
  defaultKind = 'WEBCAM',
  disabled = false,
}: SourcePickerProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="monitor-zone-select">Zone</Label>
        <select
          id="monitor-zone-select"
          value={selectedZoneId ? String(selectedZoneId) : ''}
          disabled={disabled || zones.length === 0}
          onChange={(e) => onSelectZone(Number(e.target.value))}
          className="block h-11 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
        >
          {zones.length === 0 ? (
            <option value="">No active zones</option>
          ) : (
            zones.map((z) => (
              <option key={z.id} value={String(z.id)}>
                {z.name} ({z.mode === 'COUNT' ? 'Count mode' : 'Density mode'})
              </option>
            ))
          )}
        </select>
      </div>

      {selectedZoneId > 0 && (
        <QueryErrorResetBoundary>
          {({ reset }) => (
            <ErrorBoundary
              resetKeys={[selectedZoneId]}
              onReset={reset}
              fallbackRender={({ resetErrorBoundary }) => (
                <div
                  role="alert"
                  className="space-y-2 rounded-lg border p-3 text-sm"
                >
                  <p>Could not load sources for this zone.</p>
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
              <Suspense
                fallback={
                  <div role="status" className="space-y-2">
                    <span className="sr-only">Loading sources</span>
                    <Skeleton className="h-11 w-full" />
                    <Skeleton className="h-9 w-2/3" />
                  </div>
                }
              >
                <SourceListSection
                  zoneId={selectedZoneId}
                  selectedSourceId={selectedSourceId}
                  onSelectSource={onSelectSource}
                  defaultKind={defaultKind}
                  disabled={disabled}
                />
              </Suspense>
            </ErrorBoundary>
          )}
        </QueryErrorResetBoundary>
      )}
    </div>
  );
}
