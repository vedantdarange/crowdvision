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
      {
        ...page('/report/crowd', 'Crowd report', 'F6'),
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
        ...page('/report/sos', 'Send SOS', 'F6'),
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
        ...page('/my-reports', 'My reports', 'F6'),
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
      {
        ...page('/police/zones/:id', 'Zone live view', 'F4'),
        lazy: async () => ({
          Component: (await import('@/features/zones/PoliceZoneDetail'))
            .PoliceZoneDetail,
        }),
      },
      {
        ...page('/police/monitor', 'Camera control', 'F4'),
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
        ...page('/police/reports', 'Report review', 'F6'),
        lazy: async () => ({
          Component: (await import('@/features/reports')).ReportReviewPage,
        }),
      },
      {
        ...page('/police/advisories', 'Broadcast advisory', 'F6'),
        lazy: async () => ({
          Component: (await import('@/features/advisories'))
            .PoliceAdvisoriesPage,
        }),
      },
      {
        handle: { role: 'admin' },
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
    ],
  },
];
export const router = createBrowserRouter(routes);
