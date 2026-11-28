import { EventEmitter } from 'node:events';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { Report } from '@contract/types';
import crowdFixture from '../../contract/examples/report_crowd.json';
import sosFixture from '../../contract/examples/report_sos.json';
import reportsListFixture from '../../contract/examples/reports_list.json';
import userFixture from '../../contract/examples/user.json';
import zonesFixture from '../../contract/examples/zones.json';
import { useSession } from '@/features/auth';
import { RealtimeProvider } from '@/features/realtime/RealtimeProvider';
import { queryClient as appQueryClient } from '@/lib/queryClient';
import {
  CrowdReportPage,
  downscaleCrowdImage,
  fitDimensions,
  MyReportsPage,
  ReportReviewPage,
  SosReportPage,
  useGeolocation,
} from '@/features/reports';

const socketMock = vi.hoisted(() => ({
  socket: null as unknown as EventEmitter & {
    auth?: unknown;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  },
}));

vi.mock('@/lib/socket', async () => {
  const { EventEmitter } = await import('node:events');
  const emitter = Object.assign(new EventEmitter(), {
    auth: {},
    connect: vi.fn(),
    disconnect: vi.fn(),
  });
  socketMock.socket = emitter;
  return { socket: emitter };
});

vi.mock('@/features/reports/ReportPinMap', () => ({
  default: ({ report }: { report: Report }) => (
    <div data-testid="pin-map-stub">
      Pin #{report.id} ({report.lat}, {report.lng})
    </div>
  ),
}));

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
  }),
);
vi.mock('sonner', () => ({ toast: toastMock }));

const origGeolocationDesc = Object.getOwnPropertyDescriptor(
  navigator,
  'geolocation',
);
const origCreateObjectUrl = URL.createObjectURL;
const origRevokeObjectUrl = URL.revokeObjectURL;

function restoreEnv() {
  if (origGeolocationDesc) {
    Object.defineProperty(navigator, 'geolocation', origGeolocationDesc);
  } else {
    delete (navigator as unknown as Record<string, unknown>).geolocation;
  }
  URL.createObjectURL = origCreateObjectUrl;
  URL.revokeObjectURL = origRevokeObjectUrl;
}

function stubGeolocationSuccess(lat = 18.5195, lng = 73.8553, accuracy = 12.4) {
  const getCurrentPosition = vi.fn((success: PositionCallback) => {
    success({
      coords: {
        latitude: lat,
        longitude: lng,
        accuracy,
        altitude: null,
        altitudeAccuracy: null,
        heading: null,
        speed: null,
        toJSON: () => ({}),
      },
      timestamp: Date.now(),
      toJSON: () => ({}),
    });
  });
  Object.defineProperty(navigator, 'geolocation', {
    value: { getCurrentPosition },
    configurable: true,
  });
  return getCurrentPosition;
}

function makeQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(['config'], {
    target_fps: 3,
    frame_width: 640,
    jpeg_quality: 0.7,
    stale_after_s: 15,
    vapid_public_key: null,
    app_version: '0.1.0',
    contract_version: '1.1.0',
  });
  return client;
}

describe('fitDimensions & downscaleCrowdImage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    restoreEnv();
  });

  it('scales longest side <= 1280 while keeping aspect ratio', () => {
    expect(fitDimensions(3000, 1500, 1280)).toEqual({
      width: 1280,
      height: 640,
    });
    expect(fitDimensions(1500, 3000, 1280)).toEqual({
      width: 640,
      height: 1280,
    });
    expect(fitDimensions(800, 600, 1280)).toEqual({ width: 800, height: 600 });
  });

  it('re-encodes photo as image/jpeg with quality 0.8 and releases loader resource', async () => {
    const release = vi.fn();
    const draw = vi.fn();
    const toJpegBlob = vi
      .fn()
      .mockResolvedValue(new Blob(['jpeg-bytes'], { type: 'image/jpeg' }));
    const createCanvas = vi.fn(() => ({ draw, toJpegBlob }));

    const file = new File(['raw-png'], 'crowd.png', { type: 'image/png' });
    const result = await downscaleCrowdImage(file, {
      maxSide: 1280,
      quality: 0.8,
      deps: {
        loadImage: async () => ({
          image: { width: 2560, height: 1920 } as unknown as HTMLImageElement,
          release,
        }),
        createCanvas,
      },
    });

    expect(result.width).toBe(1280);
    expect(result.height).toBe(960);
    expect(result.blob.type).toBe('image/jpeg');
    expect(createCanvas).toHaveBeenCalledWith(1280, 960);
    expect(draw).toHaveBeenCalledTimes(1);
    expect(toJpegBlob).toHaveBeenCalledWith(0.8);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it('rejects non-image uploads cleanly', async () => {
    const badFile = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    await expect(downscaleCrowdImage(badFile)).rejects.toThrow(/image/i);
  });
});

describe('useGeolocation state machine', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    restoreEnv();
  });

  it('handles denied -> retry -> ready and timeout states with 10s high-accuracy options', () => {
    const mockGetPos = vi
      .fn()
      .mockImplementationOnce(
        (_ok: PositionCallback, err: PositionErrorCallback) => {
          err({
            code: 1,
            message: 'Denied',
            PERMISSION_DENIED: 1,
            POSITION_UNAVAILABLE: 2,
            TIMEOUT: 3,
          } as GeolocationPositionError);
        },
      )
      .mockImplementationOnce(
        (_ok: PositionCallback, err: PositionErrorCallback) => {
          err({
            code: 3,
            message: 'Timed out',
            PERMISSION_DENIED: 1,
            POSITION_UNAVAILABLE: 2,
            TIMEOUT: 3,
          } as GeolocationPositionError);
        },
      )
      .mockImplementationOnce((ok: PositionCallback) => {
        ok({
          coords: {
            latitude: 18.52,
            longitude: 73.85,
            accuracy: 14.6,
            altitude: null,
            altitudeAccuracy: null,
            heading: null,
            speed: null,
            toJSON: () => ({}),
          },
          timestamp: Date.now(),
          toJSON: () => ({}),
        });
      });

    Object.defineProperty(navigator, 'geolocation', {
      value: { getCurrentPosition: mockGetPos },
      configurable: true,
    });

    const { result } = renderHook(() => useGeolocation({ timeoutMs: 10000 }));
    expect(mockGetPos).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
      }),
    );
    expect(result.current.status).toBe('denied');
    expect(result.current.error).toMatch(/why|respond|Enable Location/i);

    act(() => result.current.retry());
    expect(result.current.status).toBe('timeout');
    expect(result.current.error).toMatch(/10 seconds/i);

    act(() => result.current.retry());
    expect(result.current.status).toBe('ready');
    expect(result.current.coords).toEqual({
      lat: 18.52,
      lng: 73.85,
      accuracy: 15,
    });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe('CrowdReportPage', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    useSession.setState({
      user: { ...userFixture, role: 'citizen' },
      tokens: { access_token: 'cit-tok', refresh_token: 'cit-ref' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    restoreEnv();
    useSession.setState({ user: null, tokens: null });
  });

  function stubDomCanvasAndImage() {
    URL.createObjectURL = vi.fn(() => 'blob:mock-preview-url');
    URL.revokeObjectURL = vi.fn();

    class MockImg {
      width = 2000;
      height = 1000;
      naturalWidth = 2000;
      naturalHeight = 1000;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_v: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal('Image', MockImg);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(
      (cb, type) => {
        cb(new Blob(['jpeg-data'], { type: type ?? 'image/jpeg' }));
      },
    );
  }

  it('downscales photo, submits multipart, renders zone result, drops image/URLs, and passes axe', async () => {
    stubGeolocationSuccess(18.5195, 73.8553, 11);
    stubDomCanvasAndImage();

    let capturedBody: BodyInit | null | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      capturedBody = init?.body;
      return new Response(
        JSON.stringify({
          data: { ...(crowdFixture as Report), count: 14, density_hint: 0.35 },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      );
    });

    const client = makeQueryClient();
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouterWrapper>
          <CrowdReportPage />
        </MemoryRouterWrapper>
      </QueryClientProvider>,
    );

    expect(
      screen.getByText(/Location ready · accuracy ±11 m/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Your photo is not stored; the count, location/i),
    ).toBeInTheDocument();

    const fileInput = screen.getByLabelText(/Crowd photo/i) as HTMLInputElement;
    expect(fileInput).toHaveAttribute('capture', 'environment');

    const rawFile = new File(['raw'], 'crowd.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [rawFile] } });

    await screen.findByAltText('Selected crowd photo preview');
    await userEvent.type(
      screen.getByLabelText(/Optional note/i),
      'Dense queue',
    );

    expect((await axe(container)).violations).toEqual([]);

    await userEvent.click(
      screen.getByRole('button', { name: /Submit crowd report/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/14 people counted, about 0\.3 per m² in Main Gate/i),
      ).toBeInTheDocument();
    });

    expect(capturedBody).toBeInstanceOf(FormData);
    const fd = capturedBody as FormData;
    expect(fd.get('lat')).toBe('18.5195');
    expect(fd.get('lng')).toBe('73.8553');
    expect(fd.get('note')).toBe('Dense queue');
    expect((fd.get('image') as File).type).toBe('image/jpeg');

    expect(URL.revokeObjectURL).toHaveBeenCalled();
    expect(screen.queryByAltText('Selected crowd photo preview')).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it.each([
    [
      413,
      'PAYLOAD_TOO_LARGE',
      'Too large',
      undefined,
      /exceeds the 5 MB limit/i,
      undefined,
    ],
    [
      422,
      'VALIDATION_ERROR',
      'Validation failed.',
      undefined,
      /Image must be JPEG or PNG/i,
      { image: ['Image must be JPEG or PNG.'] },
    ],
    [
      429,
      'RATE_LIMITED',
      'Too many requests.',
      '42',
      /try again in 42 seconds/i,
      undefined,
    ],
    [
      503,
      'DETECTOR_UNAVAILABLE',
      'Detector busy',
      undefined,
      /crowd counter is temporarily busy or unavailable/i,
      undefined,
    ],
  ] as const)(
    'maps HTTP %s (%s) to specific error feedback',
    async (
      status,
      code,
      message,
      retryAfter,
      expectedPattern,
      details?: Readonly<Record<string, readonly string[]>>,
    ) => {
      stubGeolocationSuccess();
      stubDomCanvasAndImage();

      vi.spyOn(globalThis, 'fetch').mockImplementation(
        async () =>
          new Response(
            JSON.stringify({
              error: { code, message, ...(details ? { details } : {}) },
            }),
            {
              status,
              headers: {
                'Content-Type': 'application/json',
                ...(retryAfter ? { 'Retry-After': retryAfter } : {}),
              },
            },
          ),
      );

      const client = makeQueryClient();
      render(
        <QueryClientProvider client={client}>
          <MemoryRouterWrapper>
            <CrowdReportPage />
          </MemoryRouterWrapper>
        </QueryClientProvider>,
      );

      fireEvent.change(screen.getByLabelText(/Crowd photo/i), {
        target: {
          files: [new File(['x'], 'c.jpg', { type: 'image/jpeg' })],
        },
      });
      await screen.findByAltText('Selected crowd photo preview');
      await userEvent.click(
        screen.getByRole('button', { name: /Submit crowd report/i }),
      );

      expect(await screen.findByText(expectedPattern)).toBeInTheDocument();
    },
  );
});

function MemoryRouterWrapper({ children }: { children: React.ReactNode }) {
  const router = createMemoryRouter(
    [{ path: '*', element: <main>{children}</main> }],
    { initialEntries: ['/'] },
  );
  return <RouterProvider router={router} />;
}

describe('SosReportPage & MyReportsPage', () => {
  beforeEach(() => {
    toastMock.mockClear();
    useSession.setState({
      user: { ...userFixture, id: 4, role: 'citizen' },
      tokens: { access_token: 'cit-tok', refresh_token: 'cit-ref' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    restoreEnv();
    useSession.setState({ user: null, tokens: null });
  });

  it('requires confirmation before sending SOS, shows reference id + 112 notice, and passes axe', async () => {
    stubGeolocationSuccess(18.5195, 73.8553, 8);
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            data: { ...(sosFixture as Report), id: 99 },
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        ),
    );

    const client = makeQueryClient();
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouterWrapper>
          <SosReportPage />
        </MemoryRouterWrapper>
      </QueryClientProvider>,
    );

    expect(screen.getByRole('note')).toHaveTextContent(
      /In immediate danger, call 112 - this app is not a replacement for emergency services/i,
    );
    expect((await axe(container)).violations).toEqual([]);

    await userEvent.click(screen.getByRole('button', { name: /Crush risk/i }));
    await userEvent.click(screen.getByRole('button', { name: /Send SOS/i }));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(
      screen.getByRole('heading', { name: /Confirm SOS request/i }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole('button', { name: /Confirm & send SOS/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/SOS report sent · Reference #99/i),
      ).toBeInTheDocument();
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('renders empty state links on /my-reports and updates status chips live from report:updated', async () => {
    const initialMine: Report = {
      ...(crowdFixture as Report),
      id: 77,
      status: 'PENDING',
      created_by: { id: 4, name: userFixture.name },
    };

    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: [],
            pagination: { total: 0, page: 1, limit: 20, total_pages: 0 },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: [initialMine],
            pagination: { total: 1, page: 1, limit: 20, total_pages: 1 },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );

    const client = makeQueryClient();
    const first = render(
      <QueryClientProvider client={client}>
        <MemoryRouterWrapper>
          <MyReportsPage />
        </MemoryRouterWrapper>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/No reports sent yet/i)).toBeInTheDocument();
    expect(
      screen.getAllByRole('link', { name: /Report.*crowd/i })[0],
    ).toHaveAttribute('href', '/report/crowd');
    expect(
      screen.getAllByRole('link', { name: /Send SOS/i })[0],
    ).toHaveAttribute('href', '/report/sos');
    first.unmount();

    appQueryClient.clear();
    appQueryClient.setQueryData(['config'], {
      target_fps: 3,
      frame_width: 640,
      jpeg_quality: 0.7,
      stale_after_s: 15,
      vapid_public_key: null,
      app_version: '0.1.0',
      contract_version: '1.1.0',
    });
    render(
      <QueryClientProvider client={appQueryClient}>
        <RealtimeProvider>
          <MemoryRouterWrapper>
            <MyReportsPage />
          </MemoryRouterWrapper>
        </RealtimeProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Pending')).toBeInTheDocument();

    act(() => {
      for (const listener of socketMock.socket.listeners('report:updated')) {
        listener({
          ...initialMine,
          status: 'VERIFIED',
          review_note: 'Stewards dispatched',
          reviewed_at: '2026-11-28T10:00:00Z',
          reviewed_by: { id: 2, name: 'Inspector Asha' },
        });
      }
    });

    await waitFor(() => {
      expect(screen.getByText('Verified')).toBeInTheDocument();
      expect(screen.getByText(/Stewards dispatched/i)).toBeInTheDocument();
    });
    expect(toastMock).toHaveBeenCalledWith('Crowd report #77 verified');
    expect(fetchSpy).toHaveBeenCalled();
  });
});

describe('ReportReviewPage (/police/reports)', () => {
  beforeEach(() => {
    toastMock.mockClear();
    toastMock.error.mockClear();
    useSession.setState({
      user: { ...userFixture, id: 2, name: 'Inspector Asha', role: 'police' },
      tokens: { access_token: 'pol-tok', refresh_token: 'pol-ref' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useSession.setState({ user: null, tokens: null });
  });

  it('orders pending reports first, highlights & scrolls to ?focus=<id>, optimistically updates, rolls back on 409, and passes axe', async () => {
    const reports = reportsListFixture.data as Report[];
    const reviewedFirst: Report = {
      ...reports[1]!,
      id: 40,
      status: 'VERIFIED',
      created_at: '2026-11-28T12:00:00Z',
    };
    const pendingOlder: Report = {
      ...reports[1]!,
      id: 46,
      status: 'PENDING',
      created_at: '2026-11-24T10:15:30Z',
    };
    const pendingSos: Report = {
      ...reports[0]!,
      id: 45,
      kind: 'SOS',
      status: 'PENDING',
      created_at: '2026-11-24T10:16:00Z',
    };

    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy;

    let serverReports: Report[] = [reviewedFirst, pendingOlder, pendingSos];
    let rejectReview = true;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/zones')) {
        return new Response(JSON.stringify(zonesFixture), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('/reports/46') && init?.method === 'PATCH') {
        if (rejectReview) {
          return new Response(
            JSON.stringify({
              error: {
                code: 'INVALID_TRANSITION',
                message: 'Already reviewed',
              },
            }),
            { status: 409, headers: { 'Content-Type': 'application/json' } },
          );
        }
        const updated: Report = {
          ...pendingOlder,
          status: 'DISMISSED',
          reviewed_at: '2026-11-28T14:35:00Z',
        };
        serverReports = serverReports.map((r) => (r.id === 46 ? updated : r));
        return new Response(JSON.stringify({ data: updated }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(
        JSON.stringify({
          data: serverReports,
          pagination: {
            total: serverReports.length,
            page: 1,
            limit: 20,
            total_pages: 1,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });

    const client = makeQueryClient();
    const router = createMemoryRouter(
      [
        {
          path: '/police/reports',
          element: (
            <main>
              <ReportReviewPage />
            </main>
          ),
        },
      ],
      { initialEntries: ['/police/reports?focus=46'] },
    );

    const { container } = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    const listItems = await screen.findAllByRole('listitem');
    expect(listItems[0]).toHaveAttribute('data-report-id', '45');
    expect(listItems[1]).toHaveAttribute('data-report-id', '46');
    expect(listItems[2]).toHaveAttribute('data-report-id', '40');
    expect(listItems[1]).toHaveAttribute('data-focused', 'true');
    expect(scrollSpy).toHaveBeenCalled();

    expect(screen.getByText(/SOS · Crush risk/i)).toBeVisible();
    expect(screen.getByTestId('pin-map-stub')).toHaveTextContent('Pin #46');
    expect((await axe(container)).violations).toEqual([]);

    const focusedCard = listItems[1]!;
    await userEvent.click(
      within(focusedCard).getByRole('button', { name: 'Verify' }),
    );
    await userEvent.type(
      screen.getByLabelText(/Optional review note/i),
      'Verified by patrol',
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Confirm verify/i }),
    );

    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith(
        'Someone already reviewed this report.',
      );
    });
    // Rolled back to PENDING after 409 conflict.
    expect(within(listItems[1]!).getByText('Pending')).toBeInTheDocument();

    // Now test successful dismiss.
    rejectReview = false;
    await userEvent.click(
      within(screen.getAllByRole('listitem')[1]!).getByRole('button', {
        name: 'Dismiss',
      }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Confirm dismiss/i }),
    );
    await waitFor(() => {
      expect(
        within(container.querySelector('[data-report-id="46"]')!).getByText(
          'Dismissed',
        ),
      ).toBeInTheDocument();
    });
  });
});
