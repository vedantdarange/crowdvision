import { EventEmitter } from 'node:events';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { Advisory } from '@contract/types';
import advisoriesFixture from '../../contract/examples/advisories.json';
import liveFixture from '../../contract/examples/zones_live.json';
import userFixture from '../../contract/examples/user.json';
import zonesFixture from '../../contract/examples/zones.json';
import { PoliceAdvisoriesPage } from '@/features/advisories';
import { useSession } from '@/features/auth';
import { RealtimeProvider } from '@/features/realtime/RealtimeProvider';
import { LiveMap } from '@/features/zones/PublicPages';
import { queryClient as appQueryClient } from '@/lib/queryClient';

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

vi.mock('@/features/zones/ZoneMap', () => ({ default: () => null }));

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
  }),
);
vi.mock('sonner', () => ({ toast: toastMock }));

function makeClient() {
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

describe('PoliceAdvisoriesPage & citizen live advisory propagation', () => {
  beforeEach(() => {
    toastMock.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
    useSession.setState({
      user: { ...userFixture, id: 2, name: 'Inspector Asha', role: 'police' },
      tokens: { access_token: 'pol-tok', refresh_token: 'pol-ref' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    appQueryClient.clear();
    useSession.setState({ user: null, tokens: null });
  });

  it('validates title/body/future expiry, broadcasts POST /advisories, retracts via confirm dialog, and passes axe', async () => {
    const initial = advisoriesFixture.data as Advisory[];
    let serverAdvisories: Advisory[] = [...initial];
    let createdPayload: Record<string, unknown> | undefined;

    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes('/zones')) {
          return new Response(JSON.stringify(zonesFixture), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/advisories') && init?.method === 'POST') {
          createdPayload = JSON.parse(String(init.body)) as Record<
            string,
            unknown
          >;
          const created: Advisory = {
            ...initial[0]!,
            id: 55,
            title: String(createdPayload.title),
            body: String(createdPayload.body),
            severity: createdPayload.severity as Advisory['severity'],
            zone_id: (createdPayload.zone_id as number | null) ?? null,
            zone_name: createdPayload.zone_id ? 'Main Gate' : null,
            created_at: '2026-11-28T14:30:00Z',
          };
          serverAdvisories = [created, ...serverAdvisories];
          return new Response(JSON.stringify({ data: created }), {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/advisories/55') && init?.method === 'DELETE') {
          serverAdvisories = serverAdvisories.filter((a) => a.id !== 55);
          return new Response(null, { status: 204 });
        }
        return new Response(JSON.stringify({ data: serverAdvisories }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      });

    const client = makeClient();
    const router = createMemoryRouter(
      [
        {
          path: '/police/advisories',
          element: (
            <main>
              <PoliceAdvisoriesPage />
            </main>
          ),
        },
      ],
      { initialEntries: ['/police/advisories'] },
    );

    const { container } = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await screen.findByRole('heading', { name: 'Broadcast advisory' });
    await screen.findByRole('button', { name: /Broadcast advisory/i });
    expect((await axe(container)).violations).toEqual([]);

    // Submitting blank triggers RHF/Zod validation.
    await userEvent.click(
      screen.getByRole('button', { name: /Broadcast advisory/i }),
    );
    expect(
      await screen.findByText('Enter an advisory title.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Enter the advisory message.')).toBeInTheDocument();

    // Enter past expiry date -> client validation rejects.
    await userEvent.type(screen.getByLabelText('Title'), 'Clear East Exit');
    await userEvent.type(
      screen.getByLabelText('Message'),
      'Use secondary stairwell toward parking.',
    );
    await userEvent.type(
      screen.getByLabelText(/Optional expiry/i),
      '2020-01-01T10:00',
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Broadcast advisory/i }),
    );
    expect(
      await screen.findByText('Expiry time must be in the future.'),
    ).toBeInTheDocument();

    // Clear expiry and select a zone + URGENT severity -> submits cleanly.
    fireEvent.change(screen.getByLabelText(/Optional expiry/i), {
      target: { value: '' },
    });
    await userEvent.selectOptions(screen.getByLabelText('Severity'), 'URGENT');
    await userEvent.selectOptions(screen.getByLabelText('Scope'), '1');
    await userEvent.click(
      screen.getByRole('button', { name: /Broadcast advisory/i }),
    );

    await waitFor(() => {
      expect(screen.getByText('Clear East Exit')).toBeInTheDocument();
    });
    expect(createdPayload).toEqual({
      title: 'Clear East Exit',
      body: 'Use secondary stairwell toward parking.',
      severity: 'URGENT',
      zone_id: 1,
    });
    expect(toastMock.success).toHaveBeenCalledWith('Advisory broadcast.');

    // Retract via confirm dialog.
    const advisoryCard = screen.getByText('Clear East Exit').closest('li')!;
    await userEvent.click(
      within(advisoryCard).getByRole('button', { name: /Retract/i }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Confirm retract/i }),
    );

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/advisories/55',
        expect.objectContaining({ method: 'DELETE' }),
      );
      expect(screen.queryByText('Clear East Exit')).toBeNull();
    });
  });

  it('propagates live advisory:new and advisory:retracted to the public map screen with citizen toast', async () => {
    useSession.setState({ user: null, tokens: null });
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
    appQueryClient.setQueryData(['zones', 'live'], liveFixture.data);
    appQueryClient.setQueryData(['advisories', 'all'], []);

    const router = createMemoryRouter(
      [
        {
          path: '/',
          element: (
            <main>
              <LiveMap />
            </main>
          ),
        },
      ],
      { initialEntries: ['/'] },
    );

    render(
      <QueryClientProvider client={appQueryClient}>
        <RealtimeProvider>
          <RouterProvider router={router} />
        </RealtimeProvider>
      </QueryClientProvider>,
    );

    expect(screen.queryByLabelText('Active advisories')).toBeNull();

    const incoming: Advisory = {
      ...(advisoriesFixture.data[0] as Advisory),
      id: 88,
      severity: 'URGENT',
      title: 'Stage Gate congested — use Gate B',
      created_at: '2026-11-28T14:35:00Z',
    };

    act(() => {
      for (const listener of socketMock.socket.listeners('advisory:new')) {
        listener(incoming);
      }
    });

    expect(
      await screen.findByText('Stage Gate congested — use Gate B'),
    ).toBeVisible();
    expect(toastMock).toHaveBeenCalledWith('Stage Gate congested — use Gate B');

    act(() => {
      for (const listener of socketMock.socket.listeners(
        'advisory:retracted',
      )) {
        listener({ id: 88 });
      }
    });

    await waitFor(() => {
      expect(
        screen.queryByText('Stage Gate congested — use Gate B'),
      ).toBeNull();
    });
  });
});
