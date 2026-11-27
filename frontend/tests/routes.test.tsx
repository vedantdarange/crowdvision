import { useSession } from '@/features/auth';
import seedUser from '../../contract/examples/user.json';
import { afterEach, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, matchRoutes } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { routes } from '@/app/router';
afterEach(() => useSession.getState().logout());
const pages = [
  '/',
  '/zones/1',
  '/advisories',
  '/help',
  '/login',
  '/register',
  '/report/crowd',
  '/report/sos',
  '/my-reports',
  '/police',
  '/police/alerts',
  '/police/alerts/12',
  '/police/zones/1',
  '/police/monitor',
  '/police/reports',
  '/police/advisories',
  '/admin/zones',
  '/admin/zones/new',
  '/admin/zones/1/edit',
  '/admin/sources',
  '/admin/users',
  '/admin/settings',
  '/admin/analytics',
  '/admin/audit',
];
it.each(pages)('has an lazy route for %s', (path) => {
  const match = matchRoutes(routes, path)?.at(-1);
  expect(match?.route.path).not.toBe('*');
  expect(match?.route.lazy).toBeTypeOf('function');
  expect(match?.route.handle).toHaveProperty('title');
});
it('renders the admin layout and lazy route with its administration navigation', async () => {
  useSession.setState({ user: { ...seedUser, role: 'admin' } });
  const router = createMemoryRouter(routes, {
    initialEntries: ['/admin/zones'],
  });
  render(<RouterProvider router={router} />);
  expect(await screen.findByRole('heading', { name: 'Zones' })).toBeVisible();
  expect(
    screen.getByRole('navigation', { name: 'Administration' }),
  ).toBeInTheDocument();
});
it('keeps sidebar destinations accessible when collapsed and restores the preference', async () => {
  localStorage.removeItem('cv-sidebar');
  const mount = () =>
    render(
      <RouterProvider
        router={createMemoryRouter(routes, { initialEntries: ['/'] })}
      />,
    );
  const first = mount();
  await userEvent.click(
    await screen.findByRole('button', { name: 'Collapse sidebar' }),
  );
  expect(
    screen.getByRole('button', { name: 'Expand sidebar' }),
  ).toHaveAttribute('aria-expanded', 'false');
  expect(
    screen.getAllByRole('link', { name: 'Help centre' })[0],
  ).toHaveAttribute('href', '/help');
  first.unmount();
  mount();
  await userEvent.click(
    await screen.findByRole('button', { name: 'Expand sidebar' }),
  );
  expect(
    screen.getByRole('button', { name: 'Collapse sidebar' }),
  ).toHaveAttribute('aria-expanded', 'true');
  localStorage.removeItem('cv-sidebar');
});
