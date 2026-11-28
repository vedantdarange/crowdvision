import { createBrowserRouter, type RouteObject } from 'react-router';
import { PublicLayout } from './layouts/PublicLayout';
import { PoliceLayout } from './layouts/PoliceLayout';
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

function page(
  title: string,
  phase: string,
): Pick<RouteObject, 'handle' | 'HydrateFallback'> {
  return {
    handle: { title, phase },
    HydrateFallback: RouteLoading,
  };
}
export const routes: RouteObject[] = [
  {
    element: <PublicLayout />,
    children: [
      {
        path: '/',
        ...page('Live map', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).LiveMap,
        }),
      },
      {
        path: '/zones/:id',
        ...page('Zone detail', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).ZoneDetail,
        }),
      },
      {
        path: '/advisories',
        ...page('Advisories', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).Advisories,
        }),
      },
      {
        path: '/help',
        ...page('Help', 'F2'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PublicPages')).Help,
        }),
      },
      {
        path: '/report/crowd',
        ...page('Crowd report', 'F6'),
        handle: { role: 'citizen', title: 'Crowd report', phase: 'F6' },
        lazy: async () => {
          const { CrowdReportPage } = await import('@/features/reports');
          return {
            Component: () => (
              <RequireRole role="citizen">
                <CrowdReportPage />
              </RequireRole>
            ),
          };
        },
      },
      {
        path: '/report/sos',
        ...page('Send SOS', 'F6'),
        handle: { role: 'citizen', title: 'Send SOS', phase: 'F6' },
        lazy: async () => {
          const { SosReportPage } = await import('@/features/reports');
          return {
            Component: () => (
              <RequireRole role="citizen">
                <SosReportPage />
              </RequireRole>
            ),
          };
        },
      },
      {
        path: '/my-reports',
        ...page('My reports', 'F6'),
        handle: { role: 'citizen', title: 'My reports', phase: 'F6' },
        lazy: async () => {
          const { MyReportsPage } = await import('@/features/reports');
          return {
            Component: () => (
              <RequireRole role="citizen">
                <MyReportsPage />
              </RequireRole>
            ),
          };
        },
      },
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
    element: <PoliceLayout />,
    children: [
      {
        path: '/police',
        ...page('Operations dashboard', 'F3'),
        lazy: async () => ({
          Component: (await import('@/features/police/Dashboard')).Dashboard,
        }),
      },
      {
        path: '/police/alerts',
        ...page('Alert queue', 'F3'),
        lazy: async () => ({
          Component: (await import('@/features/police/Queue')).Queue,
        }),
      },
      {
        path: '/police/alerts/:id',
        ...page('Alert detail', 'F3'),
        lazy: async () => ({
          Component: (await import('@/features/police/Detail')).Detail,
        }),
      },
      {
        path: '/police/zones/:id',
        ...page('Zone live view', 'F4'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PoliceZoneDetail'))
            .PoliceZoneDetail,
        }),
      },
      {
        path: '/police/monitor',
        ...page('Camera control', 'F4'),
        lazy: async () => ({
          Component: (await import('@/features/monitor/MonitorPage'))
            .MonitorPage,
        }),
      },
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
      {
        path: '/police/reports',
        ...page('Report review', 'F6'),
        lazy: async () => ({
          Component: (await import('@/features/reports')).ReportReviewPage,
        }),
      },
      {
        path: '/police/advisories',
        ...page('Broadcast advisory', 'F6'),
        lazy: async () => ({
          Component: (await import('@/features/advisories'))
            .PoliceAdvisoriesPage,
        }),
      },
      {
        handle: { role: 'admin' },
        children: [
          {
            path: '/admin/zones',
            ...page('Zones', 'F7'),
            lazy: async () => ({
              Component: (await import('@/features/admin')).AdminZonesPage,
            }),
          },
          {
            path: '/admin/zones/new',
            ...page('New zone', 'F7'),
            lazy: async () => ({
              Component: (await import('@/features/admin/ZoneEditor'))
                .ZoneEditorPage,
            }),
          },
          {
            path: '/admin/zones/:id/edit',
            ...page('Edit zone', 'F7'),
            lazy: async () => ({
              Component: (await import('@/features/admin/ZoneEditor'))
                .ZoneEditorPage,
            }),
          },
          {
            path: '/admin/sources',
            ...page('Sources', 'F7'),
            lazy: async () => ({
              Component: (await import('@/features/admin')).AdminSourcesPage,
            }),
          },
          {
            path: '/admin/users',
            ...page('Users', 'F7'),
            lazy: () => import('@/features/admin/Users'),
          },
          {
            path: '/admin/settings',
            ...page('Settings', 'F7'),
            lazy: () => import('@/features/admin/Settings'),
          },
          {
            path: '/admin/analytics',
            ...page('Analytics', 'F7'),
            lazy: () => import('@/features/admin/Analytics'),
          },
          {
            path: '/admin/audit',
            ...page('Audit log', 'F7'),
            lazy: () => import('@/features/admin/Audit'),
          },
        ],
      },
    ],
  },
];
export const router = createBrowserRouter(routes);
