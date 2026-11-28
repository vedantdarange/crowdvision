import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { PolygonGeometry, SourceInfo, ZoneState } from '@contract/types';
import sourcesFixture from '../../contract/examples/sources.json';
import userFixture from '../../contract/examples/user.json';
import zonesFixture from '../../contract/examples/zones.json';
import { AdminSourcesPage, AdminZonesPage } from '@/features/admin';
import { ZoneDrawControl } from '@/features/admin/ZoneDrawControl';
import { ZoneEditorPage } from '@/features/admin/ZoneEditor';
import { useSession } from '@/features/auth';

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
  }),
);
vi.mock('sonner', () => ({ toast: toastMock }));

const mapLibMocks = vi.hoisted(() => {
  const controlListeners = new Map<string, Set<() => void>>();
  const tdListeners = new Map<string, Set<(...args: unknown[]) => void>>();
  let snapshot: Array<Record<string, unknown>> = [];
  let featureSeq = 1;

  const tdInstance = {
    enabled: false,
    on: vi.fn((event: string, cb: (...args: unknown[]) => void) => {
      if (!tdListeners.has(event)) tdListeners.set(event, new Set());
      tdListeners.get(event)!.add(cb);
    }),
    off: vi.fn((event: string, cb: (...args: unknown[]) => void) => {
      tdListeners.get(event)?.delete(cb);
    }),
    getSnapshot: vi.fn(() => snapshot),
    getFeatureId: vi.fn(() => `feat-${featureSeq++}`),
    addFeatures: vi.fn((features: Array<Record<string, unknown>>) => {
      snapshot = [...snapshot, ...features];
      return [];
    }),
    removeFeatures: vi.fn((ids: Array<string | number>) => {
      snapshot = snapshot.filter((f) => !ids.includes(f.id as string));
    }),
    setMode: vi.fn(),
  };

  let lastControl: unknown = null;
  let lastOptions: unknown = null;

  class MockTerradrawControl {
    constructor(options: unknown) {
      lastOptions = options;
    }
    onAdd = vi.fn(() => document.createElement('div'));
    onRemove = vi.fn();
    on = vi.fn((event: string, cb: () => void) => {
      if (!controlListeners.has(event)) controlListeners.set(event, new Set());
      controlListeners.get(event)!.add(cb);
    });
    off = vi.fn((event: string, cb: () => void) => {
      controlListeners.get(event)?.delete(cb);
    });
    getTerraDrawInstance = vi.fn(() => tdInstance);
  }

  const fakeMap = {
    loaded: vi.fn(() => true),
    once: vi.fn(),
    off: vi.fn(),
    addControl: vi.fn((ctrl: unknown) => {
      lastControl = ctrl;
    }),
    hasControl: vi.fn(() => true),
    removeControl: vi.fn(),
  };

  return {
    MockTerradrawControl,
    tdInstance,
    fakeMap,
    reset() {
      controlListeners.clear();
      tdListeners.clear();
      snapshot = [];
      featureSeq = 1;
      tdInstance.enabled = false;
      vi.clearAllMocks();
      fakeMap.loaded.mockReturnValue(true);
      fakeMap.hasControl.mockReturnValue(true);
    },
    emitTd(event: string, ...args: unknown[]) {
      for (const cb of tdListeners.get(event) ?? []) cb(...args);
    },
    emitControl(event: string) {
      for (const cb of controlListeners.get(event) ?? []) cb();
    },
    setSnapshot(next: Array<Record<string, unknown>>) {
      snapshot = next;
    },
    getLastOptions: () => lastOptions,
    getLastControl: () => lastControl,
  };
});

vi.mock('@watergis/maplibre-gl-terradraw', () => ({
  MaplibreTerradrawControl: mapLibMocks.MockTerradrawControl,
}));

vi.mock('@vis.gl/react-maplibre', () => ({
  default: () => null,
  NavigationControl: () => null,
  AttributionControl: () => null,
  Source: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  Layer: () => null,
  useMap: () => ({ current: { getMap: () => mapLibMocks.fakeMap } }),
}));

let mockNextDrawnPolygon: PolygonGeometry | null = null;
vi.mock('@/features/admin/ZoneEditorMap', () => ({
  ZoneEditorMap: ({
    initialPolygon,
    onPolygonChange,
  }: {
    initialPolygon: PolygonGeometry | null;
    onPolygonChange: (p: PolygonGeometry | null) => void;
  }) => (
    <div data-testid="zone-editor-map-stub">
      <span>
        {initialPolygon ? 'Has initial polygon' : 'No initial polygon'}
      </span>
      <button
        type="button"
        onClick={() => onPolygonChange(mockNextDrawnPolygon)}
      >
        Simulate draw polygon
      </button>
    </div>
  ),
}));

const SAMPLE_POLY: PolygonGeometry = {
  type: 'Polygon',
  coordinates: [
    [
      [73.855, 18.519],
      [73.8551, 18.519],
      [73.8551, 18.5191],
      [73.855, 18.5191],
      [73.855, 18.519],
    ],
  ],
};

const BOWTIE_POLY: PolygonGeometry = {
  type: 'Polygon',
  coordinates: [
    [
      [73.855, 18.519],
      [73.8551, 18.5191],
      [73.8551, 18.519],
      [73.855, 18.5191],
      [73.855, 18.519],
    ],
  ],
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
}

describe('ZoneDrawControl wrapper', () => {
  beforeEach(() => {
    mapLibMocks.reset();
  });

  it('adds control, enforces single polygon, handles delete, and removes control/listeners on unmount', () => {
    const onChange = vi.fn();
    const { unmount } = render(
      <ZoneDrawControl initialPolygon={SAMPLE_POLY} onChange={onChange} />,
    );

    expect(mapLibMocks.getLastOptions()).toEqual({
      modes: ['polygon', 'select', 'delete'],
      open: true,
      showDeleteConfirmation: false,
    });
    expect(mapLibMocks.fakeMap.addControl).toHaveBeenCalledWith(
      mapLibMocks.getLastControl(),
      'top-right',
    );

    // Ready seeds the edit polygon and enters select mode.
    mapLibMocks.emitTd('ready');
    expect(mapLibMocks.tdInstance.addFeatures).toHaveBeenCalledTimes(1);
    expect(mapLibMocks.tdInstance.setMode).toHaveBeenCalledWith('select');

    // Drawing a second polygon removes the first so only one remains.
    const secondPoly: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [73.856, 18.52],
          [73.8562, 18.52],
          [73.8562, 18.5202],
          [73.856, 18.5202],
          [73.856, 18.52],
        ],
      ],
    };
    mapLibMocks.setSnapshot([
      {
        id: 'feat-1',
        type: 'Feature',
        geometry: SAMPLE_POLY,
        properties: { mode: 'polygon' },
      },
      {
        id: 'feat-2',
        type: 'Feature',
        geometry: secondPoly,
        properties: { mode: 'polygon' },
      },
    ]);
    mapLibMocks.emitTd('finish', 'feat-2');
    expect(mapLibMocks.tdInstance.removeFeatures).toHaveBeenCalledWith([
      'feat-1',
    ]);
    expect(onChange).toHaveBeenLastCalledWith(secondPoly);

    // Deleting clears polygon cleanly.
    mapLibMocks.setSnapshot([]);
    mapLibMocks.emitControl('feature-deleted');
    expect(onChange).toHaveBeenLastCalledWith(null);

    // Unmount cleans up Terra Draw listeners and removes control from map.
    unmount();
    expect(mapLibMocks.tdInstance.off).toHaveBeenCalled();
    expect(mapLibMocks.fakeMap.removeControl).toHaveBeenCalledWith(
      mapLibMocks.getLastControl(),
    );
  });
});

const originalResizeObserverDesc = Object.getOwnPropertyDescriptor(
  globalThis,
  'ResizeObserver',
);

function stubResizeObserver() {
  if (typeof globalThis.ResizeObserver === 'undefined') {
    Object.defineProperty(globalThis, 'ResizeObserver', {
      configurable: true,
      writable: true,
      value: class ResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    });
  }
}

function restoreResizeObserver() {
  if (originalResizeObserverDesc) {
    Object.defineProperty(
      globalThis,
      'ResizeObserver',
      originalResizeObserverDesc,
    );
  } else {
    delete (globalThis as Record<string, unknown>).ResizeObserver;
  }
}

describe('AdminZonesPage (/admin/zones)', () => {
  beforeEach(() => {
    stubResizeObserver();
    toastMock.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
    useSession.setState({
      user: { ...userFixture, id: 1, role: 'admin' },
      tokens: { access_token: 'adm-tok', refresh_token: 'adm-ref' },
    });
  });

  afterEach(() => {
    restoreResizeObserver();
    vi.restoreAllMocks();
    useSession.setState({ user: null, tokens: null });
  });

  it('renders zone table, shows "Resolve its alert first" on 409 CONFLICT, handles empty state, and passes axe', async () => {
    const zones = (zonesFixture as { data: ZoneState[] }).data;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/zones/1') && init?.method === 'DELETE') {
        return new Response(
          JSON.stringify({
            error: {
              code: 'CONFLICT',
              message: 'Cannot deactivate zone with open alert.',
            },
          }),
          { status: 409, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ data: zones }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = makeClient();
    const router = createMemoryRouter(
      [
        {
          path: '/admin/zones',
          element: (
            <main>
              <AdminZonesPage />
            </main>
          ),
        },
        { path: '/admin/zones/new', element: <div>New</div> },
        { path: '/admin/zones/:id/edit', element: <div>Edit</div> },
        { path: '/admin/sources', element: <div>Sources</div> },
      ],
      { initialEntries: ['/admin/zones'] },
    );

    const { container } = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    const table = await screen.findByRole('table');
    expect(within(table).getByText('Main Gate')).toBeVisible();
    expect(screen.getByRole('link', { name: /New zone/i })).toHaveAttribute(
      'href',
      '/admin/zones/new',
    );
    expect((await axe(container)).violations).toEqual([]);

    const mainGateRow = within(table).getByText('Main Gate').closest('tr')!;
    await userEvent.click(
      within(mainGateRow).getByRole('button', { name: /Deactivate/i }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Confirm deactivate/i }),
    );

    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith('Resolve its alert first.');
      expect(
        screen.getByText(/Resolve its alert first before deactivating/i),
      ).toBeInTheDocument();
    });
  });

  it('renders empty state on /admin/zones when no zones exist', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const client = makeClient();
    const router = createMemoryRouter(
      [
        {
          path: '/admin/zones',
          element: (
            <main>
              <AdminZonesPage />
            </main>
          ),
        },
        { path: '/admin/zones/new', element: <div>New</div> },
      ],
      { initialEntries: ['/admin/zones'] },
    );

    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('No zones configured')).toBeVisible();
  });
});

describe('ZoneEditorPage (/admin/zones/new & /admin/zones/:id/edit)', () => {
  beforeEach(() => {
    stubResizeObserver();
    mockNextDrawnPolygon = SAMPLE_POLY;
    toastMock.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
    useSession.setState({
      user: { ...userFixture, id: 1, role: 'admin' },
      tokens: { access_token: 'adm-tok', refresh_token: 'adm-ref' },
    });
  });

  afterEach(() => {
    restoreResizeObserver();
    vi.restoreAllMocks();
    useSession.setState({ user: null, tokens: null });
  });

  it('validates Fruin thresholds, COUNT counts, self-intersecting polygon, maps server 422, creates zone, and passes axe', async () => {
    const zones = (zonesFixture as { data: ZoneState[] }).data;
    let return422Once = true;
    let submittedPayload: Record<string, unknown> | undefined;

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/zones') && init?.method === 'POST') {
        submittedPayload = JSON.parse(String(init.body)) as Record<
          string,
          unknown
        >;
        if (return422Once) {
          return422Once = false;
          return new Response(
            JSON.stringify({
              error: {
                code: 'VALIDATION_ERROR',
                message: 'Validation failed',
                details: {
                  name: ['Server says name is invalid.'],
                  area_m2: ['Area differs by more than 10%.'],
                },
              },
            }),
            { status: 422, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response(
          JSON.stringify({
            data: {
              ...zones[0]!,
              id: 77,
              name: String(submittedPayload.name),
              area_m2: 118.4,
            },
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ data: zones }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = makeClient();
    const router = createMemoryRouter(
      [
        {
          path: '/admin/zones/new',
          element: (
            <main>
              <ZoneEditorPage />
            </main>
          ),
        },
        { path: '/admin/zones', element: <div>Zones List Target</div> },
      ],
      { initialEntries: ['/admin/zones/new'] },
    );

    const { container } = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await screen.findByRole('button', { name: /Simulate draw polygon/i });
    expect(screen.getByText(/Fruin crowd-safety thresholds/i)).toBeVisible();
    expect((await axe(container)).violations).toEqual([]);

    // Draw self-intersecting polygon -> rejected immediately.
    mockNextDrawnPolygon = BOWTIE_POLY;
    await userEvent.click(
      screen.getByRole('button', { name: /Simulate draw polygon/i }),
    );
    expect(
      screen.getByText(/Polygon edges cannot cross or self-intersect/i),
    ).toBeInTheDocument();

    // Draw valid polygon -> preview Area rendered.
    mockNextDrawnPolygon = SAMPLE_POLY;
    await userEvent.click(
      screen.getByRole('button', { name: /Simulate draw polygon/i }),
    );
    expect(screen.getByText(/Area: \d+\.\d m² \(preview/i)).toBeInTheDocument();

    // Test warning >= critical rejection.
    await userEvent.type(screen.getByLabelText('Name'), 'VIP Tent');
    const warnInput = screen.getByLabelText(/Warning density/i);
    await userEvent.clear(warnInput);
    await userEvent.type(warnInput, '4.5');
    await userEvent.click(screen.getByRole('button', { name: /Create zone/i }));
    expect(
      await screen.findByText(/Warning density must be lower than critical/i),
    ).toBeInTheDocument();

    // Fix density, switch to COUNT mode, verify counts required.
    await userEvent.clear(warnInput);
    await userEvent.type(warnInput, '3.0');
    await userEvent.selectOptions(
      screen.getByLabelText('Monitoring mode'),
      'COUNT',
    );
    await userEvent.click(screen.getByRole('button', { name: /Create zone/i }));
    expect(
      await screen.findByText(/Warning count is required in Count mode/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Critical count is required in Count mode/i),
    ).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Warning count/i), '8');
    await userEvent.type(screen.getByLabelText(/Critical count/i), '10');

    // First submit returns server 422 -> maps onto Name field & area banner.
    await userEvent.click(screen.getByRole('button', { name: /Create zone/i }));
    expect(
      await screen.findByText('Server says name is invalid.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Area differs by more than 10%.'),
    ).toBeInTheDocument();

    // Re-validate and submit successfully -> redirects to /admin/zones with saved server area toast.
    mockNextDrawnPolygon = SAMPLE_POLY;
    await userEvent.click(
      screen.getByRole('button', { name: /Simulate draw polygon/i }),
    );
    await userEvent.click(screen.getByRole('button', { name: /Create zone/i }));

    await waitFor(() => {
      expect(screen.getByText('Zones List Target')).toBeInTheDocument();
    });
    expect(submittedPayload?.mode).toBe('COUNT');
    expect(submittedPayload?.warning_count).toBe(8);
    expect(submittedPayload?.critical_count).toBe(10);
    expect(toastMock.success).toHaveBeenCalledWith(
      'Saved "VIP Tent" (118.4 m²).',
    );
  });

  it('pre-populates existing zone in edit mode and submits PATCH /zones/:id', async () => {
    const zones = (zonesFixture as { data: ZoneState[] }).data;
    const targetZone = zones[0]!;
    let patchedBody: Record<string, unknown> | undefined;

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith(`/zones/${targetZone.id}`) && init?.method === 'PATCH') {
        patchedBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return new Response(
          JSON.stringify({
            data: {
              ...targetZone,
              ...patchedBody,
              area_m2: 41.2,
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url.endsWith(`/zones/${targetZone.id}`)) {
        return new Response(JSON.stringify({ data: targetZone }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({ data: zones }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = makeClient();
    const router = createMemoryRouter(
      [
        {
          path: '/admin/zones/:id/edit',
          element: (
            <main>
              <ZoneEditorPage />
            </main>
          ),
        },
        { path: '/admin/zones', element: <div>Zones List Target</div> },
      ],
      { initialEntries: [`/admin/zones/${targetZone.id}/edit`] },
    );

    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(
        `Saved area: ${targetZone.area_m2.toFixed(1)} m²`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue(targetZone.name);

    await userEvent.click(screen.getByRole('switch', { name: /Active zone/i }));
    await userEvent.click(
      screen.getByRole('button', { name: /Save changes/i }),
    );

    await waitFor(() => {
      expect(screen.getByText('Zones List Target')).toBeInTheDocument();
    });
    expect(patchedBody?.is_active).toBe(false);
    expect(toastMock.success).toHaveBeenCalledWith(
      `Saved "${targetZone.name}" (41.2 m²).`,
    );
  });
});

describe('AdminSourcesPage (/admin/sources)', () => {
  beforeEach(() => {
    stubResizeObserver();
    toastMock.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
    useSession.setState({
      user: { ...userFixture, id: 1, role: 'admin' },
      tokens: { access_token: 'adm-tok', refresh_token: 'adm-ref' },
    });
  });

  afterEach(() => {
    restoreResizeObserver();
    vi.restoreAllMocks();
    useSession.setState({ user: null, tokens: null });
  });

  it('validates 1 <= coverage <= 2x zone area, creates/edits/disables sources, and passes axe', async () => {
    const zones = (zonesFixture as { data: ZoneState[] }).data;
    let sources = [...(sourcesFixture as { data: SourceInfo[] }).data];
    let createdBody: Record<string, unknown> | undefined;

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/zones')) {
        return new Response(JSON.stringify({ data: zones }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/sources') && init?.method === 'POST') {
        createdBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        const created: SourceInfo = {
          id: 90,
          zone_id: Number(createdBody.zone_id),
          name: String(createdBody.name),
          kind: createdBody.kind as SourceInfo['kind'],
          coverage_area_m2: Number(createdBody.coverage_area_m2),
          is_active: true,
          status: 'OFFLINE',
          last_frame_at: null,
          created_at: '2026-11-28T14:50:00Z',
        };
        sources = [...sources, created];
        return new Response(JSON.stringify({ data: created }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('/sources/90') && init?.method === 'PATCH') {
        const patch = JSON.parse(String(init.body)) as Record<string, unknown>;
        sources = sources.map((s) => (s.id === 90 ? { ...s, ...patch } : s));
        return new Response(
          JSON.stringify({ data: sources.find((s) => s.id === 90) }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url.includes('/sources/90') && init?.method === 'DELETE') {
        sources = sources.filter((s) => s.id !== 90);
        return new Response(null, { status: 204 });
      }
      return new Response(JSON.stringify({ data: sources }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = makeClient();
    const router = createMemoryRouter(
      [
        {
          path: '/admin/sources',
          element: (
            <main>
              <AdminSourcesPage />
            </main>
          ),
        },
      ],
      { initialEntries: ['/admin/sources'] },
    );

    const { container } = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await screen.findByLabelText(/Coverage area/i);
    expect(
      screen.getByText(
        /the area your camera actually sees; smaller than the zone is fine/i,
      ),
    ).toBeVisible();
    expect((await axe(container)).violations).toEqual([]);

    // Zone 1 area_m2 = 40 -> max coverage = 80. Entering 95 rejects.
    await userEvent.type(
      screen.getByLabelText('Source name'),
      'East Tripod Cam',
    );
    const covInput = screen.getByLabelText(/Coverage area/i);
    await userEvent.clear(covInput);
    await userEvent.type(covInput, '95');
    await userEvent.click(screen.getByRole('button', { name: /Add source/i }));

    expect(
      await screen.findByText(/Coverage must be between 1 and 80\.0 m²/i),
    ).toBeInTheDocument();

    // Valid coverage 25.5 -> POST /sources sends coverage_area_m2.
    await userEvent.clear(covInput);
    await userEvent.type(covInput, '25.5');
    await userEvent.click(screen.getByRole('button', { name: /Add source/i }));

    const zone1Section = screen.getByLabelText(/Sources in Main Gate/i);
    const zone1Table = within(zone1Section).getByRole('table');
    expect(
      await within(zone1Table).findByText('East Tripod Cam'),
    ).toBeVisible();
    expect(createdBody?.coverage_area_m2).toBe(25.5);

    // Edit newly created source -> PATCH
    const newRow = within(zone1Table)
      .getByText('East Tripod Cam')
      .closest('tr')!;
    await userEvent.click(
      within(newRow).getByRole('button', { name: /Edit/i }),
    );
    const editCov = screen.getByLabelText('Coverage area (m²)', {
      selector: '#edit-src-coverage',
    });
    await userEvent.clear(editCov);
    await userEvent.type(editCov, '30');
    await userEvent.click(
      screen.getByRole('button', { name: /Save changes/i }),
    );
    await waitFor(() => {
      expect(within(zone1Table).getByText('30.0 m²')).toBeVisible();
    });

    // Disable -> confirm dialog -> DELETE
    const updatedRow = within(zone1Table)
      .getByText('East Tripod Cam')
      .closest('tr')!;
    await userEvent.click(
      within(updatedRow).getByRole('button', { name: /Disable/i }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Confirm disable/i }),
    );
    await waitFor(() => {
      expect(within(zone1Table).queryByText('East Tripod Cam')).toBeNull();
    });
  });
});
