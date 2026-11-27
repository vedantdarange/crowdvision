import { createBrowserRouter, type RouteObject } from 'react-router';
import { PublicLayout } from './layouts/PublicLayout';
import { PoliceLayout } from './layouts/PoliceLayout';
import { AdminLayout } from './layouts/AdminLayout';
import { AuthLayout } from './layouts/AuthLayout';
import { RequireRole } from '@/features/auth';
import { Skeleton } from '@/components/ui/skeleton';

function RouteLoading() {
  return (
    <div role="status" className="space-y-4 p-6">
      <span className="sr-only">Loading page</span>
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

function page(path: string, title: string, phase: string): RouteObject {
  return {
    path,
    handle: { title, phase },
    HydrateFallback: RouteLoading,
    lazy: () => import('./pages/PlaceholderPage'),
  };
}
export const routes: RouteObject[] = [
  {
    element: <PublicLayout />,
    children: [
      page('/', 'Live map', 'F2'),
      page('/zones/:id', 'Zone detail', 'F2'),
      page('/advisories', 'Advisories', 'F2'),
      page('/help', 'Help', 'F2'),
      ...['/report/crowd', '/report/sos', '/my-reports'].map((path, i) => ({
        ...page(path, ['Crowd report', 'Send SOS', 'My reports'][i]!, 'F6'),
        lazy: async () => {
          const m = await import('./pages/PlaceholderPage');
          return {
            Component: () => (
              <RequireRole role="citizen">
                <m.Component />
              </RequireRole>
            ),
          };
        },
      })),
      page('/forbidden', 'Access unavailable', 'F1'),
      page('*', 'Page not found', 'F1'),
    ],
  },
  {
    element: <AuthLayout />,
    children: [
      page('/login', 'Sign in', 'F1'),
      page('/register', 'Create citizen account', 'F1'),
    ],
  },
  {
    element: (
      <RequireRole role="police">
        <PoliceLayout />
      </RequireRole>
    ),
    children: [
      page('/police', 'Operations dashboard', 'F3'),
      page('/police/alerts', 'Alert queue', 'F3'),
      page('/police/alerts/:id', 'Alert detail', 'F3'),
      page('/police/zones/:id', 'Zone live view', 'F4'),
      page('/police/monitor', 'Camera control', 'F4'),
      page('/police/reports', 'Report review', 'F6'),
      page('/police/advisories', 'Broadcast advisory', 'F6'),
    ],
  },
  {
    element: (
      <RequireRole role="admin">
        <AdminLayout />
      </RequireRole>
    ),
    children: [
      page('/admin/zones', 'Zones', 'F7'),
      page('/admin/zones/new', 'New zone', 'F7'),
      page('/admin/zones/:id/edit', 'Edit zone', 'F7'),
      page('/admin/sources', 'Sources', 'F7'),
      page('/admin/users', 'Users', 'F7'),
      page('/admin/settings', 'Settings', 'F7'),
      page('/admin/analytics', 'Analytics', 'F7'),
      page('/admin/audit', 'Audit log', 'F7'),
    ],
  },
];
export const router = createBrowserRouter(routes);
