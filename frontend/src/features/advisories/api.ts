import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Advisory, AdvisorySeverity, ApiOne } from '@contract/types';
import { apiClient, ApiRequestError } from '@/lib/apiClient';
import { updateAdvisory } from '@/features/realtime/cache';

export { useAdvisories } from '@/features/zones/api';

export interface CreateAdvisoryInput {
  title: string;
  body: string;
  severity: AdvisorySeverity;
  zone_id?: number | null;
  expires_at?: string | null;
}

export function useCreateAdvisory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateAdvisoryInput) =>
      (
        await apiClient<ApiOne<Advisory>>('/advisories', {
          method: 'POST',
          body: {
            title: input.title,
            body: input.body,
            severity: input.severity,
            ...(input.zone_id != null ? { zone_id: input.zone_id } : {}),
            ...(input.expires_at ? { expires_at: input.expires_at } : {}),
          },
        })
      ).data,
    onSuccess: (created) => {
      updateAdvisory(client, created.id, created);
      void client.invalidateQueries({ queryKey: ['advisories'] });
      toast.success('Advisory broadcast.');
    },
  });
}

export function useRetractAdvisory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient<void>(`/advisories/${id}`, { method: 'DELETE' });
      return id;
    },
    onSuccess: (id) => {
      updateAdvisory(client, id);
      void client.invalidateQueries({ queryKey: ['advisories'] });
      toast.success('Advisory retracted.');
    },
    onError: (error) => {
      toast.error(
        error instanceof ApiRequestError
          ? error.message
          : 'Could not retract advisory.',
      );
    },
  });
}
