import type { Alert, Level, ZoneState } from '../../contract/types';
import {
  fixture,
  now,
  publicZone,
  type MockEmit,
  type MockState,
} from './state';
export function createEngine(state: MockState, emit: MockEmit) {
  const candidates = new Map<number, { level: Level; since: number }>();
  const reminders = new Map<number, number>();
  const history = new Map<number, { time: number; metric: number }[]>();
  const lastEmit = new Map<number, number>();
  const addEvent = (
    alert: Alert,
    type: (typeof state.events)[number]['type'],
    data: Record<string, unknown> = {},
  ) =>
    state.events.push({
      id: state.nextId++,
      alert_id: alert.id,
      type,
      actor: null,
      data,
      created_at: now(),
    });
  function publish(zone: ZoneState, time = Date.now()) {
    if (time - (lastEmit.get(zone.id) ?? -Infinity) < 1000) return;
    lastEmit.set(zone.id, time);
    emit('zone:update', publicZone(zone), 'public');
    emit('zone:detail', zone, 'role:police');
  }
  function apply(
    zone: ZoneState,
    count: number | null,
    density: number | null,
    time = Date.now(),
  ) {
    const previous = zone.level,
      metric = zone.mode === 'COUNT' ? count : density;
    const warning =
        zone.mode === 'COUNT' ? zone.warning_count! : zone.warning_density,
      critical =
        zone.mode === 'COUNT' ? zone.critical_count! : zone.critical_density;
    let candidate: Level = 'NO_DATA';
    if (metric !== null) {
      candidate =
        metric >= critical
          ? 'CRITICAL'
          : metric >= warning
            ? 'WARNING'
            : 'SAFE';
      if (
        previous === 'CRITICAL' &&
        metric >= critical * state.settings.hysteresis_ratio
      )
        candidate = 'CRITICAL';
      else if (
        (previous === 'CRITICAL' || previous === 'WARNING') &&
        metric >= warning * state.settings.hysteresis_ratio &&
        candidate === 'SAFE'
      )
        candidate = 'WARNING';
    }
    const samples = (history.get(zone.id) ?? []).filter(
      (p) => time - p.time <= 60000,
    );
    const change =
        metric === null ? 0 : metric - (samples[0]?.metric ?? metric),
      threshold = zone.mode === 'COUNT' ? 2 : 0.3;
    zone.trend =
      change >= threshold
        ? 'RISING'
        : change <= -threshold
          ? 'FALLING'
          : 'STEADY';
    if (metric !== null) samples.push({ time, metric });
    history.set(zone.id, samples);
    zone.count = count;
    zone.density = density;
    if (candidate === previous) candidates.delete(zone.id);
    else if (candidate === 'NO_DATA' || previous === 'NO_DATA') {
      zone.level = candidate;
      candidates.delete(zone.id);
    } else {
      let pending = candidates.get(zone.id);
      if (pending?.level !== candidate) {
        pending = { level: candidate, since: time };
        candidates.set(zone.id, pending);
      }
      const rank = { NO_DATA: -1, SAFE: 0, WARNING: 1, CRITICAL: 2 };
      if (
        time - pending.since >=
        (rank[candidate] > rank[previous]
          ? state.settings.debounce_s
          : state.settings.clear_s) *
          1000
      ) {
        zone.level = candidate;
        candidates.delete(zone.id);
      }
    }
    zone.live_updated_at = now();
    let alert = state.alerts.find(
      (a) =>
        a.zone_id === zone.id &&
        !['RESOLVED', 'AUTO_CLEARED'].includes(a.status),
    );
    if (zone.level === 'NO_DATA') {
      if (alert && previous !== 'NO_DATA') addEvent(alert, 'FEED_LOST');
    } else {
      if (alert && previous === 'NO_DATA') addEvent(alert, 'FEED_RESTORED');
      if (zone.level === 'WARNING' || zone.level === 'CRITICAL') {
        if (!alert) {
          const resolved = state.alerts
            .filter((a) => a.zone_id === zone.id && a.status === 'RESOLVED')
            .sort((a, b) =>
              (b.resolved_at ?? '').localeCompare(a.resolved_at ?? ''),
            )[0];
          const stillActive = resolved?.condition_active === true;
          if (
            !stillActive ||
            time - Date.parse(resolved.resolved_at!) >=
              state.settings.reraise_after_s * 1000
          ) {
            alert = {
              ...fixture<Alert>('alert'),
              id: state.nextId++,
              zone_id: zone.id,
              zone_name: zone.name,
              location: zone.centroid,
              level: zone.level,
              peak_level: zone.level,
              peak_count: count ?? 0,
              peak_density: density ?? 0,
              condition_active: true,
              condition_cleared_at: null,
              created_at: now(),
            };
            state.alerts.push(alert);
            zone.open_alert_id = alert.id;
            addEvent(
              alert,
              'CREATED',
              stillActive
                ? {
                    reason: 'STILL_ACTIVE_AFTER_RESOLVE',
                    previous_alert_id: resolved.id,
                  }
                : {},
            );
            emit('alert:new', alert, 'role:police');
          }
        } else {
          const rose = alert.level === 'WARNING' && zone.level === 'CRITICAL';
          if (!alert.condition_active) {
            alert.condition_active = true;
            alert.condition_cleared_at = null;
            addEvent(alert, 'REOPENED');
          }
          alert.level = zone.level;
          if (zone.level === 'CRITICAL') alert.peak_level = 'CRITICAL';
          alert.peak_count = Math.max(alert.peak_count, count ?? 0);
          alert.peak_density = Math.max(alert.peak_density, density ?? 0);
          if (rose) {
            alert.last_escalated_at = now();
            addEvent(alert, 'ESCALATED');
            emit(
              'alert:escalated',
              { alert, reason: 'LEVEL_UP' },
              'role:police',
            );
          }
          emit('alert:updated', alert, 'role:police');
        }
      } else if (zone.level === 'SAFE' && alert?.condition_active) {
        alert.condition_active = false;
        alert.condition_cleared_at = now();
        if (alert.status === 'NEW' && alert.peak_level === 'WARNING') {
          alert.status = 'AUTO_CLEARED';
          zone.open_alert_id = null;
          addEvent(alert, 'AUTO_CLEARED');
        }
        emit('alert:updated', alert, 'role:police');
      }
    }
    if (
      alert?.status === 'NEW' &&
      alert.level === 'CRITICAL' &&
      alert.condition_active
    ) {
      const last = reminders.get(alert.id) ?? time;
      reminders.set(alert.id, last);
      if (time - last >= state.settings.escalation_s * 1000) {
        reminders.set(alert.id, time);
        addEvent(alert, 'REMINDER');
        emit(
          'alert:escalated',
          { alert, reason: 'CRITICAL_UNACKNOWLEDGED' },
          'role:police',
        );
      }
    }
    publish(zone, time);
  }
  return { apply, publish };
}
