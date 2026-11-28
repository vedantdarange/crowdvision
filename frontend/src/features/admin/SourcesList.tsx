import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';
import {
  Camera,
  Loader2,
  Pencil,
  Plus,
  PowerOff,
  Radio,
  Video,
  WifiOff,
} from 'lucide-react';
import type { SourceInfo, ZoneState } from '@contract/types';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Age } from '@/features/police/Alerts';
import { ApiRequestError } from '@/lib/apiClient';
import {
  useAdminSources,
  useAdminZones,
  useCreateAdminSource,
  useDisableAdminSource,
  useUpdateAdminSource,
} from './api';

const COVERAGE_HELPER =
  'the area your camera actually sees; smaller than the zone is fine';

const createSourceSchema = z.object({
  zone_id: z.coerce.number().int().min(1, 'Select a zone.'),
  name: z
    .string()
    .trim()
    .min(1, 'Enter a source name.')
    .max(255, 'Keep name under 255 characters.'),
  kind: z.enum(['WEBCAM', 'VIDEO_FILE']),
  coverage_area_m2: z.coerce
    .number({ error: 'Enter a valid coverage area.' })
    .min(1, 'Coverage must be at least 1 m².'),
});

type CreateSourceInputValues = z.input<typeof createSourceSchema>;
type CreateSourceValues = z.output<typeof createSourceSchema>;

const editSourceSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, 'Enter a source name.')
    .max(255, 'Keep name under 255 characters.'),
  coverage_area_m2: z.coerce
    .number({ error: 'Enter a valid coverage area.' })
    .min(1, 'Coverage must be at least 1 m².'),
  is_active: z.boolean(),
});

type EditSourceInputValues = z.input<typeof editSourceSchema>;
type EditSourceValues = z.output<typeof editSourceSchema>;

function CreateSourceForm({
  zones,
  selectedZoneId,
}: {
  zones: ZoneState[];
  selectedZoneId: number | null;
}) {
  const activeZones = useMemo(
    () => zones.filter((zone) => zone.is_active),
    [zones],
  );
  const initialZone =
    activeZones.find((z) => z.id === selectedZoneId) ?? activeZones[0];

  const createMutation = useCreateAdminSource();

  const {
    register,
    control,
    watch,
    setValue,
    setError,
    reset,
    handleSubmit,
    formState: { errors, isSubmitting, dirtyFields },
  } = useForm<CreateSourceInputValues, unknown, CreateSourceValues>({
    resolver: zodResolver(createSourceSchema),
    defaultValues: {
      zone_id: initialZone?.id ?? 0,
      name: '',
      kind: 'WEBCAM',
      coverage_area_m2: initialZone
        ? Math.round(initialZone.area_m2 * 10) / 10
        : 10,
    },
  });

  const watchedZoneId = Number(watch('zone_id'));
  const currentZone =
    activeZones.find((z) => z.id === watchedZoneId) ?? initialZone;

  useEffect(() => {
    if (!currentZone || dirtyFields.coverage_area_m2) return;
    setValue('coverage_area_m2', Math.round(currentZone.area_m2 * 10) / 10);
  }, [currentZone, dirtyFields.coverage_area_m2, setValue]);

  if (!activeZones.length) {
    return null;
  }

  async function onSubmit(values: CreateSourceValues) {
    const zone = activeZones.find((z) => z.id === values.zone_id);
    if (!zone) {
      setError('zone_id', { message: 'Choose an active zone.' });
      return;
    }
    const maxCoverage = zone.area_m2 * 2;
    if (values.coverage_area_m2 > maxCoverage) {
      setError(
        'coverage_area_m2',
        {
          message: `Coverage must be between 1 and ${maxCoverage.toFixed(1)} m² (2x ${zone.name} area).`,
        },
        { shouldFocus: true },
      );
      return;
    }

    try {
      await createMutation.mutateAsync({
        zone_id: values.zone_id,
        name: values.name.trim(),
        kind: values.kind,
        coverage_area_m2: values.coverage_area_m2,
      });
      reset({
        zone_id: zone.id,
        name: '',
        kind: values.kind,
        coverage_area_m2: Math.round(zone.area_m2 * 10) / 10,
      });
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 422) {
        const covErr = error.details?.coverage_area_m2;
        if (Array.isArray(covErr) && typeof covErr[0] === 'string') {
          setError('coverage_area_m2', { message: covErr[0] });
          return;
        }
        const nameErr = error.details?.name;
        if (Array.isArray(nameErr) && typeof nameErr[0] === 'string') {
          setError('name', { message: nameErr[0] });
          return;
        }
      }
      setError('root', {
        message:
          error instanceof Error ? error.message : 'Could not create source.',
      });
    }
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(onSubmit)(e)}
      className="glass grid gap-4"
      noValidate
    >
      <h2>Add camera source</h2>

      <div className="police-filters">
        <div className="space-y-1.5">
          <Label htmlFor="admin-src-zone">Zone</Label>
          <Controller
            name="zone_id"
            control={control}
            render={({ field }) => (
              <select
                id="admin-src-zone"
                value={String(field.value)}
                onChange={(e) => field.onChange(Number(e.target.value))}
              >
                {activeZones.map((zone) => (
                  <option key={zone.id} value={zone.id}>
                    {zone.name} ({zone.area_m2.toFixed(1)} m²)
                  </option>
                ))}
              </select>
            )}
          />
          {errors.zone_id && (
            <p role="alert" className="text-critical text-sm">
              {errors.zone_id.message}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="admin-src-name">Source name</Label>
          <Input
            id="admin-src-name"
            placeholder="E.g. Gate East Cam 2"
            aria-invalid={Boolean(errors.name)}
            {...register('name')}
          />
          {errors.name && (
            <p role="alert" className="text-critical text-sm">
              {errors.name.message}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="admin-src-kind">Kind</Label>
          <Controller
            name="kind"
            control={control}
            render={({ field }) => (
              <select
                id="admin-src-kind"
                value={field.value}
                onChange={(e) => field.onChange(e.target.value)}
              >
                <option value="WEBCAM">Webcam</option>
                <option value="VIDEO_FILE">Video file</option>
              </select>
            )}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="admin-src-coverage">Coverage area (m²)</Label>
          <Input
            id="admin-src-coverage"
            type="number"
            step="0.1"
            aria-invalid={Boolean(errors.coverage_area_m2)}
            {...register('coverage_area_m2')}
          />
          <p className="text-muted-foreground text-xs">
            {COVERAGE_HELPER}
            {currentZone
              ? ` (1 to ${(currentZone.area_m2 * 2).toFixed(1)} m²).`
              : '.'}
          </p>
          {errors.coverage_area_m2 && (
            <p role="alert" className="text-critical text-sm">
              {errors.coverage_area_m2.message}
            </p>
          )}
        </div>
      </div>

      {errors.root && (
        <p role="alert" className="text-critical text-sm font-medium">
          {errors.root.message}
        </p>
      )}

      <div>
        <Button
          type="submit"
          className="min-h-11 gap-2"
          disabled={isSubmitting || createMutation.isPending}
        >
          {isSubmitting || createMutation.isPending ? (
            <>
              <Loader2 size={16} className="animate-spin" aria-hidden />
              Adding source...
            </>
          ) : (
            <>
              <Plus size={16} aria-hidden />
              Add source
            </>
          )}
        </Button>
      </div>
    </form>
  );
}

function EditSourceDialog({
  source,
  zoneAreaM2,
  trigger,
  close,
}: {
  source: SourceInfo;
  zoneAreaM2: number;
  trigger: HTMLElement;
  close: () => void;
}) {
  const updateMutation = useUpdateAdminSource();

  const {
    register,
    control,
    setError,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<EditSourceInputValues, unknown, EditSourceValues>({
    resolver: zodResolver(editSourceSchema),
    defaultValues: {
      name: source.name,
      coverage_area_m2: source.coverage_area_m2,
      is_active: source.is_active,
    },
  });

  const maxCoverage = zoneAreaM2 * 2;

  async function onSubmit(values: EditSourceValues) {
    if (values.coverage_area_m2 > maxCoverage) {
      setError(
        'coverage_area_m2',
        {
          message: `Coverage must be between 1 and ${maxCoverage.toFixed(1)} m² (2x zone area).`,
        },
        { shouldFocus: true },
      );
      return;
    }
    try {
      await updateMutation.mutateAsync({
        id: source.id,
        name: values.name.trim(),
        coverage_area_m2: values.coverage_area_m2,
        is_active: values.is_active,
      });
      close();
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 422) {
        const covErr = error.details?.coverage_area_m2;
        if (Array.isArray(covErr) && typeof covErr[0] === 'string') {
          setError('coverage_area_m2', { message: covErr[0] });
          return;
        }
      }
      setError('root', {
        message:
          error instanceof Error ? error.message : 'Could not update source.',
      });
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !updateMutation.isPending) close();
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
        <DialogTitle>Edit source &ldquo;{source.name}&rdquo;</DialogTitle>
        <DialogDescription>
          Update source name, camera field-of-view coverage, or active state.
        </DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => void handleSubmit(onSubmit)(e)}
          noValidate
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-src-name">Name</Label>
            <Input
              id="edit-src-name"
              aria-invalid={Boolean(errors.name)}
              {...register('name')}
            />
            {errors.name && (
              <p role="alert" className="text-critical text-sm">
                {errors.name.message}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="edit-src-coverage">Coverage area (m²)</Label>
            <Input
              id="edit-src-coverage"
              type="number"
              step="0.1"
              aria-invalid={Boolean(errors.coverage_area_m2)}
              {...register('coverage_area_m2')}
            />
            <p className="text-muted-foreground text-xs">
              {COVERAGE_HELPER} (1 to {maxCoverage.toFixed(1)} m²).
            </p>
            {errors.coverage_area_m2 && (
              <p role="alert" className="text-critical text-sm">
                {errors.coverage_area_m2.message}
              </p>
            )}
          </div>

          <div className="flex items-center justify-between rounded-lg border p-3">
            <Label htmlFor="edit-src-active">Active source</Label>
            <Controller
              name="is_active"
              control={control}
              render={({ field }) => (
                <Switch
                  id="edit-src-active"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          {errors.root && (
            <p role="alert" className="text-critical text-sm">
              {errors.root.message}
            </p>
          )}

          <div className="police-actions justify-end pt-1">
            <DialogClose asChild>
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                disabled={isSubmitting || updateMutation.isPending}
              >
                Cancel
              </Button>
            </DialogClose>
            <Button
              type="submit"
              className="min-h-11"
              disabled={isSubmitting || updateMutation.isPending}
            >
              Save changes
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DisableSourceDialog({
  source,
  trigger,
  close,
}: {
  source: SourceInfo;
  trigger: HTMLElement;
  close: () => void;
}) {
  const disableMutation = useDisableAdminSource();

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !disableMutation.isPending) close();
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
        <DialogTitle>Disable &ldquo;{source.name}&rdquo;?</DialogTitle>
        <DialogDescription>
          Frames from this source will stop updating its zone until re-enabled.
        </DialogDescription>
        <div className="police-actions justify-end pt-2">
          <DialogClose asChild>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={disableMutation.isPending}
            >
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            className="min-h-11"
            disabled={disableMutation.isPending}
            onClick={() =>
              disableMutation.mutate(source.id, { onSettled: close })
            }
          >
            Confirm disable
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SourcesContent({
  filterZoneId,
  setFilterZoneId,
}: {
  filterZoneId: number | null;
  setFilterZoneId: (id: number | null) => void;
}) {
  const { data: zones } = useAdminZones();
  const { data: sources } = useAdminSources('all');

  const [editTarget, setEditTarget] = useState<{
    source: SourceInfo;
    zoneAreaM2: number;
    trigger: HTMLElement;
  } | null>(null);
  const [disableTarget, setDisableTarget] = useState<{
    source: SourceInfo;
    trigger: HTMLElement;
  } | null>(null);

  if (!zones.some((z) => z.is_active)) {
    return (
      <EmptyState
        title="Create a zone first"
        description="Camera sources belong to a monitored zone. Draw a zone before adding sources."
        action={
          <Button asChild className="min-h-11">
            <Link to="/admin/zones/new">New zone</Link>
          </Button>
        }
      />
    );
  }

  const visibleZones = zones.filter((zone) => {
    if (!zone.is_active) return false;
    if (filterZoneId !== null) return zone.id === filterZoneId;
    return true;
  });

  return (
    <div className="space-y-5">
      <CreateSourceForm zones={zones} selectedZoneId={filterZoneId} />

      <div className="police-filters">
        <label>
          Filter by zone
          <select
            value={filterZoneId !== null ? String(filterZoneId) : ''}
            onChange={(e) =>
              setFilterZoneId(e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">All active zones</option>
            {zones
              .filter((z) => z.is_active)
              .map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name}
                </option>
              ))}
          </select>
        </label>
      </div>

      {visibleZones.map((zone) => {
        const zoneSources = sources.filter((s) => s.zone_id === zone.id);
        return (
          <section
            key={zone.id}
            className="glass space-y-3"
            aria-label={`Sources in ${zone.name}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2>
                {zone.name}{' '}
                <span className="text-muted-foreground text-sm font-normal">
                  (zone area {zone.area_m2.toFixed(1)} m²)
                </span>
              </h2>
              <span className="text-muted-foreground text-xs">
                {zoneSources.length}{' '}
                {zoneSources.length === 1 ? 'source' : 'sources'}
              </span>
            </div>

            {!zoneSources.length ? (
              <p className="text-muted-foreground text-sm">
                No camera sources configured for this zone yet.
              </p>
            ) : (
              <div className="queue-table">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Kind</TableHead>
                      <TableHead>Coverage area</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {zoneSources.map((src) => (
                      <TableRow key={src.id}>
                        <TableCell className="font-semibold">
                          {src.name}
                        </TableCell>
                        <TableCell>
                          <span className="inline-flex items-center gap-1.5">
                            {src.kind === 'WEBCAM' ? (
                              <Camera size={14} aria-hidden />
                            ) : (
                              <Video size={14} aria-hidden />
                            )}
                            <span>
                              {src.kind === 'WEBCAM' ? 'Webcam' : 'Video file'}
                            </span>
                          </span>
                        </TableCell>
                        <TableCell>
                          {src.coverage_area_m2.toFixed(1)} m²
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap items-center gap-2">
                            {src.status === 'ONLINE' ? (
                              <span className="bg-safe-bg text-safe border-safe/30 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold">
                                <Radio size={12} aria-hidden />
                                Online
                              </span>
                            ) : (
                              <span className="bg-muted text-muted-foreground inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold">
                                <WifiOff size={12} aria-hidden />
                                Offline
                              </span>
                            )}
                            {!src.is_active && (
                              <span className="rounded border px-1.5 py-0.5 text-xs">
                                Disabled
                              </span>
                            )}
                            {src.last_frame_at && (
                              <Age ts={src.last_frame_at} />
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="police-actions justify-end">
                            <Button
                              type="button"
                              variant="outline"
                              className="min-h-11 gap-1.5"
                              onClick={(event) =>
                                setEditTarget({
                                  source: src,
                                  zoneAreaM2: zone.area_m2,
                                  trigger: event.currentTarget,
                                })
                              }
                            >
                              <Pencil size={15} aria-hidden />
                              Edit
                            </Button>
                            {src.is_active && (
                              <Button
                                type="button"
                                variant="outline"
                                className="min-h-11 gap-1.5"
                                onClick={(event) =>
                                  setDisableTarget({
                                    source: src,
                                    trigger: event.currentTarget,
                                  })
                                }
                              >
                                <PowerOff size={15} aria-hidden />
                                Disable
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </section>
        );
      })}

      {editTarget && (
        <EditSourceDialog
          key={editTarget.source.id}
          source={editTarget.source}
          zoneAreaM2={editTarget.zoneAreaM2}
          trigger={editTarget.trigger}
          close={() => setEditTarget(null)}
        />
      )}

      {disableTarget && (
        <DisableSourceDialog
          key={disableTarget.source.id}
          source={disableTarget.source}
          trigger={disableTarget.trigger}
          close={() => setDisableTarget(null)}
        />
      )}
    </div>
  );
}

export function AdminSourcesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawZone = searchParams.get('zone_id');
  const parsedZone = rawZone ? Number(rawZone) : null;
  const filterZoneId =
    parsedZone !== null && Number.isFinite(parsedZone) && parsedZone > 0
      ? parsedZone
      : null;

  function handleZoneFilterChange(id: number | null) {
    if (id === null) {
      setSearchParams({});
    } else {
      setSearchParams({ zone_id: String(id) });
    }
  }

  return (
    <section className="police-page">
      <header>
        <div>
          <h1>Sources</h1>
          <p className="text-muted-foreground text-sm">
            Configure cameras and video sources per zone with calibrated
            field-of-view coverage areas.
          </p>
        </div>
      </header>

      <SuspenseBoundary>
        <SourcesContent
          filterZoneId={filterZoneId}
          setFilterZoneId={handleZoneFilterChange}
        />
      </SuspenseBoundary>
    </section>
  );
}
