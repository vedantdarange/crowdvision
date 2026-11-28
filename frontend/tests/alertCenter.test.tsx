import {
  render,
  screen,
  within,
  act,
  waitFor,
  fireEvent,
} from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { Alert, Report } from '@contract/types';
import fixture from '../../contract/examples/alert.json';
import sos from '../../contract/examples/report_sos.json';
import user from '../../contract/examples/user.json';
import { AlertCenter } from '@/features/alerts/AlertCenter';
import { updateAlert } from '@/features/police/data';
import { socket } from '@/lib/socket';
import { useSession } from '@/features/auth';
const toastSpy = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: toastSpy }));
const alert = fixture as Alert;
function mount(alerts: Alert[] = []) {
  const c = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  c.setQueryData(['alerts', 'banner'], alerts);
  c.setQueryData(['reports', 'banner'], []);
  useSession.setState({ user: { ...user, role: 'police' } });
  const view = render(
    <StrictMode>
      <QueryClientProvider client={c}>
        <MemoryRouter>
          <main>
            <AlertCenter />
          </main>
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
  return { ...view, c };
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useSession.setState({ user: null });
});
it('caps the stack by severity, exposes peak density, passes axe and follows alert status', async () => {
  const { c, container } = mount();
  act(() => {
    for (const id of [1, 2, 3, 4])
      updateAlert(
        c,
        {
          ...alert,
          id,
          zone_name: 'Zone ' + id,
          level: id === 4 ? 'CRITICAL' : 'WARNING',
        },
        false,
      );
  });
  expect(await screen.findByText('+1 more')).toBeVisible();
  const banners = screen.getAllByRole('alert');
  expect(banners).toHaveLength(3);
  expect(within(banners[0]!).getByText('Zone 4')).toBeVisible();
  expect(within(banners[0]!).getByText('Peak 0.2 people/m²')).toBeVisible();
  expect(screen.getByText('Alerts not armed - tap to enable')).toBeVisible();
  expect(
    (await axe(container, { rules: { 'color-contrast': { enabled: false } } }))
      .violations,
  ).toEqual([]);
  act(() => updateAlert(c, { ...alert, id: 4, status: 'ACKNOWLEDGED' }, false));
  await waitFor(() => expect(screen.queryByText('Zone 4')).toBeNull());
});
it('acknowledges optimistically before the POST finishes', async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetch = vi.fn().mockReturnValue(pending);
  vi.stubGlobal('fetch', fetch);
  mount([alert]);
  fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
  await waitFor(() => expect(screen.queryByText(alert.zone_name)).toBeNull());
  expect(String(fetch.mock.calls[0]?.[0])).toContain('/alerts/12/acknowledge');
  finish(Response.json({ data: { ...alert, status: 'ACKNOWLEDGED' } }));
});
it.each(['CRUSH_RISK', 'FIRE', 'MEDICAL', 'LOST_CHILD', 'OTHER'] as const)(
  'handles %s once and removes reviewed SOS',
  async (type) => {
    const { unmount, c } = mount();
    vi.spyOn(c, 'invalidateQueries').mockResolvedValue(undefined);
    toastSpy.mockClear();
    const r: Report = { ...(sos as Report), sos_type: type, zone_name: null };
    const send = (event: 'report:new' | 'report:updated', report: Report) =>
      act(() => {
        for (const fn of socket.listeners(event)) fn(report);
      });
    send('report:new', r);
    if (type === 'LOST_CHILD' || type === 'OTHER') {
      expect(toastSpy).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('alert')).toBeNull();
    } else {
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'location outside zones',
      );
      expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
        'href',
        '/police/reports?focus=' + r.id,
      );
      send('report:updated', { ...r, status: 'VERIFIED' });
      await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    }
    unmount();
    expect(socket.listeners('report:new')).toHaveLength(0);
    expect(socket.listeners('report:updated')).toHaveLength(0);
  },
);
