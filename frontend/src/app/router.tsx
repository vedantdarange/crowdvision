import { createBrowserRouter, type RouteObject } from 'react-router';
import { PublicLayout } from './layouts/PublicLayout';
import { PoliceLayout } from './layouts/PoliceLayout';
import { AdminLayout } from './layouts/AdminLayout';
import { AuthLayout } from './layouts/AuthLayout';
import { AccessPage } from '@/features/auth/AccessPage';
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
      {
        ...page('/', 'Live map', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).LiveMap,
        }),
      },
      {
        ...page('/zones/:id', 'Zone detail', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).ZoneDetail,
        }),
      },
      {
        ...page('/advisories', 'Advisories', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).Advisories,
        }),
      },
      {
        ...page('/help', 'Help', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).Help,
        }),
      },
      ...['/report/crowd', '/report/sos', '/my-reports'].map((path, i) => ({
        ...page(path, ['Crowd report', 'Send SOS', 'My reports'][i]!, 'F6'),
        handle: {
          role: 'citizen',
          title: ['Crowd report', 'Send SOS', 'My reports'][i],
          phase: 'F6',
        },
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
      { path: '/forbidden', element: <AccessPage /> },
      { path: '*', element: <AccessPage missing /> },
    ],
  },
  {
    element: <AuthLayout />,
    children: [
      {
        path: '/login',
        handle: { title: 'Sign in' },
        HydrateFallback: RouteLoading,
        lazy: async () => ({
          Component: (await import('@/features/auth/AuthForm')).LoginForm,
        }),
      },
      {
        path: '/register',
        handle: { title: 'Create citizen account' },
        HydrateFallback: RouteLoading,
        lazy: async () => ({
          Component: (await import('@/features/auth/AuthForm')).RegisterForm,
        }),
      },
    ],
  },
  {
    handle: { role: 'police' },
    element: (
      <RequireRole role="police">
        <PoliceLayout />
      </RequireRole>
    ),
    children: [
      {
        ...page('/police', 'Operations dashboard', 'F3'),
        lazy: async () => ({
          Component: (await import('@/features/police/Dashboard')).Dashboard,
        }),
      },
      {
        ...page('/police/alerts', 'Alert queue', 'F3'),
        lazy: async () => ({
          Component: (await import('@/features/police/Queue')).Queue,
        }),
      },
      {
        ...page('/police/alerts/:id', 'Alert detail', 'F3'),
        lazy: async () => ({
          Component: (await import('@/features/police/Detail')).Detail,
        }),
      },
      page('/police/zones/:id', 'Zone live view', 'F4'),
      page('/police/monitor', 'Camera control', 'F4'),
      ...(import.meta.env.DEV
        ? [
            {
              path: '/police/monitor-dev',
              handle: { title: 'Monitor dev harness', phase: 'F4' },
              HydrateFallback: RouteLoading,
              lazy: async () => ({
                Component: (await import('@/features/monitor/MonitorDev'))
                  .MonitorDev,
              }),
            },
          ]
        : []),
      page('/police/reports', 'Report review', 'F6'),
      page('/police/advisories', 'Broadcast advisory', 'F6'),
    ],
  },
  {
    handle: { role: 'admin' },
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
