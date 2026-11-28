import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { Component as Users } from '@/features/admin/Users';
import { Component as Settings } from '@/features/admin/Settings';
import { Component as Analytics, duration } from '@/features/admin/Analytics';
import { Component as Audit } from '@/features/admin/Audit';
import { downloadAlerts } from '@/features/admin/managementApi';
import { useSession } from '@/features/auth';
import users from '../../contract/examples/users_list.json';
import settings from '../../contract/examples/settings.json';
import analytics from '../../contract/examples/analytics_summary.json';
import audit from '../../contract/examples/audit_logs_list.json';

const emptySummary = {
  ...analytics,
  alerts_by_zone: [],
  peak_hours: [],
  reports_by_status: { PENDING: 0, VERIFIED: 0, DISMISSED: 0 },
};
const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  useSession.setState({
    user: { ...users.data[0]!, role: 'admin' },
    tokens: { access_token: 'access', refresh_token: 'refresh' },
  });
  fetchMock.mockReset().mockImplementation(async (url, options) => {
    const path = String(url).split('?')[0] ?? '';
    if (path.endsWith('/users')) return Response.json(users);
    if (path.endsWith('/settings'))
      return Response.json({
        data: { ...settings, ...JSON.parse(String(options?.body ?? '{}')) },
      });
    if (path.endsWith('/summary')) return Response.json({ data: emptySummary });
    if (path.endsWith('/audit-logs')) return Response.json(audit);
    throw Error(path);
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useSession.setState({ user: null, tokens: null });
});
function mount(Page: typeof Users) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <main>
        <Page />
      </main>
    </QueryClientProvider>,
  );
}
it('protects the signed-in administrator and reports a server conflict', async () => {
  mount(Users);
  expect(await screen.findByLabelText('Role for Admin Meera')).toBeDisabled();
  expect(
    screen.getByRole('button', { name: 'Disable Admin Meera' }),
  ).toBeDisabled();
  fetchMock.mockResolvedValueOnce(
    Response.json(
      {
        error: {
          code: 'CONFLICT',
          message: 'This account cannot be disabled.',
        },
      },
      { status: 409 },
    ),
  );
  await userEvent.click(
    screen.getByRole('button', { name: 'Disable Inspector Arjun' }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'This account cannot be disabled.',
  );
});
it('keeps a duplicate account form open with an email-specific error', async () => {
  mount(Users);
  await screen.findByLabelText('Role for Admin Meera');
  fireEvent.change(screen.getByLabelText('Name', { exact: true }), {
    target: { value: 'Officer' },
  });
  fireEvent.change(screen.getByLabelText('Email'), {
    target: { value: 'officer@example.org' },
  });
  fireEvent.change(screen.getByLabelText(/Temporary password/), {
    target: { value: 'local-demo-123' },
  });
  fetchMock.mockResolvedValueOnce(
    Response.json(
      { error: { code: 'CONFLICT', message: 'Email is already registered.' } },
      { status: 409 },
    ),
  );
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
  expect(
    await screen.findByText('An account already uses this email.'),
  ).toBeVisible();
  expect(screen.getByLabelText('Name', { exact: true })).toHaveValue('Officer');
});
it('patches only changed numeric settings, and saves help separately', async () => {
  mount(Settings);
  const delay = await screen.findByLabelText('Re-raise delay (s)');
  expect(delay).toHaveAttribute('min', '10');
  expect(delay).toHaveAttribute('max', '600');
  fireEvent.change(delay, { target: { value: '70' } });
  await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
  const bodies = () =>
    fetchMock.mock.calls
      .filter(([, o]) => o?.method === 'PATCH')
      .map(([, o]) => JSON.parse(String(o?.body)));
  await waitFor(() => expect(bodies()).toEqual([{ reraise_after_s: 70 }]));
  await userEvent.click(
    screen.getByRole('button', { name: 'Add emergency number' }),
  );
  fireEvent.change(screen.getAllByLabelText('Label').at(-1)!, {
    target: { value: 'Desk' },
  });
  fireEvent.change(screen.getAllByLabelText('Phone number').at(-1)!, {
    target: { value: '123' },
  });
  await userEvent.click(
    screen.getByRole('button', { name: 'Save help information' }),
  );
  await waitFor(() =>
    expect(bodies()[1]).toEqual({
      help_info: {
        ...settings.help_info,
        emergency_numbers: [
          ...settings.help_info.emergency_numbers,
          { label: 'Desk', number: '123' },
        ],
      },
    }),
  );
});
it.each([
  [null, 'No data'],
  [0, '0:00'],
  [8, '0:08'],
  [59.8, '1:00'],
  [121, '2:01'],
] as const)('formats %s seconds', (value, expected) =>
  expect(duration(value)).toBe(expected),
);
it('explains empty analytics sections', async () => {
  const immediate = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (...args) => {
    await new Promise((resolve) => setTimeout(resolve, 20));
    return immediate(...args);
  });
  mount(Analytics);
  expect(await screen.findByText(/No alerts in this range/)).toBeVisible();
  expect(screen.getByText(/No reports in this range/)).toBeVisible();
  expect(screen.getByText(/No density readings/)).toBeVisible();
  expect(screen.getAllByText('No data')).toHaveLength(2);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it('downloads the selected CSV as a Blob using the session bearer', async () => {
  fetchMock.mockResolvedValueOnce(
    new Response('id,zone', { headers: { 'Content-Type': 'text/csv' } }),
  );
  const make = vi.fn(() => 'blob:csv');
  const revoke = vi.fn();
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = make;
      static revokeObjectURL = revoke;
    },
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe('alerts.csv');
      expect(this.href).toBe('blob:csv');
    });
  await downloadAlerts({ from: analytics.from, to: analytics.to });
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(String(url)).toContain('/analytics/export/alerts.csv?from=');
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer access');
  expect(make.mock.calls[0]).toEqual([
    expect.objectContaining({ type: 'text/csv' }),
  ]);
  expect(click).toHaveBeenCalledOnce();
});
it.each([
  [Users, 'Disable Admin Meera'],
  [Settings, 'Save settings'],
  [Analytics, 'Download alerts CSV'],
  [Audit, 'View details'],
] as const)(
  'checks the populated management page for accessibility (%s)',
  async (Page, control) => {
    const { container } = mount(Page);
    if (Page === Audit)
      await screen.findByRole('cell', { name: 'ALERT_RESOLVED' });
    else await screen.findByRole('button', { name: control });
    const result = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  },
);
