import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';
import { Loader2, Megaphone } from 'lucide-react';
import type { ZoneState } from '@contract/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ApiRequestError } from '@/lib/apiClient';
import { useCreateAdvisory } from './api';

const advisorySchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, 'Enter an advisory title.')
    .max(255, 'Keep title within 255 characters.'),
  body: z
    .string()
    .trim()
    .min(1, 'Enter the advisory message.')
    .max(4000, 'Keep message within 4000 characters.'),
  severity: z.enum(['INFO', 'WARNING', 'URGENT']),
  zone_id: z.string(),
  expires_at: z.string().refine((value) => {
    if (!value.trim()) return true;
    const ms = Date.parse(value);
    return Number.isFinite(ms) && ms > Date.now();
  }, 'Expiry time must be in the future.'),
});

type AdvisoryFormValues = z.infer<typeof advisorySchema>;

export function AdvisoryForm({ zones }: { zones: ZoneState[] }) {
  const createMutation = useCreateAdvisory();

  const {
    register,
    control,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AdvisoryFormValues>({
    resolver: zodResolver(advisorySchema),
    defaultValues: {
      title: '',
      body: '',
      severity: 'INFO',
      zone_id: '',
      expires_at: '',
    },
  });

  async function onSubmit(values: AdvisoryFormValues) {
    try {
      const zoneId = values.zone_id ? Number(values.zone_id) : null;
      const expiresAt = values.expires_at.trim()
        ? new Date(values.expires_at).toISOString()
        : null;

      await createMutation.mutateAsync({
        title: values.title.trim(),
        body: values.body.trim(),
        severity: values.severity,
        zone_id: zoneId,
        expires_at: expiresAt,
      });

      reset({
        title: '',
        body: '',
        severity: 'INFO',
        zone_id: '',
        expires_at: '',
      });
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 422) {
        let mapped = false;
        for (const field of [
          'title',
          'body',
          'severity',
          'zone_id',
          'expires_at',
        ] as const) {
          const detail = error.details?.[field];
          if (Array.isArray(detail) && typeof detail[0] === 'string') {
            setError(field, { message: detail[0] }, { shouldFocus: !mapped });
            mapped = true;
          }
        }
        if (mapped) return;
      }
      setError('root', {
        message:
          error instanceof Error
            ? error.message
            : 'Could not publish advisory.',
      });
    }
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(onSubmit)(e)}
      className="glass grid gap-4"
      noValidate
    >
      <h2>Publish new advisory</h2>

      <div className="space-y-1.5">
        <Label htmlFor="adv-title">Title</Label>
        <Input
          id="adv-title"
          maxLength={255}
          aria-invalid={Boolean(errors.title)}
          placeholder="E.g. Use East Gate exit lane"
          {...register('title')}
        />
        {errors.title && (
          <p role="alert" className="text-critical text-sm">
            {errors.title.message}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="adv-body">Message</Label>
        <Textarea
          id="adv-body"
          rows={4}
          maxLength={4000}
          aria-invalid={Boolean(errors.body)}
          placeholder="Clear instructions for visitors on site."
          {...register('body')}
        />
        {errors.body && (
          <p role="alert" className="text-critical text-sm">
            {errors.body.message}
          </p>
        )}
      </div>

      <div className="police-filters">
        <div className="space-y-1.5">
          <Label htmlFor="adv-severity">Severity</Label>
          <Controller
            name="severity"
            control={control}
            render={({ field }) => (
              <select
                id="adv-severity"
                value={field.value}
                onChange={(e) => field.onChange(e.target.value)}
              >
                <option value="INFO">Info</option>
                <option value="WARNING">Warning</option>
                <option value="URGENT">Urgent</option>
              </select>
            )}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="adv-zone">Scope</Label>
          <Controller
            name="zone_id"
            control={control}
            render={({ field }) => (
              <select
                id="adv-zone"
                value={field.value}
                onChange={(e) => field.onChange(e.target.value)}
              >
                <option value="">All zones (global)</option>
                {zones
                  .filter((z) => z.is_active)
                  .map((z) => (
                    <option key={z.id} value={String(z.id)}>
                      {z.name}
                    </option>
                  ))}
              </select>
            )}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="adv-expires">Optional expiry (local time)</Label>
          <Input
            id="adv-expires"
            type="datetime-local"
            aria-invalid={Boolean(errors.expires_at)}
            {...register('expires_at')}
          />
          {errors.expires_at && (
            <p role="alert" className="text-critical text-sm">
              {errors.expires_at.message}
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
              Publishing...
            </>
          ) : (
            <>
              <Megaphone size={16} aria-hidden />
              Broadcast advisory
            </>
          )}
        </Button>
      </div>
    </form>
  );
}
