import { expect, it, vi } from 'vitest';
import { screen, within, act, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { axe } from 'vitest-axe';
import { routes } from '@/app/router';
import { render } from './renderPublic';
import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';
import { RealtimeProvider } from '@/features/realtime/RealtimeProvider';
import { updateZone, updateAdvisory } from '@/features/realtime/cache';
import live from '../../contract/examples/zones_live.json';
import notices from '../../contract/examples/advisories.json';
import type { PublicZoneState, Advisory } from '@contract/types';
import { EventEmitter } from 'node:events';
const mock = vi.hoisted(() => ({ socket: null as unknown as EventEmitter }));
vi.mock('@/lib/socket', async () => {
  const { EventEmitter } = await import('node:events');
  const socket = Object.assign(new EventEmitter(), {
    connect: vi.fn(),
    disconnect: vi.fn(),
  });
  mock.socket = socket;
  return { socket };
});
it.each([
  ['/', 'Live map'],
  ['/zones/1', 'Zone advisories'],
  ['/advisories', 'Advisories'],
  ['/help', 'Help'],
])('checks accessibility on %s', async (path, title) => {
  const { container } = render(
    <RouterProvider
      router={createMemoryRouter(routes, { initialEntries: [path!] })}
    />,
  );
  await screen.findByRole('heading', { name: title });
  if (path === '/')
    expect(
      within(screen.getAllByRole('article')[0]!).getByText('No data', {
        exact: true,
      }),
    ).toBeInTheDocument();
  expect(
    (await axe(container, { rules: { 'color-contrast': { enabled: false } } }))
      .violations,
  ).toEqual([]);
});
it('resyncs active queries on hello and flags a disconnected feed', async () => {
  const fetcher = vi.fn(async () => 1);
  function Observer() {
    useQuery({ queryKey: ['observed'], queryFn: fetcher });
    return null;
  }
  queryClient.setQueryData(['config'], {});
  render(
    <QueryClientProvider client={queryClient}>
      <RealtimeProvider>
        <Observer />
      </RealtimeProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  act(() => {
    mock.socket.emit('hello');
  });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  act(() => {
    mock.socket.emit('disconnect');
  });
  expect(screen.getByText(/live data may be stale/)).toBeVisible();
  act(() => {
    mock.socket.emit('hello');
  });
  expect(screen.queryByText(/live data may be stale/)).toBeNull();
  queryClient.clear();
});
it('upserts zones and filters or retracts advisories by id', () => {
  const zone = live.data[0] as PublicZoneState,
    item = notices.data[0] as Advisory;
  queryClient.setQueryData(['zones', 'live'], []);
  updateZone(queryClient, zone);
  updateZone(queryClient, { ...zone, level: 'CRITICAL' });
  expect(queryClient.getQueryData(['zones', 'live'])).toEqual([
    { ...zone, level: 'CRITICAL' },
  ]);
  queryClient.setQueryData(['advisories', 'all'], []);
  queryClient.setQueryData(['advisories', 9], []);
  updateAdvisory(queryClient, item.id, { ...item, zone_id: 1 });
  updateAdvisory(queryClient, 9999);
  expect(queryClient.getQueryData(['advisories', 'all'])).toHaveLength(1);
  expect(queryClient.getQueryData(['advisories', 9])).toEqual([]);
  updateAdvisory(queryClient, item.id);
  expect(queryClient.getQueryData(['advisories', 'all'])).toEqual([]);
  queryClient.clear();
});
