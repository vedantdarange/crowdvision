import { Link, useParams, useNavigate } from 'react-router';
import type { AlertEvent } from '@contract/types';
import { Actions, Age, Status, label, useAlertDialog } from './Alerts';
import { useAlert, useZone } from './data';
import { LevelBadge } from '@/components/status/LevelBadge';
import { PoliceMap } from './PoliceMap';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
export function Timeline({ events }: { events: AlertEvent[] }) {
  return (
    <section className="glass">
      <h2>Timeline</h2>
      {!events.length && <p>No events recorded.</p>}
      <ol>
        {[...events]
          .sort(
            (a, b) =>
              Date.parse(a.created_at) - Date.parse(b.created_at) ||
              a.id - b.id,
          )
          .map((e) => {
            const title =
              e.type === 'FEED_LOST'
                ? 'Camera feed lost'
                : e.type === 'FEED_RESTORED'
                  ? 'Camera feed restored'
                  : e.type === 'CREATED' &&
                      e.data.reason === 'STILL_ACTIVE_AFTER_RESOLVE'
                    ? 'Raised again: still over the limit'
                    : label(e.type);
            return (
              <li key={e.id}>
                <strong>{title}</strong>
                <span>{e.actor?.name ?? 'System'}</span>
                <Age ts={e.created_at} />
                {typeof e.data.note === 'string' && <p>{e.data.note}</p>}
              </li>
            );
          })}
      </ol>
    </section>
  );
}
function DetailMap({ id }: { id: number }) {
  const { data: zone } = useZone(id),
    navigate = useNavigate();
  return (
    <PoliceMap
      zones={[zone]}
      selected={id}
      select={() => void navigate('/police/zones/' + id)}
    />
  );
}
export function Detail() {
  const { id } = useParams(),
    { data: a } = useAlert(Number(id)),
    { choose, dialog } = useAlertDialog();
  return (
    <section className="police-page">
      <Link
        className="inline-flex min-h-11 items-center justify-self-start"
        to="/police/alerts"
      >
        Alert queue
      </Link>
      <h1>
        {a.zone_name} · Alert #{a.id}
      </h1>
      <div className="police-grid">
        <section className="glass">
          <h2>Alert summary</h2>
          <div className="police-actions">
            <LevelBadge level={a.level} />
            <Status alert={a} />
          </div>
          <p>Peak level · {label(a.peak_level)}</p>
          <p>Peak density · {a.peak_density} people/m²</p>
          <p>Peak count · {a.peak_count}</p>
          <p>
            Created · <Age ts={a.created_at} />
          </p>
          {(['acknowledged', 'responding', 'resolved'] as const).map((step) => (
            <p key={step}>
              {label(step)} ·{' '}
              {a[`${step}_at`] ? (
                <>
                  {a[`${step}_by`]?.name ?? 'System'} ·{' '}
                  <Age ts={a[`${step}_at`]} />
                </>
              ) : (
                '—'
              )}
            </p>
          ))}
          {a.resolution_note && <p>Resolution note · {a.resolution_note}</p>}
          <Actions alert={a} choose={choose} />
        </section>
        <section className="glass detail-map">
          <h2>Zone location</h2>
          <SuspenseBoundary>
            <DetailMap id={a.zone_id} />
          </SuspenseBoundary>
          <Link
            className="inline-flex min-h-11 items-center"
            to={'/police/zones/' + a.zone_id}
          >
            Open zone live view
          </Link>
        </section>
      </div>
      <Timeline events={a.events} />
      {dialog}
    </section>
  );
}
