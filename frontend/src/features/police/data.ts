import {
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery,
  type QueryClient,
} from '@tanstack/react-query';
import { create } from 'zustand';
import type {
  Alert,
  AlertDetail,
  ApiList,
  ApiOne,
  HistoryPoint,
  Level,
  Settings,
  SourceInfo,
  SourceKind,
  SourceStatusPayload,
  ZoneState,
} from '@contract/types';
import { apiClient } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';

export type Filters = {
  active?: boolean;
  status?: string;
  level?: string;
  zone_id?: string;
  from?: string;
  to?: string;
  page: number;
  limit: number;
};
export const activeFeed: Filters = { active: true, page: 1, limit: 8 };
export function useAlerts(filters: Filters) {
  const params = new URLSearchParams({ sort: '-created_at' });
  for (const [key, value] of Object.entries(filters))
    if (value) params.set(key, String(value));
  return useSuspenseQuery({
    queryKey: k.alerts(filters),
    queryFn: ({ signal }) =>
      apiClient<ApiList<Alert>>('/alerts?' + params, { signal }),
  });
}
export function useZones() {
  return useSuspenseQuery({
    queryKey: k.zones.list,
    queryFn: async ({ signal }) =>
      (await apiClient<ApiOne<ZoneState[]>>('/zones', { signal })).data,
  });
}
export function useZone(id: number) {
  return useSuspenseQuery({
    queryKey: k.zones.detail(id),
    queryFn: async ({ signal }) =>
      (await apiClient<ApiOne<ZoneState>>('/zones/' + id, { signal })).data,
  });
}

export type HistoryRange = '30m' | '2h' | '24h';

export const HISTORY_RANGES: Record<
  HistoryRange,
  { label: string; durationMs: number; bucketS: 10 | 60 | 300 }
> = {
  '30m': { label: '30 min', durationMs: 30 * 60 * 1000, bucketS: 10 },
  '2h': { label: '2 h', durationMs: 2 * 60 * 60 * 1000, bucketS: 60 },
  '24h': { label: '24 h', durationMs: 24 * 60 * 60 * 1000, bucketS: 300 },
};

export function useZoneHistory(zoneId: number, range: HistoryRange) {
  const { durationMs, bucketS } = HISTORY_RANGES[range];
  return useSuspenseQuery({
    queryKey: k.zones.history(zoneId, range),
    queryFn: async ({ signal }) => {
      const to = new Date();
      const from = new Date(to.getTime() - durationMs);
      const params = new URLSearchParams({
        from: from.toISOString(),
        to: to.toISOString(),
        bucket_s: String(bucketS),
      });
      return (
        await apiClient<ApiOne<HistoryPoint[]>>(
          `/zones/${zoneId}/history?${params}`,
          { signal },
        )
      ).data;
    },
  });
}

export function useSources(zoneId?: number) {
  return useSuspenseQuery({
    queryKey: k.sources(zoneId ?? 'all'),
    queryFn: async ({ signal }) => {
      const query = zoneId ? `?zone_id=${zoneId}` : '';
      return (
        await apiClient<ApiOne<SourceInfo[]>>('/sources' + query, { signal })
      ).data;
    },
  });
}

export interface CreateSourceInput {
  zone_id: number;
  name: string;
  kind: SourceKind;
}

export function useCreateSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateSourceInput) => {
      const payload: CreateSourceInput = {
        zone_id: input.zone_id,
        name: input.name,
        kind: input.kind,
      };
      return (
        await apiClient<ApiOne<SourceInfo>>('/sources', {
          method: 'POST',
          body: payload,
        })
      ).data;
    },
    onSuccess: (created) => {
      client.setQueryData<SourceInfo[]>(k.sources(created.zone_id), (old) =>
        old ? [...old, created] : [created],
      );
      client.setQueryData<SourceInfo[]>(k.sources('all'), (old) =>
        old ? [...old, created] : old,
      );
      client.setQueryData<ZoneState[]>(k.zones.list, (old) =>
        old?.map((z) =>
          z.id === created.zone_id
            ? { ...z, sources: [...z.sources, created] }
            : z,
        ),
      );
      client.setQueryData<ZoneState>(
        k.zones.detail(created.zone_id),
        (old) => old && { ...old, sources: [...old.sources, created] },
      );
      void client.invalidateQueries({ queryKey: ['sources'] });
    },
  });
}

export function useAlert(id: number) {
  return useSuspenseQuery({
    queryKey: k.alertDetail(id),
    queryFn: async ({ signal }) =>
      (await apiClient<ApiOne<AlertDetail>>('/alerts/' + id, { signal })).data,
  });
}
export function useDelay(enabled: boolean) {
  return useQuery({
    queryKey: k.settings,
    enabled,
    queryFn: async () => (await apiClient<ApiOne<Settings>>('/settings')).data,
  });
}
export type SeriesPoint = {
  ts: string;
  count: number | null;
  density: number | null;
  level: Level;
};
export const useSeries = create<{ zones: Record<number, SeriesPoint[]> }>(
  () => ({
    zones: {},
  }),
);
export function updatePoliceZone(client: QueryClient, zone: ZoneState) {
  // A socket can arrive before the initial snapshot. Keep this partial list
  // stale until GET /zones supplies the other zones.
  const hasSnapshot = !!client.getQueryState(k.zones.list)?.dataUpdatedAt;
  client.setQueryData<ZoneState[]>(
    k.zones.list,
    (old = []) =>
      old.some((z) => z.id === zone.id)
        ? old.map((z) => (z.id === zone.id ? zone : z))
        : [...old, zone],
    hasSnapshot ? undefined : { updatedAt: 0 },
  );
  client.setQueryData(k.zones.detail(zone.id), zone);
  const ts = zone.live_updated_at;
  if (ts)
    useSeries.setState(({ zones }) => ({
      zones: {
        ...zones,
        [zone.id]: [
          ...(zones[zone.id] ?? []).filter((p) => p.ts !== ts),
          { ts, count: zone.count, density: zone.density, level: zone.level },
        ].slice(-300),
      },
    }));
}
export function updateSource(client: QueryClient, event: SourceStatusPayload) {
  const update = (zone: ZoneState) =>
    zone.id !== event.zone_id
      ? zone
      : {
          ...zone,
          sources: zone.sources.map((s) =>
            s.id !== event.source_id
              ? s
              : {
                  ...s,
                  status: event.status,
                  last_frame_at: event.last_frame_at,
                },
          ),
        };
  client.setQueryData<ZoneState[]>(k.zones.list, (old) => old?.map(update), {
    updatedAt: client.getQueryState(k.zones.list)?.dataUpdatedAt,
  });
  client.setQueryData<ZoneState>(
    k.zones.detail(event.zone_id),
    (old) => old && update(old),
  );
  const patchSources = (old: SourceInfo[] | undefined) =>
    old?.map((s) =>
      s.id === event.source_id
        ? { ...s, status: event.status, last_frame_at: event.last_frame_at }
        : s,
    );
  client.setQueryData<SourceInfo[]>(k.sources(event.zone_id), patchSources);
  client.setQueryData<SourceInfo[]>(k.sources('all'), patchSources);
}
function matches(a: Alert, f: Filters) {
  return (
    (!f.active || !['RESOLVED', 'AUTO_CLEARED'].includes(a.status)) &&
    (!f.status || f.status === a.status) &&
    (!f.level || f.level === a.level) &&
    (!f.zone_id || Number(f.zone_id) === a.zone_id) &&
    (!f.from || Date.parse(a.created_at) >= Date.parse(f.from)) &&
    (!f.to || Date.parse(a.created_at) <= Date.parse(f.to))
  );
}
export function updateAlert(client: QueryClient, a: Alert, refresh = true) {
  client.setQueriesData<Alert[]>(
    { queryKey: ['alerts', 'banner'], exact: true },
    (old = []) => {
      const rows = old.filter((row) => row.id !== a.id);
      if (a.status === 'NEW') rows.push(a);
      return rows;
    },
  );
  const detailKey = k.alertDetail(a.id);
  const previous = client.getQueryData<AlertDetail>(detailKey);
  for (const [key, page] of client.getQueriesData<ApiList<Alert>>({
    queryKey: ['alerts'],
    predicate: (q) => typeof q.queryKey[1] === 'object',
  })) {
    if (!page) continue;
    const f = key[1] as Filters;
    const had = page.data.some((row) => row.id === a.id);
    const eligible = matches(a, f);
    client.setQueriesData<ApiList<Alert>>(
      { queryKey: key, exact: true },
      (old) => {
        if (!old) return old;
        const rows = old.data.filter((row) => row.id !== a.id);
        if (eligible && (had || f.page === 1)) rows.push(a);
        rows.sort(
          (x, y) =>
            Date.parse(y.created_at) - Date.parse(x.created_at) || y.id - x.id,
        );
        const knownBefore = previous ? matches(previous, f) : had;
        const delta = Number(eligible) - Number(knownBefore);
        const total = Math.max(rows.length, old.pagination.total + delta);
        return {
          data: rows.slice(0, f.limit),
          pagination: {
            ...old.pagination,
            total,
            total_pages: Math.ceil(total / f.limit),
          },
        };
      },
    );
  }
  client.setQueryData<AlertDetail>(detailKey, (old) => ({
    ...old,
    ...a,
    events: old?.events ?? [],
  }));
  if (refresh) {
    // Socket payloads omit history and cannot fill gaps in a paginated result.
    void client.invalidateQueries({
      queryKey: ['alerts'],
      predicate: (q) =>
        typeof q.queryKey[1] === 'object' ||
        q.queryKey[1] === 'banner' ||
        q.queryKey[2] === a.id,
    });
  }
}
