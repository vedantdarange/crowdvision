import { useState } from 'react';
import {
  Link,
  NavLink,
  Outlet,
  ScrollRestoration,
  useNavigate,
} from 'react-router';
import {
  Activity,
  Map,
  Bell,
  NotebookPen,
  LifeBuoy,
  UserRound,
  LayoutDashboard,
  Siren,
  ScanLine,
  Inbox,
  Megaphone,
  FileText,
  MapPinned,
  Camera,
  Users,
  SlidersHorizontal,
  ChartNoAxesColumn,
  History,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeftOpen,
  Menu,
  Layers,
  ChevronRight,
  ShieldCheck,
  Globe,
  Sliders,
  type LucideIcon,
} from 'lucide-react';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { ThemeProvider, useTheme } from '../ThemeProvider';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { useSession } from '@/features/auth';
import { loginPath } from '@/features/auth/access';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuItem,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import './shell.css';
import '@/features/police/police.css';
import { ConnectionDot } from '@/components/status/ConnectionDot';
import { useConnection } from '@/features/realtime/RealtimeProvider';
import { toast } from 'sonner';
import { InstallHint, sendTestPush } from '@/features/push';

type Audience = 'public' | 'auth' | 'police' | 'admin';
type Item = readonly [string, string, LucideIcon];
const publicMenu: Item[] = [
  ['/', 'Venue overview', Map],
  ['/advisories', 'Advisories', Bell],
  ['/report/crowd', 'Report a crowd', NotebookPen],
  ['/help', 'Help centre', LifeBuoy],
];
const operations: Item[] = [
  ['/police', 'Dashboard', LayoutDashboard],
  ['/police/alerts', 'Alerts', Siren],
  ['/police/monitor', 'Monitor', ScanLine],
  ['/police/reports', 'Reports', Inbox],
];
const extra: Item[] = [
  ['/police/advisories', 'Broadcast', Megaphone],
  ['/my-reports', 'My reports', FileText],
  ['/help', 'Help centre', LifeBuoy],
];
const administration: Item[] = [
  ['/admin/zones', 'Zones', MapPinned],
  ['/admin/sources', 'Sources', Camera],
  ['/admin/users', 'Users', Users],
  ['/admin/settings', 'Settings', SlidersHorizontal],
  ['/admin/analytics', 'Analytics', ChartNoAxesColumn],
  ['/admin/audit', 'Audit log', History],
];
const spaces: Item[] = [
  ['/', 'Public workspace', Globe],
  ['/police', 'Police workspace', ShieldCheck],
  ['/admin/zones', 'Admin workspace', Sliders],
];
function MenuLinks({
  items,
  close = false,
  compact = false,
}: {
  items: Item[];
  close?: boolean;
  compact?: boolean;
}) {
  return items.map(([path, name, Icon]) => {
    const link = (
      <NavLink
        key={path}
        to={path}
        end
        title={name}
        aria-label={name}
        className="rail-link"
      >
        <Icon aria-hidden size={18} />
        <span className={compact ? 'sr-only' : ''}>{name}</span>
      </NavLink>
    );
    return close ? (
      <SheetClose key={path} asChild>
        {link}
      </SheetClose>
    ) : (
      link
    );
  });
}
type ShellProps = { audience: Audience; children?: import('react').ReactNode };
function Shell({ audience, children }: ShellProps) {
  const { theme, toggle } = useTheme();
  const connection = useConnection((s) => s.status);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cv-sidebar') === 'compact';
    } catch {
      return false;
    }
  });
  function resize() {
    setCollapsed(!collapsed);
    try {
      localStorage.setItem('cv-sidebar', collapsed ? 'expanded' : 'compact');
    } catch {
      /* Keep the current session preference. */
    }
  }
  const professional = audience === 'admin' || audience === 'police';
  const { user, logout } = useSession();
  const [sendingTestPush, setSendingTestPush] = useState(false);

  async function handleSendTestPush() {
    if (sendingTestPush) return;
    setSendingTestPush(true);
    try {
      const result = await sendTestPush();
      toast.success(
        result.sent === 1
          ? 'Sent test notification to 1 device.'
          : `Sent test notification to ${result.sent} devices.`,
      );
    } catch {
      toast.error('Could not send test notification.');
    } finally {
      setSendingTestPush(false);
    }
  }
  const navigate = useNavigate();
  const workspaces = spaces.filter(
    ([path]) =>
      path === '/' ||
      (path === '/police' && user && user.role !== 'citizen') ||
      user?.role === 'admin',
  );
  const main: Item[] = professional
    ? operations
    : publicMenu.map((item) =>
        item[0] === '/report/crowd' && !user
          ? [loginPath(item[0]), item[1], item[2]]
          : item,
      );
  const more: Item[] = professional
    ? extra
    : user
      ? [
          ['/my-reports', 'My reports', FileText],
          ['/report/sos', 'Send SOS', Siren],
        ]
      : [['/login', 'Account', UserRound]];
  const space =
    audience === 'admin'
      ? 'Administration'
      : professional
        ? 'Police operations'
        : 'Public workspace';
  const navigation = (mobile = false) => (
    <>
      <nav aria-label="Main navigation">
        <p className="rail-caption">Main menu</p>
        <MenuLinks
          items={[...main, ...more]}
          compact={!mobile && collapsed}
          close={mobile}
        />
      </nav>
      {user?.role === 'admin' && (
        <nav aria-label="Administration">
          <p className="rail-caption">Administration</p>
          <MenuLinks
            items={administration}
            compact={!mobile && collapsed}
            close={mobile}
          />
        </nav>
      )}
      {workspaces.length > 1 && (
        <nav aria-label="Workspaces">
          <p className="rail-caption">Workspaces</p>
          <MenuLinks
            items={workspaces}
            compact={!mobile && collapsed}
            close={mobile}
          />
        </nav>
      )}
    </>
  );
  return (
    <div className="cv-frame" data-compact={collapsed}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside id="venue-sidebar" className="cv-rail">
        <Link
          to="/"
          className="cv-brand"
          aria-label="CrowdVision — Crowd Safety Monitor"
        >
          <span className="brand-icon">
            <Activity size={23} aria-hidden />
          </span>
          <span className="brand-name">CrowdVision</span>
        </Link>
        {navigation()}
        <button
          type="button"
          className="rail-link collapse-btn"
          onClick={resize}
          aria-controls="venue-sidebar"
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen size={18} />
          ) : (
            <PanelLeftClose size={18} />
          )}
          <span className={collapsed ? 'sr-only' : ''}>Collapse sidebar</span>
        </button>
      </aside>
      <div className="cv-main">
        <header className="cv-top">
          <span className="breadcrumb">
            <Layers size={16} /> Crowd Safety Monitor <ChevronRight size={13} />{' '}
            <strong>{space}</strong>
          </span>
          <div className="top-actions">
            {professional && <ConnectionDot state={connection} />}
            <button
              type="button"
              className="cv-tool"
              onClick={toggle}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="cv-tool"
                    aria-label={'Account for ' + user.name}
                  >
                    <UserRound size={18} />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>
                    {user.name} · {user.role}
                  </DropdownMenuLabel>
                  <DropdownMenuItem onSelect={toggle}>
                    Switch to {theme === 'dark' ? 'light' : 'dark'} mode
                  </DropdownMenuItem>
                  {(user.role === 'police' || user.role === 'admin') && (
                    <DropdownMenuItem
                      disabled={sendingTestPush}
                      onSelect={() => {
                        void handleSendTestPush();
                      }}
                    >
                      Send test notification
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem
                    onSelect={() => {
                      logout();
                      void navigate('/', { replace: true });
                    }}
                  >
                    Log out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <Link className="cv-tool" to="/login" aria-label="Open account">
                <UserRound size={18} />
              </Link>
            )}
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <InstallHint />
          {children}
          <SuspenseBoundary>
            <Outlet />
          </SuspenseBoundary>
        </main>
      </div>
      <nav className="cv-bottom" aria-label="Mobile navigation">
        <MenuLinks items={main.slice(0, 4)} />
        <Sheet>
          <SheetTrigger asChild>
            <button
              className="rail-link"
              aria-label={
                professional ? 'More navigation' : 'Account navigation'
              }
            >
              {professional ? <Menu size={18} /> : <UserRound size={18} />}
              {professional ? 'More' : 'Account'}
            </button>
          </SheetTrigger>
          <SheetContent className="overflow-y-auto">
            <SheetHeader>
              <SheetTitle>
                {professional
                  ? 'Navigation'
                  : user
                    ? user.name + ' · ' + user.role
                    : 'Account'}
              </SheetTitle>
            </SheetHeader>
            <div className="drawer-links">
              {navigation(true)}
              {!professional && user && (
                <SheetClose asChild>
                  <button
                    className="rail-link"
                    onClick={() => {
                      logout();
                      void navigate('/', { replace: true });
                    }}
                  >
                    Log out
                  </button>
                </SheetClose>
              )}
            </div>
          </SheetContent>
        </Sheet>
      </nav>
      <ScrollRestoration />
    </div>
  );
}
export function AppShell({ audience, children }: ShellProps) {
  return (
    <ThemeProvider
      defaultTheme={
        audience === 'admin' || audience === 'police' ? 'dark' : 'light'
      }
    >
      <Shell audience={audience}>{children}</Shell>
    </ThemeProvider>
  );
}
