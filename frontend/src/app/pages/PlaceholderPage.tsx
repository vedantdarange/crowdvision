import { Link, useLocation, useMatches } from 'react-router';
import {
  ArrowUpRight,
  MapPinned,
  Layers3,
  Radio,
  Megaphone,
  LifeBuoy,
  Flag,
  ChevronRight,
  DoorOpen,
  TentTree,
  Landmark,
  Route,
  ShieldCheck,
  Compass,
  NotebookPen,
} from 'lucide-react';
import { LevelBadge } from '@/components/status/LevelBadge';
import { AlertCount } from '@/components/status/AlertCount';
import { LEVELS } from '@/lib/constants';
import snapshot from '@contract/examples/zones_live.json';
import help from '@contract/examples/help_info.json';
import alertPreview from '@contract/examples/alert.json';
import zonePreview from '@contract/examples/zones.json';
import type { Level } from '@contract/types';
import { VenuePlan } from './VenuePlan';
const zones = snapshot.data;
const entrances = [Landmark, TentTree, DoorOpen];
function Resources({ operations }: { operations: boolean }) {
  const links = operations
    ? ([
        ['/police/alerts', 'Alert queue', ShieldCheck],
        ['/police/monitor', 'Camera monitor', Radio],
        ['/police/reports', 'Report review', NotebookPen],
      ] as const)
    : ([
        ['/advisories', 'Venue advisories', Megaphone],
        ['/report/crowd', 'Report a crowd', NotebookPen],
        ['/help', 'Help centre', LifeBuoy],
      ] as const);
  return (
    <section className="field-guide">
      <div className="guide-icon">
        <Compass size={22} />
      </div>
      <p className="eyebrow">
        {operations ? 'Operations' : 'Visitor resources'}
      </p>
      <h2>{operations ? 'Response desk' : 'Safety desk'}</h2>
      <p className="guide-intro">
        {operations
          ? 'Review alerts, camera sources and incoming reports.'
          : 'Find venue notices, report a concern, or get directions to help.'}
      </p>
      <div className="guide-links">
        {links.map(([path, title, Icon]) => (
          <Link to={path} key={path}>
            <Icon size={17} />
            {title}
            <ArrowUpRight size={14} />
          </Link>
        ))}
      </div>
    </section>
  );
}
export function Component() {
  const { pathname } = useLocation();
  const handle = useMatches().at(-1)?.handle as
    { title: string; phase: string } | undefined;
  const home = pathname === '/' || pathname === '/police';
  const venuePage = home || pathname === '/help' || pathname.includes('/zones');
  const alertZone =
    pathname === '/police/alerts' ||
    pathname === `/police/alerts/${alertPreview.id}`
      ? zonePreview.data.find(
          (zone) => zone.id === alertPreview.zone_id && zone.mode === 'COUNT',
        )
      : undefined;
  const title =
    pathname === '/' ? 'Venue overview' : (handle?.title ?? 'Page not found');
  return (
    <div className="cv-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">
            <span className="section-rule" />
            {home ? 'Venue monitoring' : 'Crowd safety'}
          </p>
          <h1>{title}</h1>
          <p>
            {home
              ? 'A view of the venue, its zones and visitor resources.'
              : pathname === '/help'
                ? 'Find your way around the venue and its safety resources.'
                : `Preview of the ${title.toLowerCase()} workspace.`}
          </p>
        </div>
        <span className="demo-pill">
          <span /> Demo preview
        </span>
      </header>
      <div className="dashboard-grid">
        <div className="left-stack">
          {venuePage ? (
            <>
              <section
                className="stat-strip glass"
                aria-label="Demo venue summary"
              >
                {(
                  [
                    [
                      MapPinned,
                      'Venue zones',
                      String(zones.length).padStart(2, '0'),
                    ],
                    [
                      Radio,
                      'Zones with data',
                      String(
                        zones.filter((z) => z.updated_at !== null).length,
                      ).padStart(2, '0'),
                    ],
                    [Layers3, 'Status levels', '04'],
                  ] as const
                ).map(([Icon, label, value]) => (
                  <div className="stat" key={label}>
                    <span className="stat-icon">
                      <Icon size={19} />
                    </span>
                    <div>
                      <small>{label}</small>
                      <strong className="reading">{value}</strong>
                    </div>
                  </div>
                ))}
              </section>
              <section className="glass map-card">
                <div className="card-title">
                  <div>
                    <p className="eyebrow">Venue layout</p>
                    <h2>Zone map</h2>
                  </div>
                  <MapPinned size={21} />
                </div>
                <VenuePlan />
                <div className="map-foot">
                  <Flag size={15} /> Ganesh festival venue{' '}
                  <span>Pune, India</span>
                </div>
              </section>
              {pathname === '/help' && (
                <section className="glass directory">
                  <div className="card-title">
                    <h2>Emergency contacts</h2>
                    <LifeBuoy size={20} />
                  </div>
                  {help.emergency_numbers.map((contact) => (
                    <a
                      className="zone-row"
                      href={`tel:${contact.number}`}
                      key={contact.number}
                    >
                      <strong>{contact.label}</strong>
                      <span className="reading">{contact.number}</span>
                      <ArrowUpRight size={14} />
                    </a>
                  ))}
                </section>
              )}
              <section className="glass directory">
                <div className="card-title">
                  <div>
                    <p className="eyebrow">Venue directory</p>
                    <h2>Monitored zones</h2>
                  </div>
                  <Route size={21} />
                </div>
                {zones.map((zone, i) => {
                  const Icon = entrances[i] ?? MapPinned;
                  return (
                    <Link
                      className="zone-row"
                      key={zone.zone_id}
                      to={`/zones/${zone.zone_id}`}
                    >
                      <span className="zone-icon">
                        <Icon size={18} />
                      </span>
                      <strong>{zone.name}</strong>
                      <LevelBadge level={zone.level as Level} />
                      <ChevronRight size={15} />
                    </Link>
                  );
                })}
              </section>
            </>
          ) : (
            <section className="glass directory">
              <div className="card-title">
                <div>
                  <p className="eyebrow">
                    {alertZone
                      ? 'Peak count / critical threshold'
                      : 'Workspace preview'}
                  </p>
                  <h2>{title}</h2>
                </div>
                <Layers3 size={21} />
              </div>
              <p className="px-5 pb-5">
                {alertZone ? (
                  <AlertCount
                    zone={alertPreview.zone_name}
                    peak={alertPreview.peak_count}
                    threshold={alertZone.critical_count}
                  />
                ) : handle?.phase ? (
                  `This screen is scheduled for ${handle.phase}. You can explore the demo venue while it is in development.`
                ) : (
                  'Choose a destination from the menu.'
                )}
              </p>
              <Link className="zone-row" to="/">
                <MapPinned size={18} />
                <strong>Explore the venue</strong>
                <ArrowUpRight size={15} />
              </Link>
            </section>
          )}
        </div>
        <div className="right-stack">
          <Resources
            operations={
              pathname.startsWith('/admin') || pathname.startsWith('/police')
            }
          />
          <section className="glass legend">
            <div className="card-title">
              <div>
                <p className="eyebrow">Quick reference</p>
                <h2>Status guide</h2>
              </div>
              <ShieldCheck size={20} />
            </div>
            {LEVELS.map((level, i) => (
              <div className="legend-row" key={level}>
                <LevelBadge level={level} />
                <span>
                  {
                    [
                      'Below threshold',
                      'Elevated crowding',
                      'High crowding',
                      'Feed unavailable',
                    ][i]
                  }
                </span>
              </div>
            ))}
          </section>
        </div>
      </div>
    </div>
  );
}
