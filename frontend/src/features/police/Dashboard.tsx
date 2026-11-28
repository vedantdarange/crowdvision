import { Link, useNavigate } from 'react-router';
import { LevelBadge } from '@/components/status/LevelBadge';
import { TrendIcon } from '@/components/status/TrendIcon';
import { Age, Status } from './Alerts';
import { activeFeed, useZones, useAlerts } from './data';
import { PoliceMap } from './PoliceMap';
export function Dashboard() {
  const { data: zones } = useZones(),
    { data: feed } = useAlerts(activeFeed);
  const navigate = useNavigate();
  return (
    <section className="police-page">
      <header>
        <h1>Operations dashboard</h1>
      </header>
      <div className="police-grid">
        <section className="glass">
          <h2>Live zone map</h2>
          {zones.length ? (
            <PoliceMap
              zones={zones}
              select={(id) => void navigate('/police/zones/' + id)}
            />
          ) : (
            <p>No active zones.</p>
          )}
        </section>
        <section className="glass">
          <h2>
            Active alerts <span>{feed.pagination.total}</span>
          </h2>
          {!feed.data.length && (
            <p>No active alerts. All zones within limits.</p>
          )}
          <ul>
            {feed.data.map((a) => (
              <li key={a.id}>
                <Link
                  className="inline-flex min-h-11 items-center"
                  to={'/police/alerts/' + a.id}
                >
                  {a.zone_name} · #{a.id}
                </Link>
                <LevelBadge level={a.level} />
                <Status alert={a} />
                <Age ts={a.created_at} />
              </li>
            ))}
          </ul>
          <Link
            className="inline-flex min-h-11 items-center"
            to="/police/alerts"
          >
            Open alert queue
          </Link>
        </section>
      </div>
      <h2>Zones</h2>
      <div className="police-zones">
        {!zones.length && <p>No active zones.</p>}
        {zones.map((z) => {
          const online = z.sources.filter((s) => s.status === 'ONLINE').length;
          return (
            <article key={z.id} className="glass">
              <h3>
                <Link
                  className="inline-flex min-h-11 items-center"
                  to={'/police/zones/' + z.id}
                >
                  {z.name}
                </Link>
              </h3>
              <div className="police-actions">
                <LevelBadge level={z.level} />
                <TrendIcon trend={z.trend} />
              </div>
              <p>Density {z.density ?? '—'} people/m²</p>
              <p>
                Warning {z.warning_density} · Critical {z.critical_density}{' '}
                people/m²
              </p>
              {z.mode === 'COUNT' && (
                <p>
                  Count {z.count ?? '—'} · Warning {z.warning_count} · Critical{' '}
                  {z.critical_count}
                </p>
              )}
              <p>
                Sources · {online} online / {z.sources.length - online} offline
              </p>
              <small>
                {z.live_updated_at && 'Updated '}
                <Age ts={z.live_updated_at} />
              </small>
              <Link
                className="inline-flex min-h-11 items-center"
                to={'/police/zones/' + z.id}
              >
                View live chart
              </Link>
            </article>
          );
        })}
      </div>
    </section>
  );
}
