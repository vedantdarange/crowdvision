import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import type {
  ApiOne,
  PublicZoneState,
  PublicZoneDetail,
  RuntimeConfig,
  Advisory,
  HelpInfo,
} from '@contract/types';
import { apiClient } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';
function resource<T>(queryKey: readonly unknown[], path: string) {
  return {
    queryKey,
    queryFn: async () => (await apiClient<ApiOne<T>>(path)).data,
  };
}
export const useLiveZones = () =>
  useSuspenseQuery(resource<PublicZoneState[]>(k.zones.live, '/zones/live'));
export const usePublicZone = (id: number) =>
  useSuspenseQuery(
    resource<PublicZoneDetail>(k.zones.public(id), '/zones/' + id + '/public'),
  );
export const useAdvisories = (id?: number) =>
  useSuspenseQuery(
    resource<Advisory[]>(
      k.advisories(id),
      '/advisories' + (id ? '?zone_id=' + id : ''),
    ),
  );
export const useHelp = () =>
  useSuspenseQuery(resource<HelpInfo>(k.help, '/help-info'));
export const useConfig = (enabled = true) =>
  useQuery({
    ...resource<RuntimeConfig>(k.config, '/config'),
    staleTime: Infinity,
    enabled,
  });
