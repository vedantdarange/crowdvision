import { render as mount } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import help from '../../contract/examples/help_info.json';
import live from '../../contract/examples/zones_live.json';
import notices from '../../contract/examples/advisories.json';
import detail from '../../contract/examples/zone_public_detail.json';
import { vi } from 'vitest';
vi.mock('@/features/zones/ZoneMap', () => ({ default: () => null }));
export function render(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity } },
  });
  client.setQueryData(['help'], help);
  client.setQueryData(['zones', 'live'], live.data);
  client.setQueryData(['zones', 'public', 1], detail.data);
  for (const key of ['all', detail.data.state.zone_id])
    client.setQueryData(['advisories', key], notices.data);
  return mount(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
