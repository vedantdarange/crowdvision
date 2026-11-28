import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { Suspense } from 'react';
import { axe } from 'vitest-axe';
import type { Advisory, HistoryPoint, ZoneState } from '@contract/types';
import zonesFixture from '../../contract/examples/zones.json';
import historyFixture from '../../contract/examples/history.json';
import advisoriesFixture from '../../contract/examples/advisories.json';
import { queryKeys as k } from '@/lib/queryKeys';
import { updatePoliceZone, useSeries } from '@/features/police/data';
import { Dashboard } from '@/features/police/Dashboard';
import ZoneChart, { ZoneTooltipContent } from '@/features/zones/ZoneChart';
import { PoliceZoneDetail } from '@/features/zones/PoliceZoneDetail';

vi.mock('@/features/zones/ZoneMap', () => ({ default: () => null }));

const zones = zonesFixture.data as ZoneState[];
const baseHistory = historyFixture.data as HistoryPoint[];
const advisories = advisoriesFixture.data as Advisory[];

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
}

describe('ZoneChart & PoliceZoneDetail (F4b)', () => {
  afterEach(() => {
    useSeries.setState({ zones: {} });
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('uses density thresholds in DENSITY mode and count thresholds in COUNT mode, capped at 300 points', () => {
    const densityZone: ZoneState = {
      ...zones[2]!,
      mode: 'DENSITY',
      warning_density: 2.5,
      critical_density: 3.8,
    };
    const countZone: ZoneState = {
      ...zones[0]!,
      mode: 'COUNT',
      warning_count: 7,
      critical_count: 11,
    };

    const manyPoints = Array.from({ length: 320 }, (_, i) => ({
      ts: new Date(Date.UTC(2026, 10, 24, 10, 0, i)).toISOString(),
      count: i,
      density: Number((i * 0.01).toFixed(2)),
      level: 'SAFE' as const,
    }));

    const { rerender } = render(
      <ZoneChart zone={densityZone} points={manyPoints} />,
    );
    expect(screen.getByText(/Warning \(2\.5\)/)).toBeInTheDocument();
    expect(screen.getByText(/Critical \(3\.8\)/)).toBeInTheDocument();
    expect(screen.getByText(/Showing 300 points \(max 300\)/)).toBeVisible();

    rerender(<ZoneChart zone={countZone} points={manyPoints} />);
    expect(screen.getByText(/Warning \(7\)/)).toBeInTheDocument();
    expect(screen.getByText(/Critical \(11\)/)).toBeInTheDocument();
    expect(screen.getByText(/People count/)).toBeVisible();
  });

  it('renders tooltip with metric and level text in both DENSITY and COUNT modes', () => {
    const { rerender } = render(
      <ZoneTooltipContent
        active
        zone={zones[2]!}
        payload={[
          {
            payload: {
              ts: '2026-11-24T10:15:30Z',
              count: 25,
              density: 4.2,
              level: 'CRITICAL',
              value: 4.2,
              timeLabel: '15:45:30',
            },
          },
        ]}
      />,
    );
    expect(screen.getByText(/4\.2 people\/m²/)).toBeVisible();
    expect(screen.getByText('Critical')).toBeVisible();

    rerender(
      <ZoneTooltipContent
        active
        zone={zones[0]!}
        payload={[
          {
            payload: {
              ts: '2026-11-24T10:15:30Z',
              count: 4,
              density: 0.2,
              level: 'WARNING',
              value: 4,
              timeLabel: '15:45:30',
            },
          },
        ]}
      />,
    );
    expect(screen.getByText(/4 people/)).toBeVisible();
    expect(screen.getByText('Warning')).toBeVisible();
  });

  it('shows skeleton while history loads, switches bucket_s across 30 min (10), 2 h (60), and 24 h (300), and retries on error', async () => {
    const user = userEvent.setup();
    const zone: ZoneState = {
      ...zones[2]!,
      level: 'WARNING',
      trend: 'RISING',
      count: 20,
      density: 3.4,
      live_updated_at: new Date().toISOString(),
      sources: [
        {
          ...zones[2]!.sources[0]!,
          status: 'ONLINE',
          last_frame_at: new Date(Date.now() - 4000).toISOString(),
        },
      ],
    };

    const historyCalls: string[] = [];
    let failNextHistory = false;
    let resolvePendingHistory: ((r: Response) => void) | null = null;

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes('/history')) {
          historyCalls.push(url);
          if (failNextHistory) {
            failNextHistory = false;
            return Response.json(
              { error: { code: 'INTERNAL', message: 'Boom' } },
              { status: 500 },
            );
          }
          if (url.includes('bucket_s=10') && historyCalls.length === 1) {
            return new Promise<Response>((resolve) => {
              resolvePendingHistory = resolve;
            });
          }
          return Response.json({ data: baseHistory });
        }
        if (url.includes('/advisories')) {
          return Response.json({ data: advisories });
        }
        if (url.includes('/zones/3')) {
          return Response.json({ data: zone });
        }
        return Response.json({ data: [] });
      }),
    );

    const client = makeClient();
    client.setQueryData(k.zones.detail(3), zone);
    client.setQueryData(k.advisories(3), advisories);

    const view = render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/police/zones/3']}>
          <Routes>
            <Route
              path="/police/zones/:id"
              element={
                <main id="main" tabIndex={-1}>
                  <Suspense fallback="Loading">
                    <PoliceZoneDetail />
                  </Suspense>
                </main>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText('Loading zone history chart'),
    ).toBeInTheDocument();

    await act(async () => {
      resolvePendingHistory?.(Response.json({ data: baseHistory }));
    });

    expect(
      await screen.findByText('Currently 3.4 people per square metre, rising.'),
    ).toBeVisible();
    expect(screen.getByText('Warning')).toBeVisible();
    expect(screen.getByText('Rising')).toBeVisible();
    expect(screen.getByText('ONLINE')).toBeVisible();
    expect(screen.getByText(/Last frame/)).toBeVisible();
    expect(screen.getByText(advisories[0]!.title)).toBeVisible();

    await waitFor(() =>
      expect(historyCalls.some((u) => u.includes('bucket_s=10'))).toBe(true),
    );

    await user.click(screen.getByRole('button', { name: '2 h' }));
    await waitFor(() =>
      expect(historyCalls.some((u) => u.includes('bucket_s=60'))).toBe(true),
    );

    failNextHistory = true;
    await user.click(screen.getByRole('button', { name: '24 h' }));
    expect(
      await screen.findByText('Could not load zone history samples.'),
    ).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(
        historyCalls.filter((u) => u.includes('bucket_s=300')).length,
      ).toBeGreaterThanOrEqual(2),
    );

    act(() => {
      updatePoliceZone(client, {
        ...zone,
        level: 'CRITICAL',
        density: 4.5,
        count: 27,
        live_updated_at: new Date().toISOString(),
      });
    });
    expect(
      await screen.findByText('Currently 4.5 people per square metre, rising.'),
    ).toBeVisible();

    expect(
      (
        await axe(view.container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  });

  it('shows empty state when both history and live series are empty', async () => {
    const zone = zones[0]!;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes('/history')) return Response.json({ data: [] });
        if (url.includes('/advisories')) return Response.json({ data: [] });
        return Response.json({ data: zone });
      }),
    );

    const client = makeClient();
    client.setQueryData(k.zones.detail(1), zone);
    client.setQueryData(k.advisories(1), []);

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/police/zones/1']}>
          <Routes>
            <Route
              path="/police/zones/:id"
              element={
                <Suspense fallback="Loading">
                  <PoliceZoneDetail />
                </Suspense>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('No history samples yet')).toBeVisible();
    expect(screen.getByText('OFFLINE')).toBeVisible();
    expect(screen.getByText('Last frame: never')).toBeVisible();
    expect(
      screen.getByText('No active advisories for this zone.'),
    ).toBeVisible();
  });

  it('links dashboard zone cards to /police/zones/:id', async () => {
    const client = makeClient();
    client.setQueryData(k.zones.list, zones);
    client.setQueryData(k.alerts({ active: true, page: 1, limit: 8 }), {
      data: [],
      pagination: { total: 0, page: 1, limit: 8, total_pages: 0 },
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Suspense fallback="Loading">
            <Dashboard />
          </Suspense>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const card = await screen.findByRole('heading', { name: 'Main Gate' });
    const article = card.closest('article')!;
    const links = within(article).getAllByRole('link');
    expect(
      links.some((l) => l.getAttribute('href') === '/police/zones/1'),
    ).toBe(true);
  });
});
