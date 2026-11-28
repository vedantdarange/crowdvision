import { lazy, Suspense } from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import type { ZoneState } from '@contract/types';
const ZoneMap = lazy(() => import('@/features/zones/ZoneMap'));
export function PoliceMap({
  zones,
  select,
  selected = null,
}: {
  zones: ZoneState[];
  select: (id: number) => void;
  selected?: number | null;
}) {
  return (
    <div className="police-map">
      <ErrorBoundary fallback={<p>Map unavailable. Use the zone links.</p>}>
        <Suspense fallback={<p>Loading map…</p>}>
          <ZoneMap
            zones={zones.map((z) => ({
              ...z,
              zone_id: z.id,
              updated_at: z.live_updated_at,
            }))}
            select={select}
            selected={selected}
          />
        </Suspense>
      </ErrorBoundary>
    </div>
  );
}
