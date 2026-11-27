import type { QueryClient } from '@tanstack/react-query';
import type {
  PublicZoneState,
  PublicZoneDetail,
  Advisory,
} from '@contract/types';
import { queryKeys as k } from '@/lib/queryKeys';
export function updateZone(client: QueryClient, zone: PublicZoneState) {
  client.setQueryData<PublicZoneState[]>(
    k.zones.live,
    (old) =>
      old &&
      (old.some((z) => z.zone_id === zone.zone_id)
        ? old.map((z) => (z.zone_id === zone.zone_id ? zone : z))
        : [...old, zone]),
  );
  client.setQueryData<PublicZoneDetail>(
    k.zones.public(zone.zone_id),
    (old) => old && { ...old, state: zone },
  );
}
export function updateAdvisory(
  client: QueryClient,
  id: number,
  item?: Advisory,
) {
  for (const [key] of client.getQueriesData({ queryKey: ['advisories'] })) {
    client.setQueryData<Advisory[]>(key, (old) => {
      if (!old) return old;
      const remaining = old.filter((a) => a.id !== id);
      if (
        item &&
        (key[1] === 'all' || item.zone_id === null || item.zone_id === key[1])
      )
        remaining.push(item);
      return remaining.sort((a, b) => b.created_at.localeCompare(a.created_at));
    });
  }
}
