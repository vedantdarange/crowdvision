import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
  type QueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import type {
  ApiOne,
  MetricMode,
  PolygonGeometry,
  SourceInfo,
  SourceKind,
  ZoneState,
} from '@contract/types';
import { apiClient, ApiRequestError } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';

const ADMIN_ZONES_KEY = ['zones', 'list', 'all'] as const;

export interface ZonePayload {
  name: string;
  description: string;
  geometry: PolygonGeometry;
  area_m2: number;
  mode: MetricMode;
  warning_density: number;
  critical_density: number;
  warning_count: number | null;
  critical_count: number | null;
}

export interface ZonePatchPayload extends ZonePayload {
  is_active: boolean;
}

export interface AdminCreateSourceInput {
  zone_id: number;
  name: string;
  kind: SourceKind;
  coverage_area_m2: number;
}

export interface AdminUpdateSourceInput {
  id: number;
  name?: string;
  coverage_area_m2?: number;
  is_active?: boolean;
}

function invalidateZoneCaches(client: QueryClient, zoneId?: number) {
  void client.invalidateQueries({ queryKey: ['zones'] });
  void client.invalidateQueries({ queryKey: ['sources'] });
  if (zoneId !== undefined) {
    void client.invalidateQueries({ queryKey: k.zones.detail(zoneId) });
    void client.invalidateQueries({ queryKey: k.zones.public(zoneId) });
  }
}

export function useAdminZones() {
  return useSuspenseQuery({
    queryKey: ADMIN_ZONES_KEY,
    queryFn: async ({ signal }) =>
      (
        await apiClient<ApiOne<ZoneState[]>>('/zones?include_inactive=true', {
          signal,
        })
      ).data,
  });
}

export function useAdminZone(id: number) {
  return useSuspenseQuery({
    queryKey: k.zones.detail(id),
    queryFn: async ({ signal }) =>
      (await apiClient<ApiOne<ZoneState>>(`/zones/${id}`, { signal })).data,
  });
}

export function useCreateZone() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ZonePayload) =>
      (
        await apiClient<ApiOne<ZoneState>>('/zones', {
          method: 'POST',
          body: payload,
        })
      ).data,
    onSuccess: (created) => {
      client.setQueryData(k.zones.detail(created.id), created);
      invalidateZoneCaches(client, created.id);
    },
  });
}

export function useUpdateZone(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ZonePatchPayload) =>
      (
        await apiClient<ApiOne<ZoneState>>(`/zones/${id}`, {
          method: 'PATCH',
          body: payload,
        })
      ).data,
    onSuccess: (updated) => {
      client.setQueryData(k.zones.detail(updated.id), updated);
      invalidateZoneCaches(client, updated.id);
    },
  });
}

export function useDeactivateZone() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (zoneId: number) => {
      await apiClient<void>(`/zones/${zoneId}`, { method: 'DELETE' });
      return zoneId;
    },
    onSuccess: (zoneId) => {
      invalidateZoneCaches(client, zoneId);
      toast.success('Zone deactivated.');
    },
    onError: (error) => {
      if (error instanceof ApiRequestError && error.status === 409) {
        toast.error('Resolve its alert first.');
        return;
      }
      toast.error(
        error instanceof Error ? error.message : 'Could not deactivate zone.',
      );
    },
  });
}

export function useAdminSources(zoneId: number | 'all' = 'all') {
  return useSuspenseQuery({
    queryKey: k.sources(zoneId),
    queryFn: async ({ signal }) => {
      const qs = zoneId === 'all' ? '' : `?zone_id=${zoneId}`;
      return (
        await apiClient<ApiOne<SourceInfo[]>>('/sources' + qs, { signal })
      ).data;
    },
  });
}

export function useCreateAdminSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: AdminCreateSourceInput) =>
      (
        await apiClient<ApiOne<SourceInfo>>('/sources', {
          method: 'POST',
          body: input,
        })
      ).data,
    onSuccess: (created) => {
      invalidateZoneCaches(client, created.zone_id);
      toast.success(`Source "${created.name}" added.`);
    },
  });
}

export function useUpdateAdminSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: AdminUpdateSourceInput) =>
      (
        await apiClient<ApiOne<SourceInfo>>(`/sources/${id}`, {
          method: 'PATCH',
          body,
        })
      ).data,
    onSuccess: (updated) => {
      invalidateZoneCaches(client, updated.zone_id);
      toast.success(`Source "${updated.name}" updated.`);
    },
  });
}

export function useDisableAdminSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient<void>(`/sources/${id}`, { method: 'DELETE' });
      return id;
    },
    onSuccess: () => {
      invalidateZoneCaches(client);
      toast.success('Source disabled.');
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : 'Could not disable source.',
      );
    },
  });
}
