import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';
import { createMemoryRouter, MemoryRouter, Route, Routes } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { ErrorBoundary } from 'react-error-boundary';
import { Suspense, useState, type ReactElement } from 'react';
import type {
  ApiList,
  FrameResult,
  PublicZoneState,
  User,
  ZoneState,
} from '@contract/types';
import configFixture from '../../contract/examples/config.json';
import frameResultFixture from '../../contract/examples/frame_result.json';
import zonesFixture from '../../contract/examples/zones.json';
import zonesLiveFixture from '../../contract/examples/zones_live.json';
import zoneStateFixture from '../../contract/examples/zone_state.json';
import alertsListFixture from '../../contract/examples/alerts_list.json';
import alertDetailFixture from '../../contract/examples/alert_detail.json';
import reportsListFixture from '../../contract/examples/reports_list.json';
import advisoriesFixture from '../../contract/examples/advisories.json';
import sourcesFixture from '../../contract/examples/sources.json';
import userFixture from '../../contract/examples/user.json';

const { socketMock, toastMock } = vi.hoisted(() => {
  const listeners = new Map<string, Set<(...args: unknown[]) => void>>();
  return {
    socketMock: {
      connected: true,
      io: {
        on: vi.fn(),
        off: vi.fn(),
      },
      on: vi.fn((event: string, fn: (...args: unknown[]) => void) => {
        const set = listeners.get(event) ?? new Set();
        set.add(fn);
        listeners.set(event, set);
      }),
      off: vi.fn((event: string, fn?: (...args: unknown[]) => void) => {
        if (!fn) {
          listeners.delete(event);
          return;
        }
        listeners.get(event)?.delete(fn);
      }),
      emit: vi.fn(),
      connect: vi.fn(() => {
        socketMock.connected = true;
      }),
      disconnect: vi.fn(() => {
        socketMock.connected = false;
      }),
      listenersFor(event: string) {
        return Array.from(listeners.get(event) ?? []);
      },
      reset() {
        socketMock.connected = true;
        socketMock.connect.mockClear();
        socketMock.disconnect.mockClear();
      },
    },
    toastMock: Object.assign(vi.fn(), {
      error: vi.fn(),
      success: vi.fn(),
      warning: vi.fn(),
    }),
  };
});

vi.mock('sonner', () => ({
  toast: toastMock,
  Toaster: () => (
    <div role="region" aria-label="Notifications" aria-live="polite" />
  ),
}));
vi.mock('@/lib/socket', () => ({ socket: socketMock }));
vi.mock('@/features/zones/ZoneMap', () => ({ default: () => null }));
vi.mock('@/features/reports/ReportPinMap', () => ({
  ReportPinMap: () => null,
  default: () => null,
}));
vi.mock('@/features/admin/ZoneEditorMap', () => ({
  ZoneEditorMap: () => <div data-testid="zone-editor-map-mock" />,
}));

import { apiClient, ApiRequestError } from '@/lib/apiClient';
import { routes } from '@/app/router';
import { AppShell } from '@/app/layouts/AppShell';
import { ErrorFallback } from '@/components/ErrorFallback';
import { AlertCenter } from '@/features/alerts/AlertCenter';
import { LoginForm } from '@/features/auth/AuthForm';
import { useSession } from '@/features/auth';
import { Queue } from '@/features/police/Queue';
import { Detail } from '@/features/police/Detail';
import { LiveMap } from '@/features/zones/PublicPages';
import {
  CrowdReportPage,
  MyReportsPage,
  SosReportPage,
} from '@/features/reports';
import { AdminZonesPage } from '@/features/admin';
import { ZoneEditorPage } from '@/features/admin/ZoneEditor';
import { MonitorPage } from '@/features/monitor/MonitorPage';
import { MonitorHud } from '@/features/monitor/MonitorHud';
import {
  resetStreamSnapshot,
  useMonitorStore,
} from '@/features/monitor/streamStore';
import {
  RealtimeProvider,
  useConnection,
} from '@/features/realtime/RealtimeProvider';

const axeOptions = { rules: { 'color-contrast': { enabled: false } } };

function jsonResponse(body: unknown, status = 200, headers?: HeadersInit) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
}

const policeUser: User = {
  ...(userFixture as User),
  id: 2,
  name: 'Inspector Asha Rao',
  email: 'police1@demo.local',
  role: 'police',
};

const adminUser: User = {
  ...(userFixture as User),
  role: 'admin',
};

const citizenUser: User = {
  ...(userFixture as User),
  id: 4,
  name: 'Kiran Shah',
  email: 'citizen1@demo.local',
  role: 'citizen',
};

function installStandardFetchMock() {
  const noDataZone: PublicZoneState = {
    ...(zonesLiveFixture.data[0] as PublicZoneState),
    zone_id: 99,
    name: 'East Exit (Unmonitored)',
    level: 'NO_DATA',
    density: null,
    trend: 'STEADY',
    updated_at: null,
  };
  const zonesLive: ApiList<PublicZoneState> = {
    data: [zonesLiveFixture.data[0] as PublicZoneState, noDataZone],
    pagination: { page: 1, limit: 50, total: 2, total_pages: 1 },
  };
  const zonesAdmin: ApiList<ZoneState> = {
    data: [{ ...(zoneStateFixture as ZoneState), open_alert_id: null }],
    pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
  };

  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/v1/config'))
      return jsonResponse({ data: configFixture });
    if (url.includes('/api/v1/zones/live')) return jsonResponse(zonesLive);
    if (url.includes('/api/v1/zones/1')) {
      return jsonResponse({
        data: { ...(zoneStateFixture as ZoneState), open_alert_id: null },
      });
    }
    if (url.includes('/api/v1/zones')) return jsonResponse(zonesAdmin);
    if (url.includes('/api/v1/alerts/12'))
      return jsonResponse({ data: alertDetailFixture });
    if (url.includes('/api/v1/alerts')) return jsonResponse(alertsListFixture);
    if (url.includes('/api/v1/reports'))
      return jsonResponse(reportsListFixture);
    if (url.includes('/api/v1/advisories'))
      return jsonResponse(advisoriesFixture);
    if (url.includes('/api/v1/sources')) return jsonResponse(sourcesFixture);
    if (url.includes('/api/v1/analytics')) {
      return jsonResponse({
        data: {
          period_hours: 24,
          total_alerts: 2,
          avg_response_seconds: 120,
          alerts_by_level: { CRITICAL: 1, WARNING: 1 },
          alerts_by_zone: [],
          peak_hours: [],
          total_reports: 1,
          approved_reports: 0,
        },
      });
    }
    return jsonResponse({
      data: zonesFixture.data,
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    });
  });
  vi.stubGlobal('fetch', spy);
  return spy;
}

function stubGeolocation(lat = 18.5195, lng = 73.8553) {
  Object.defineProperty(globalThis.navigator, 'geolocation', {
    configurable: true,
    value: {
      getCurrentPosition: vi.fn((success: PositionCallback) =>
        success({
          coords: {
            latitude: lat,
            longitude: lng,
            accuracy: 10,
            altitude: null,
            altitudeAccuracy: null,
            heading: null,
            speed: null,
          },
          timestamp: Date.now(),
        } as GeolocationPosition),
      ),
    },
  });
}

describe('Phase F8 hardening, accessibility, states, and error checks', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    socketMock.reset();
    toastMock.mockClear();
    toastMock.error.mockClear();
    toastMock.success.mockClear();
    toastMock.warning.mockClear();
    useSession.setState({ user: null, tokens: null });
    useConnection.setState({ status: 'connected' });
    resetStreamSnapshot();
    Object.defineProperty(globalThis.navigator, 'onLine', {
      configurable: true,
      value: true,
    });
  });

  it('passes vitest-axe on login, public map/list, alert queue/detail, report forms, and admin zone table & editor', async () => {
    installStandardFetchMock();
    stubGeolocation();
    const client = makeClient();

    const views: Array<{
      name: string;
      element: ReactElement;
      wait: () => Promise<unknown>;
    }> = [
      {
        name: 'login',
        element: (
          <MemoryRouter>
            <LoginForm />
          </MemoryRouter>
        ),
        wait: () => screen.findByRole('heading', { name: /Sign in/i }),
      },
      {
        name: 'public-map',
        element: (
          <MemoryRouter>
            <LiveMap />
          </MemoryRouter>
        ),
        wait: () =>
          screen.findByRole('button', { name: /East Exit \(Unmonitored\)/i }),
      },
      {
        name: 'police-queue',
        element: (
          <MemoryRouter>
            <Queue />
          </MemoryRouter>
        ),
        wait: () => screen.findByRole('table'),
      },
      {
        name: 'police-detail',
        element: (
          <MemoryRouter initialEntries={['/police/alerts/12']}>
            <Routes>
              <Route path="/police/alerts/:id" element={<Detail />} />
            </Routes>
          </MemoryRouter>
        ),
        wait: () => screen.findAllByText(/Stage Area/i),
      },
      {
        name: 'crowd-report',
        element: (
          <MemoryRouter>
            <CrowdReportPage />
          </MemoryRouter>
        ),
        wait: () => screen.findByRole('heading', { name: /Report a crowd/i }),
      },
      {
        name: 'sos-report',
        element: (
          <MemoryRouter>
            <SosReportPage />
          </MemoryRouter>
        ),
        wait: () => screen.findByRole('button', { name: /Send SOS/i }),
      },
      {
        name: 'my-reports',
        element: (
          <MemoryRouter>
            <MyReportsPage />
          </MemoryRouter>
        ),
        wait: () => screen.findAllByText(/Main Gate/i),
      },
      {
        name: 'admin-zones',
        element: (
          <MemoryRouter>
            <AdminZonesPage />
          </MemoryRouter>
        ),
        wait: () => screen.findAllByText(/Main Gate/i),
      },
      {
        name: 'admin-zone-editor',
        element: (
          <MemoryRouter initialEntries={['/admin/zones/1/edit']}>
            <Routes>
              <Route
                path="/admin/zones/:id/edit"
                element={<ZoneEditorPage />}
              />
            </Routes>
          </MemoryRouter>
        ),
        wait: () => screen.findByRole('heading', { name: /Edit zone/i }),
      },
    ];

    for (const view of views) {
      const rendered = render(
        <QueryClientProvider client={client}>
          <Suspense fallback={null}>{view.element}</Suspense>
        </QueryClientProvider>,
      );
      await view.wait();
      const results = await axe(rendered.container, axeOptions);
      expect(results.violations, `axe violations in ${view.name}`).toEqual([]);
      rendered.unmount();
    }
  });

  it('never renders NO_DATA zone as zero or Safe on the public list', async () => {
    installStandardFetchMock();
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LiveMap />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const cardLink = await screen.findByRole('link', {
      name: /View East Exit \(Unmonitored\)/i,
    });
    const cardText =
      (cardLink.closest('li, article') ?? cardLink.parentElement)
        ?.textContent ?? '';
    expect(cardText).toMatch(/No data/i);
    expect(cardText).not.toMatch(/\bSafe\b/i);
    expect(cardText).not.toMatch(/\b0\b/);
  });

  it('renders both desktop table and mobile card views on /admin/zones so small screens never lose zone rows', async () => {
    installStandardFetchMock();
    const client = makeClient();
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AdminZonesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByRole('table');
    const mobileCards = container.querySelector('.queue-cards');
    expect(mobileCards).not.toBeNull();
    expect(mobileCards?.textContent).toMatch(/Main Gate/);
  });

  it('exposes aria-live="assertive" banner alerts and keyboard navigation', async () => {
    installStandardFetchMock();
    useSession.setState({
      user: policeUser,
      tokens: { access_token: 'tok', refresh_token: 'ref' },
    });
    const client = makeClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AlertCenter />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const banners = await screen.findAllByRole('alert');
    expect(banners.length).toBeGreaterThanOrEqual(1);
    const banner = banners[0]!;
    expect(banner).toHaveAttribute('aria-live', 'assertive');

    const ackBtn = within(banner).getByRole('button', { name: /Acknowledge/i });
    const openLink = within(banner).getByRole('link', { name: /Open/i });
    ackBtn.focus();
    expect(ackBtn).toHaveFocus();
    await user.tab();
    expect(openLink).toHaveFocus();
  });

  it('returns focus to the trigger button when Escape closes Queue action, SOS confirm, and Zone deactivate dialogs', async () => {
    installStandardFetchMock();
    stubGeolocation();
    useSession.setState({
      user: policeUser,
      tokens: { access_token: 'tok', refresh_token: 'ref' },
    });
    const client = makeClient();
    const user = userEvent.setup();

    const queueRender = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Queue />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const ackBtns = await screen.findAllByRole('button', {
      name: /Acknowledge/i,
    });
    const triggerAck = ackBtns[0]!;
    triggerAck.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('dialog')).toBeVisible();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(triggerAck).toHaveFocus();
    queueRender.unmount();

    useSession.setState({
      user: citizenUser,
      tokens: { access_token: 'tok', refresh_token: 'ref' },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <SosReportPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(
      await screen.findByRole('button', { name: /Crush risk/i }),
    );
    const sendBtn = screen.getByRole('button', { name: /Send SOS/i });
    sendBtn.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('dialog')).toBeVisible();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(sendBtn).toHaveFocus();

    useSession.setState({
      user: adminUser,
      tokens: { access_token: 'tok', refresh_token: 'ref' },
    });
    const zonesRender = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AdminZonesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const deactivateBtns = await screen.findAllByRole('button', {
      name: /Deactivate/i,
    });
    const triggerDeactivate = deactivateBtns[0]!;
    triggerDeactivate.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('dialog')).toBeVisible();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(triggerDeactivate).toHaveFocus();
    zonesRender.unmount();
  });

  it('transitions RealtimeProvider to offline immediately on browser offline event and marks UI stale', async () => {
    installStandardFetchMock();
    const client = makeClient();

    const shellRouter = createMemoryRouter(
      [
        {
          path: '/',
          element: (
            <RealtimeProvider>
              <AppShell audience="public">
                <p>Body</p>
              </AppShell>
            </RealtimeProvider>
          ),
        },
      ],
      { initialEntries: ['/'] },
    );

    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={shellRouter} />
      </QueryClientProvider>,
    );

    expect(screen.queryByText(/live data may be stale/i)).toBeNull();

    act(() => {
      Object.defineProperty(globalThis.navigator, 'onLine', {
        configurable: true,
        value: false,
      });
      window.dispatchEvent(new Event('offline'));
    });

    await waitFor(() =>
      expect(useConnection.getState().status).toBe('offline'),
    );
    expect(
      await screen.findByText(/Offline \/ data may be stale/i),
    ).toBeVisible();

    act(() => {
      Object.defineProperty(globalThis.navigator, 'onLine', {
        configurable: true,
        value: true,
      });
      window.dispatchEvent(new Event('online'));
    });

    await waitFor(() =>
      expect(useConnection.getState().status).toBe('reconnecting'),
    );
  });

  it('does not re-render MonitorPage when frame results arrive at 3 FPS in useMonitorStore', async () => {
    installStandardFetchMock();
    const client = makeClient();
    let monitorRenderCount = 0;

    function TrackedMonitorPage() {
      monitorRenderCount += 1;
      return MonitorPage();
    }

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <TrackedMonitorPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByRole('heading', { name: /Camera control/i });
    const settledRenders = monitorRenderCount;

    act(() => {
      for (let i = 1; i <= 30; i += 1) {
        useMonitorStore.setState({
          fps: 3,
          latencyMs: { p50: 42 + i, p95: 75 + i },
          drops: 0,
          lastResultAt: Date.now() + i * 333,
          lastResult: {
            ...(frameResultFixture as FrameResult),
            seq: i,
            count: 5 + (i % 4),
            density: 0.25,
            level: 'WARNING',
          },
        });
      }
    });

    expect(monitorRenderCount).toBe(settledRenders);
  });

  it('handles 401 expiry, 403 forbidden role route, 429 Retry-After, and ErrorFallback retry cleanly', async () => {
    // 1. 401 mid-session when refresh token is rejected -> expires session & warns user
    useSession.setState({
      user: policeUser,
      tokens: { access_token: 'stale-tok', refresh_token: 'stale-ref' },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { error: { code: 'UNAUTHENTICATED', message: 'Expired' } },
          401,
        ),
      ),
    );
    await expect(apiClient('/alerts')).rejects.toBeInstanceOf(ApiRequestError);
    expect(useSession.getState().user).toBeNull();
    expect(toastMock.error).toHaveBeenCalledWith(
      'Session expired. Please sign in again.',
    );

    // 2. 429 rate limit parses Retry-After header cleanly
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { error: { code: 'RATE_LIMITED', message: 'Too many requests' } },
          429,
          { 'Retry-After': '45' },
        ),
      ),
    );
    let caught: unknown;
    try {
      await apiClient('/reports/crowd', { method: 'POST', body: {} });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiRequestError);
    expect((caught as ApiRequestError).status).toBe(429);
    expect((caught as ApiRequestError).retryAfterSeconds).toBe(45);

    // 3. Wrong role visiting /police -> Forbidden UI rendered instead of protected view
    useSession.setState({
      user: citizenUser,
      tokens: { access_token: 'cit-tok', refresh_token: 'cit-ref' },
    });
    installStandardFetchMock();
    const client = makeClient();
    const router = createMemoryRouter(routes, { initialEntries: ['/police'] });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByRole('heading', { name: /Access denied|Forbidden/i }),
    ).toBeVisible();

    // 4. ErrorFallback allows retry after failure resolves
    let shouldFail = true;
    function Flaky() {
      const [tick, setTick] = useState(0);
      if (shouldFail) throw new Error('Backend unavailable');
      return (
        <button onClick={() => setTick((t) => t + 1)}>Recovered {tick}</button>
      );
    }
    const user = userEvent.setup();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary
        FallbackComponent={ErrorFallback}
        onReset={() => {
          shouldFail = false;
        }}
      >
        <Flaky />
      </ErrorBoundary>,
    );
    const alertBox = screen.getByRole('alert');
    expect(alertBox).toHaveTextContent(/Please retry/i);
    await user.click(within(alertBox).getByRole('button', { name: /Retry/i }));
    expect(
      await screen.findByRole('button', { name: /Recovered/i }),
    ).toBeVisible();
  });

  it('keeps Reconnecting until Socket.IO hello arrives AND active queries finish resyncing, and detects backend loss while online', async () => {
    installStandardFetchMock();
    queryClient.clear();

    let call = 0;
    let resolveResync!: (v: string) => void;
    function LiveDataWatcher() {
      const q = useQuery({
        queryKey: ['f8-resync-probe'],
        queryFn: () => {
          call += 1;
          if (call === 1) return Promise.resolve('initial');
          return new Promise<string>((resolve) => {
            resolveResync = resolve;
          });
        },
      });
      return <p>{q.data ?? 'loading'}</p>;
    }

    const resyncRouter = createMemoryRouter(
      [
        {
          path: '/',
          element: (
            <RealtimeProvider>
              <LiveDataWatcher />
            </RealtimeProvider>
          ),
        },
      ],
      { initialEntries: ['/'] },
    );

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={resyncRouter} />
      </QueryClientProvider>,
    );

    await screen.findByText('initial');

    act(() => {
      Object.defineProperty(globalThis.navigator, 'onLine', {
        configurable: true,
        value: false,
      });
      window.dispatchEvent(new Event('offline'));
    });
    expect(
      await screen.findByText(/Offline \/ data may be stale/i),
    ).toBeVisible();
    expect(useConnection.getState().status).toBe('offline');

    act(() => {
      Object.defineProperty(globalThis.navigator, 'onLine', {
        configurable: true,
        value: true,
      });
      window.dispatchEvent(new Event('online'));
    });
    expect(useConnection.getState().status).toBe('reconnecting');

    // Emit hello while the active query resync fetch is still in flight -> must stay Reconnecting.
    act(() => {
      for (const fn of socketMock.listenersFor('hello')) fn();
    });
    await waitFor(() => expect(call).toBe(2));
    expect(useConnection.getState().status).toBe('reconnecting');
    expect(
      screen.getByText(/Reconnecting\.\.\. live data may be stale/i),
    ).toBeVisible();

    // Once active query refetch completes, status transitions to connected.
    await act(async () => {
      resolveResync('synced');
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(useConnection.getState().status).toBe('connected'),
    );

    // Backend loss while browser stays online triggers reconnecting cleanly via watchdog / health failure.
    const watchdogRender = resyncRouter;
    void watchdogRender;
    vi.useFakeTimers();
    const healthFailView = render(
      <QueryClientProvider client={queryClient}>
        <RealtimeProvider>
          <p>Watchdog host</p>
        </RealtimeProvider>
      </QueryClientProvider>,
    );
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 503 })),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });
    expect(useConnection.getState().status).toBe('reconnecting');
    healthFailView.unmount();
    vi.useRealTimers();
    queryClient.clear();
  });

  it('uses container-query responsive grid in MonitorHud so density and badge stay unclipped at narrow panel widths', () => {
    const { container } = render(
      <MonitorHud
        lastResult={{
          ...(frameResultFixture as FrameResult),
          density: 0.1,
          level: 'SAFE',
          ok: true,
        }}
        fps={3}
        latencyMs={{ p50: 42, p95: 75 }}
        drops={0}
      />,
    );

    const region = container.querySelector('[aria-label="Monitor statistics"]');
    expect(region?.className).toContain('@container');
    const grid = region?.firstElementChild;
    expect(grid?.className).toContain('@[300px]:grid-cols-2');
    expect(grid?.className).toContain('@[540px]:grid-cols-4');
    expect(grid?.className).not.toContain('sm:grid-cols-4');
    expect(region?.textContent).toMatch(/0\.1\s*people\/m²/);
    expect(region?.textContent).toContain('Safe');
  });
});
