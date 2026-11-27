import { useState } from 'react';
import { Link, NavLink, Outlet, ScrollRestoration } from 'react-router';
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
import './shell.css';

type Audience = 'public' | 'auth' | 'police' | 'admin';
type Item = readonly [string, string, LucideIcon];
const publicMenu: Item[] = [
  ['/', 'Venue overview', Map],
  ['/advisories', 'Advisories', Bell],
  ['/report/crowd', 'Report a crowd', NotebookPen],
  ['/help', 'Help centre', LifeBuoy],
  ['/login', 'Account', UserRound],
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
  ['/login', 'Account', UserRound],
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
  ['/', 'Public preview', Globe],
  ['/police', 'Police preview', ShieldCheck],
  ['/admin/zones', 'Admin preview', Sliders],
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
function Shell({ audience }: { audience: Audience }) {
  const { theme, toggle } = useTheme();
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
  const main = professional ? operations : publicMenu;
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
          items={professional ? [...operations, ...extra] : main}
          compact={!mobile && collapsed}
          close={mobile}
        />
      </nav>
      {audience === 'admin' && (
        <nav aria-label="Administration">
          <p className="rail-caption">Administration</p>
          <MenuLinks
            items={administration}
            compact={!mobile && collapsed}
            close={mobile}
          />
        </nav>
      )}
      <nav aria-label="Preview workspaces">
        <p className="rail-caption">Workspaces</p>
        <MenuLinks
          items={spaces}
          compact={!mobile && collapsed}
          close={mobile}
        />
      </nav>
    </>
  );
  return (
    <div className="cv-frame" data-compact={collapsed}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside id="venue-sidebar" className="cv-rail">
        <Link to="/" className="cv-brand" aria-label="Crowd Safety Monitor">
          <span className="brand-icon">
            <Activity size={23} />
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
            <button
              type="button"
              className="cv-tool"
              onClick={toggle}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <Link className="cv-tool" to="/login" aria-label="Open account">
              <UserRound size={18} />
            </Link>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <SuspenseBoundary>
            <Outlet />
          </SuspenseBoundary>
        </main>
      </div>
      <nav className="cv-bottom" aria-label="Mobile navigation">
        <MenuLinks items={main.slice(0, 4)} />
        <Sheet>
          <SheetTrigger asChild>
            <button className="rail-link" aria-label="More navigation">
              <Menu size={18} />
              More
            </button>
          </SheetTrigger>
          <SheetContent className="overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Navigation</SheetTitle>
            </SheetHeader>
            <div className="drawer-links">{navigation(true)}</div>
          </SheetContent>
        </Sheet>
      </nav>
      <ScrollRestoration />
    </div>
  );
}
export function AppShell({ audience }: { audience: Audience }) {
  return (
    <ThemeProvider
      defaultTheme={
        audience === 'admin' || audience === 'police' ? 'dark' : 'light'
      }
    >
      <Shell audience={audience} />
    </ThemeProvider>
  );
}
