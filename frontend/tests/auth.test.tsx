import { afterEach, expect, it, vi } from 'vitest';
import { render } from './renderPublic';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { axe } from 'vitest-axe';
import { routes } from '@/app/router';
import { useSession } from '@/features/auth';
import type { Role } from '@contract/types';
import fixture from '../../contract/examples/user.json';
afterEach(() => {
  useSession.getState().logout();
  vi.unstubAllGlobals();
});
function mount(path: string, role: Role | null = null) {
  if (role) useSession.setState({ user: { ...fixture, role } });
  if (path === '/police/alerts')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        Response.json(
          url.includes('/alerts')
            ? {
                data: [],
                pagination: { total: 0, page: 1, limit: 10, total_pages: 0 },
              }
            : { data: [] },
        ),
      ),
    );
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<RouterProvider router={router} />);
  return { ...view, router };
}
const audiences = [null, 'citizen', 'police', 'admin'] as const;
const paths = [
  ['/help', 'Help', 0],
  ['/my-reports', 'My reports', 1],
  ['/police/alerts', 'Alert queue', 2],
  ['/admin/zones', 'Zones', 3],
] as const;
for (const [index, role] of audiences.entries()) {
  it.each(paths)(
    'checks ' + (role ?? 'anonymous') + ' access to %s',
    async (path, title, min) => {
      const { router } = mount(path, role);
      const heading = index >= min ? title : role ? 'Forbidden' : 'Sign in';
      expect(
        await screen.findByRole('heading', { name: heading, level: 1 }),
      ).toBeVisible();
      if (!role && min)
        expect(router.state.location.search).toBe(
          '?next=' + encodeURIComponent(path),
        );
    },
  );
  it('shows allowed navigation for ' + (role ?? 'anonymous'), async () => {
    mount('/', role);
    const sidebar = within(await screen.findByRole('complementary'));
    expect(!!sidebar.queryByRole('link', { name: 'Police workspace' })).toBe(
      index >= 2,
    );
    expect(!!sidebar.queryByRole('link', { name: 'Admin workspace' })).toBe(
      index === 3,
    );
    expect(!!sidebar.queryByRole('link', { name: 'My reports' })).toBe(
      index > 0,
    );
    const report = sidebar.getByRole('link', { name: 'Report a crowd' });
    expect(report).toHaveAttribute(
      'href',
      role ? '/report/crowd' : '/login?next=%2Freport%2Fcrowd',
    );
    expect(
      within(
        screen.getByRole('navigation', { name: 'Mobile navigation' }),
      ).getByRole('link', { name: 'Report a crowd' }),
    ).toHaveAttribute('href', report.getAttribute('href'));
  });
}
it.each(['/login', '/register'])('passes axe on %s', async (path) => {
  const { container } = mount(path);
  await screen.findByLabelText('Email');
  expect(
    (await axe(container, { rules: { 'color-contrast': { enabled: false } } }))
      .violations,
  ).toEqual([]);
});
it.each([
  [401, 'Email or password is incorrect.'],
  [403, 'Your account is disabled. Contact an administrator.'],
  [409, 'This email is already registered.'],
  [429, 'Too many attempts. Please try again later.'],
  [422, 'Use a valid email.'],
] as const)('maps server response %i', async (status, message) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Failed',
            details: { email: ['Use a valid email.'] },
          },
        },
        { status },
      ),
    ),
  );
  mount('/login');
  await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com');
  await userEvent.type(screen.getByLabelText('Password'), '12345678');
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  if (status === 422)
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription(message);
});
