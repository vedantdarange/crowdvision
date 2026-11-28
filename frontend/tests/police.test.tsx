import { afterEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { Suspense, type ReactElement } from 'react';
import { toast } from 'sonner';
import type {
  Alert,
  AlertStatus,
  AlertEvent,
  ZoneState,
  ApiList,
} from '@contract/types';
import seed from '../../contract/examples/alert.json';
import zoneSeed from '../../contract/examples/zone_state.json';
import { AlertCard } from '@/features/police/Alerts';
import { Timeline } from '@/features/police/Detail';
import { Queue } from '@/features/police/Queue';
import { Dashboard } from '@/features/police/Dashboard';
import {
  updateAlert,
  updatePoliceZone,
  updateSource,
  useSeries,
  activeFeed,
} from '@/features/police/data';
import { queryKeys as k } from '@/lib/queryKeys';
vi.mock('@/features/zones/ZoneMap', () => ({ default: () => null }));
const alert = seed as Alert,
  zone = zoneSeed as ZoneState;
const active = { ...activeFeed, limit: 10, status: '', level: '', zone_id: '' };
const page = (rows: Alert[]) => ({
  data: rows,
  pagination: {
    page: 1,
    limit: 10,
    total: rows.length,
    total_pages: rows.length ? 1 : 0,
  },
});
function client() {
  const c = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  c.setQueryData(k.zones.list, [zone]);
  for (const f of [activeFeed, active, { ...active, active: false }])
    c.setQueryData(k.alerts(f), page([alert]));
  return c;
}
function mount(ui: ReactElement, c = client()) {
  return render(
    <QueryClientProvider client={c}>
      <MemoryRouter>
        <main id="main" tabIndex={-1}>
          <Suspense fallback="Loading">{ui}</Suspense>
        </main>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it.each<[AlertStatus, string[]]>([
  ['NEW', ['Acknowledge', 'Respond', 'Resolve']],
  ['ACKNOWLEDGED', ['Respond', 'Resolve']],
  ['RESPONDING', ['Resolve']],
  ['RESOLVED', []],
  ['AUTO_CLEARED', []],
])('shows only legal actions for %s', (status, buttons) => {
  mount(
    <AlertCard
      alert={{ ...alert, status, condition_active: false }}
      choose={() => {}}
    />,
  );
  expect(screen.queryAllByRole('button').map((b) => b.textContent)).toEqual(
    buttons,
  );
  expect(!!screen.queryByText('Condition cleared - awaiting review')).toBe(
    status === 'NEW',
  );
});
it('names feed loss, restoration and re-raise events', () => {
  const events = ['FEED_LOST', 'FEED_RESTORED', 'CREATED'].map((type, id) => ({
    type,
    id,
    alert_id: 12,
    actor: null,
    created_at: alert.created_at,
    data: { reason: 'STILL_ACTIVE_AFTER_RESOLVE' },
  })) as AlertEvent[];
  mount(<Timeline events={events} />);
  for (const title of [
    'Camera feed lost',
    'Camera feed restored',
    'Raised again: still over the limit',
  ])
    expect(screen.getByText(title)).toBeVisible();
});
it('deduplicates events and moves resolved rows out of active results', () => {
  const c = client(),
    all = k.alerts({ ...active, active: false });
  const fresh = { ...alert, id: 99 };
  updateAlert(c, fresh);
  updateAlert(c, fresh);
  updateAlert(c, { ...fresh, status: 'RESOLVED' });
  expect(c.getQueryData<ApiList<Alert>>(k.alerts(active))?.data).toEqual([
    alert,
  ]);
  const history = c.getQueryData<ApiList<Alert>>(all)!;
  expect(history.data.filter((a) => a.id === 99)).toMatchObject([
    { status: 'RESOLVED' },
  ]);
  expect(history.pagination.total).toBe(2);
  expect(c.getQueryData(k.alertDetail(99))).toMatchObject({
    status: 'RESOLVED',
  });
});
it('keeps a cold zone list stale until its full snapshot arrives', () => {
  const c = new QueryClient();
  updatePoliceZone(c, zone);
  expect(c.getQueryData(k.zones.list)).toEqual([zone]);
  expect(c.getQueryState(k.zones.list)?.dataUpdatedAt).toBe(0);
});
it('bounds the live series and updates source status in both zone caches', () => {
  const c = client();
  useSeries.setState({ zones: {} });
  for (let i = 0; i < 302; i++)
    updatePoliceZone(c, {
      ...zone,
      count: i,
      live_updated_at: new Date(i * 1000).toISOString(),
    });
  const points = useSeries.getState().zones[zone.id]!;
  expect(points.length).toBe(300);
  expect(points[0]?.count).toBe(2);
  expect(points.at(-1)?.count).toBe(301);
  updateSource(c, {
    zone_id: zone.id,
    source_id: zone.sources[0]!.id,
    status: 'OFFLINE',
    last_frame_at: null,
  });
  for (const z of [
    c.getQueryData<ZoneState[]>(k.zones.list)![0],
    c.getQueryData<ZoneState>(k.zones.detail(zone.id)),
  ])
    expect(z?.sources[0]?.status).toBe('OFFLINE');
});
it.each([
  ['dashboard', <Dashboard />],
  ['queue', <Queue />],
] as const)('passes axe on the police %s', async (_name, ui) => {
  const view = mount(ui);
  expect(
    (
      await axe(view.container, {
        rules: { 'color-contrast': { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});
it('operates tabs and dialog by keyboard and rolls back an optimistic acknowledgement on conflict', async () => {
  const c = client(),
    user = userEvent.setup();
  let finish!: (r: Response) => void;
  const fetcher = vi.fn(async (_url: string, opts: RequestInit) =>
    opts.method === 'POST'
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : Response.json(page([alert])),
  );
  vi.stubGlobal('fetch', fetcher);
  const error = vi.spyOn(toast, 'error');
  mount(<Queue />, c);
  await user.tab();
  expect(screen.getByRole('tab', { name: 'Active' })).toHaveFocus();
  await user.keyboard('{ArrowRight}');
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: 'All' })).toHaveAttribute(
      'aria-selected',
      'true',
    ),
  );
  const button = within(screen.getByRole('table')).getByRole('button', {
    name: 'Acknowledge',
  });
  for (let i = 0; i < 30 && document.activeElement !== button; i++)
    await user.tab();
  expect(button).toHaveFocus();
  await user.keyboard('{Enter}');
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByRole('textbox')).toHaveFocus();
  await user.keyboard('Checking{Tab}{Tab}{Enter}');
  const key = k.alerts({ ...active, active: false });
  await waitFor(() =>
    expect(c.getQueryData<ApiList<Alert>>(key)?.data[0]?.status).toBe(
      'ACKNOWLEDGED',
    ),
  );
  await act(async () =>
    finish(
      Response.json(
        { error: { code: 'INVALID_TRANSITION', message: 'Conflict' } },
        { status: 409 },
      ),
    ),
  );
  await waitFor(() =>
    expect(error).toHaveBeenCalledWith('Someone already updated this alert'),
  );
  expect(c.getQueryData<ApiList<Alert>>(key)?.data[0]?.status).toBe('NEW');
  expect(
    fetcher.mock.calls.some(
      ([url, opts]) => url.includes('/alerts?') && opts.method !== 'POST',
    ),
  ).toBe(true);
});
