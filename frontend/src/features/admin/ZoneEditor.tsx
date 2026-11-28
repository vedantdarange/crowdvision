import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';
import { ArrowLeft, Loader2, Save } from 'lucide-react';
import { toast } from 'sonner';
import type { PolygonGeometry, ZoneState } from '@contract/types';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { ApiRequestError } from '@/lib/apiClient';
import {
  computePolygonAreaM2,
  normalizePolygonGeometry,
  validateZonePolygon,
} from '@/lib/geo';
import {
  useAdminZone,
  useAdminZones,
  useCreateZone,
  useUpdateZone,
} from './api';
import { ZoneEditorMap } from './ZoneEditorMap';

const optionalCountField = z.preprocess(
  (value) => {
    if (value === '' || value === null || value === undefined) return null;
    const num = Number(value);
    return Number.isNaN(num) ? value : num;
  },
  z
    .number({ error: 'Enter a whole number >= 1.' })
    .int('Use a whole number of people.')
    .min(1, 'Count threshold must be at least 1.')
    .nullable(),
);

const zoneSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, 'Enter a zone name.')
      .max(255, 'Keep zone name within 255 characters.'),
    description: z
      .string()
      .max(1000, 'Keep description under 1000 characters.'),
    mode: z.enum(['DENSITY', 'COUNT']),
    warning_density: z.coerce
      .number({ error: 'Enter a positive density.' })
      .positive('Warning density must be greater than 0.'),
    critical_density: z.coerce
      .number({ error: 'Enter a positive density.' })
      .positive('Critical density must be greater than 0.'),
    warning_count: optionalCountField,
    critical_count: optionalCountField,
    is_active: z.boolean(),
  })
  .superRefine((data, ctx) => {
    if (data.warning_density >= data.critical_density) {
      ctx.addIssue({
        code: 'custom',
        path: ['warning_density'],
        message: 'Warning density must be lower than critical density.',
      });
    }
    if (data.mode === 'COUNT') {
      if (data.warning_count === null) {
        ctx.addIssue({
          code: 'custom',
          path: ['warning_count'],
          message: 'Warning count is required in Count mode.',
        });
      }
      if (data.critical_count === null) {
        ctx.addIssue({
          code: 'custom',
          path: ['critical_count'],
          message: 'Critical count is required in Count mode.',
        });
      }
    }
    if (
      data.warning_count !== null &&
      data.critical_count !== null &&
      data.warning_count >= data.critical_count
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['warning_count'],
        message: 'Warning count must be lower than critical count.',
      });
    }
  });

type ZoneFormInput = z.input<typeof zoneSchema>;
type ZoneFormValues = z.output<typeof zoneSchema>;

function ZoneEditorForm({
  zones,
  existing,
}: {
  zones: ZoneState[];
  existing?: ZoneState;
}) {
  const isEdit = Boolean(existing);
  const navigate = useNavigate();
  const createMutation = useCreateZone();
  const updateMutation = useUpdateZone(existing?.id ?? 0);

  const [polygon, setPolygon] = useState<PolygonGeometry | null>(
    existing?.geometry ?? null,
  );
  const [polygonError, setPolygonError] = useState<string | null>(null);
  const [savedAreaM2, setSavedAreaM2] = useState<number | null>(
    existing?.area_m2 ?? null,
  );

  useEffect(() => {
    setPolygon(existing?.geometry ?? null);
    setSavedAreaM2(existing?.area_m2 ?? null);
    setPolygonError(null);
  }, [existing?.id, existing?.geometry, existing?.area_m2]);

  const {
    register,
    control,
    watch,
    setError,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ZoneFormInput, unknown, ZoneFormValues>({
    resolver: zodResolver(zoneSchema),
    defaultValues: {
      name: existing?.name ?? '',
      description: existing?.description ?? '',
      mode: existing?.mode ?? 'DENSITY',
      warning_density: existing?.warning_density ?? 3.0,
      critical_density: existing?.critical_density ?? 4.0,
      warning_count: existing?.warning_count ?? null,
      critical_count: existing?.critical_count ?? null,
      is_active: existing?.is_active ?? true,
    },
  });

  const selectedMode = watch('mode');
  const polygonValidation = polygon ? validateZonePolygon(polygon) : null;
  const previewAreaM2 =
    polygon && !polygonValidation ? computePolygonAreaM2(polygon) : null;

  function handlePolygonChange(next: PolygonGeometry | null) {
    if (!next) {
      setPolygon(null);
      setPolygonError(null);
      return;
    }
    const normalized = normalizePolygonGeometry(next);
    setPolygon(normalized);
    setPolygonError(validateZonePolygon(normalized));
  }

  async function onSubmit(values: ZoneFormValues) {
    const geomProblem = validateZonePolygon(polygon);
    if (geomProblem || !polygon) {
      setPolygonError(geomProblem ?? 'Draw a zone polygon on the map.');
      return;
    }
    setPolygonError(null);

    const areaHint = Math.round(computePolygonAreaM2(polygon) * 100) / 100;
    const basePayload = {
      name: values.name.trim(),
      description: values.description.trim(),
      geometry: polygon,
      area_m2: areaHint,
      mode: values.mode,
      warning_density: values.warning_density,
      critical_density: values.critical_density,
      warning_count: values.mode === 'COUNT' ? values.warning_count : null,
      critical_count: values.mode === 'COUNT' ? values.critical_count : null,
    };

    try {
      const saved = isEdit
        ? await updateMutation.mutateAsync({
            ...basePayload,
            is_active: values.is_active,
          })
        : await createMutation.mutateAsync(basePayload);

      setSavedAreaM2(saved.area_m2);
      toast.success(`Saved "${saved.name}" (${saved.area_m2.toFixed(1)} m²).`);
      void navigate('/admin/zones');
    } catch (error) {
      if (error instanceof ApiRequestError) {
        if (error.status === 409) {
          const msg = error.message.toLowerCase().includes('alert')
            ? 'Resolve its alert first.'
            : error.message;
          setError('root', { message: msg });
          return;
        }
        if (error.status === 422 && error.details) {
          let mapped = false;
          for (const field of [
            'name',
            'description',
            'mode',
            'warning_density',
            'critical_density',
            'warning_count',
            'critical_count',
          ] as const) {
            const detail = error.details[field];
            if (Array.isArray(detail) && typeof detail[0] === 'string') {
              setError(field, { message: detail[0] }, { shouldFocus: !mapped });
              mapped = true;
            }
          }
          const geomDetail =
            error.details.geometry ?? error.details.area_m2 ?? null;
          if (Array.isArray(geomDetail) && typeof geomDetail[0] === 'string') {
            setPolygonError(geomDetail[0]);
            mapped = true;
          }
          if (mapped) return;
        }
        setError('root', { message: error.message });
        return;
      }
      setError('root', { message: 'Could not save zone.' });
    }
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(onSubmit)(e)}
      className="space-y-5"
      noValidate
    >
      <div className="glass space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2>Zone polygon</h2>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {previewAreaM2 !== null ? (
              <span className="rounded-md border px-2.5 py-1 font-semibold">
                Area: {previewAreaM2.toFixed(1)} m² (preview — server
                recomputes)
              </span>
            ) : (
              <span className="text-muted-foreground">
                Draw 1 closed polygon using the top-right tool
              </span>
            )}
            {savedAreaM2 !== null && (
              <span className="text-muted-foreground text-xs">
                Saved area: {savedAreaM2.toFixed(1)} m²
              </span>
            )}
          </div>
        </div>

        <ZoneEditorMap
          zones={zones}
          editingZoneId={existing?.id}
          initialPolygon={existing?.geometry ?? null}
          onPolygonChange={handlePolygonChange}
        />

        {polygonError && (
          <p role="alert" className="text-critical text-sm font-medium">
            {polygonError}
          </p>
        )}
      </div>

      <div className="glass grid gap-4">
        <h2>Configuration</h2>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="zone-name">Name</Label>
            <Input
              id="zone-name"
              aria-invalid={Boolean(errors.name)}
              placeholder="E.g. Main Gate"
              {...register('name')}
            />
            {errors.name && (
              <p role="alert" className="text-critical text-sm">
                {errors.name.message}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="zone-mode">Monitoring mode</Label>
            <Controller
              name="mode"
              control={control}
              render={({ field }) => (
                <select
                  id="zone-mode"
                  className="border-input bg-card h-11 w-full rounded-md border px-3 text-sm"
                  value={field.value}
                  onChange={(e) => field.onChange(e.target.value)}
                >
                  <option value="DENSITY">Density (people / m²)</option>
                  <option value="COUNT">Count (total people)</option>
                </select>
              )}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="zone-description">Description</Label>
          <Textarea
            id="zone-description"
            rows={2}
            placeholder="Location landmarks, gates, or barricades"
            {...register('description')}
          />
          {errors.description && (
            <p role="alert" className="text-critical text-sm">
              {errors.description.message}
            </p>
          )}
        </div>

        <p className="text-muted-foreground rounded-lg border p-3 text-xs">
          Fruin crowd-safety thresholds: Warning (default{' '}
          <strong>3.0 people/m²</strong>) indicates slowing crowd flow and
          frequent shoulder contact; Critical (default{' '}
          <strong>4.0 people/m²</strong>) signals severe congestion and crush
          risk requiring immediate steward action. Configure camera
          field-of-view coverage separately in <code>/admin/sources</code>, not
          by shrinking the zone.
        </p>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="zone-warn-density">
              Warning density (people/m²)
            </Label>
            <Input
              id="zone-warn-density"
              type="number"
              step="0.1"
              aria-invalid={Boolean(errors.warning_density)}
              {...register('warning_density')}
            />
            {errors.warning_density && (
              <p role="alert" className="text-critical text-sm">
                {errors.warning_density.message}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="zone-crit-density">
              Critical density (people/m²)
            </Label>
            <Input
              id="zone-crit-density"
              type="number"
              step="0.1"
              aria-invalid={Boolean(errors.critical_density)}
              {...register('critical_density')}
            />
            {errors.critical_density && (
              <p role="alert" className="text-critical text-sm">
                {errors.critical_density.message}
              </p>
            )}
          </div>
        </div>

        {selectedMode === 'COUNT' && (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="zone-warn-count">Warning count (people)</Label>
              <Input
                id="zone-warn-count"
                type="number"
                step="1"
                placeholder="8"
                aria-invalid={Boolean(errors.warning_count)}
                {...register('warning_count')}
              />
              {errors.warning_count && (
                <p role="alert" className="text-critical text-sm">
                  {errors.warning_count.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="zone-crit-count">Critical count (people)</Label>
              <Input
                id="zone-crit-count"
                type="number"
                step="1"
                placeholder="10"
                aria-invalid={Boolean(errors.critical_count)}
                {...register('critical_count')}
              />
              {errors.critical_count && (
                <p role="alert" className="text-critical text-sm">
                  {errors.critical_count.message}
                </p>
              )}
            </div>
          </div>
        )}

        {isEdit && (
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <Label htmlFor="zone-active">Active zone</Label>
              <p className="text-muted-foreground text-xs">
                Inactive zones are hidden from live public status.
              </p>
            </div>
            <Controller
              name="is_active"
              control={control}
              render={({ field }) => (
                <Switch
                  id="zone-active"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>
        )}

        {errors.root && (
          <p role="alert" className="text-critical text-sm font-medium">
            {errors.root.message}
          </p>
        )}

        <div className="police-actions">
          <Button
            type="submit"
            className="min-h-11 gap-2"
            disabled={
              isSubmitting ||
              createMutation.isPending ||
              updateMutation.isPending
            }
          >
            {isSubmitting ||
            createMutation.isPending ||
            updateMutation.isPending ? (
              <>
                <Loader2 size={16} className="animate-spin" aria-hidden />
                Saving zone...
              </>
            ) : (
              <>
                <Save size={16} aria-hidden />
                {isEdit ? 'Save changes' : 'Create zone'}
              </>
            )}
          </Button>
          <Button asChild variant="outline" className="min-h-11">
            <Link to="/admin/zones">Cancel</Link>
          </Button>
        </div>
      </div>
    </form>
  );
}

function NewZoneBody() {
  const { data: zones } = useAdminZones();
  return <ZoneEditorForm zones={zones} />;
}

function EditZoneBody({ zoneId }: { zoneId: number }) {
  const { data: zones } = useAdminZones();
  const { data: existing } = useAdminZone(zoneId);
  return <ZoneEditorForm zones={zones} existing={existing} />;
}

export function ZoneEditorPage() {
  const { id } = useParams();
  const numericId = id ? Number(id) : null;
  const isEdit = numericId !== null && Number.isFinite(numericId);

  return (
    <section className="police-page">
      <header>
        <div>
          <Link
            to="/admin/zones"
            className="inline-flex min-h-11 items-center gap-1.5 text-sm"
          >
            <ArrowLeft size={16} aria-hidden />
            Back to zones
          </Link>
          <h1>{isEdit ? 'Edit zone' : 'New zone'}</h1>
        </div>
      </header>

      <SuspenseBoundary>
        {isEdit ? <EditZoneBody zoneId={numericId} /> : <NewZoneBody />}
      </SuspenseBoundary>
    </section>
  );
}
