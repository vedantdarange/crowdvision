// @vitest-environment node
import { expect, it, vi } from 'vitest';
import { createState } from '../mock-server/state';
import { createEngine } from '../mock-server/engine';
it('debounces spikes, uses hysteresis and preserves a critical alert through NO_DATA and clearing', () => {
  const state = createState(),
    emit = vi.fn(),
    engine = createEngine(state, emit),
    zone = state.zones[0]!,
    time = Date.now();
  engine.apply(zone, 2, 0.08, time);
  expect(zone.level).toBe('SAFE');
  engine.apply(zone, 6, 0.24, time + 1000);
  engine.apply(zone, 2, 0.08, time + 2000);
  expect(zone.open_alert_id).toBeNull();
  engine.apply(zone, 6, 0.24, time + 3000);
  engine.apply(zone, 6, 0.24, time + 6000);
  expect(zone.level).toBe('CRITICAL');
  const alert = state.alerts.find((a) => a.id === zone.open_alert_id)!;
  engine.apply(zone, null, null, time + 7000);
  engine.apply(zone, null, null, time + 8000);
  expect(alert.condition_active).toBe(true);
  expect(
    state.events.filter(
      (e) => e.alert_id === alert.id && e.type === 'FEED_LOST',
    ),
  ).toHaveLength(1);
  engine.apply(zone, 6, 0.24, time + 9000);
  expect(zone.level).toBe('CRITICAL');
  expect(state.alerts.filter((a) => a.zone_id === 1)).toHaveLength(1);
  engine.apply(zone, 4.5, 0.18, time + 10000);
  engine.apply(zone, 4.5, 0.18, time + 20000);
  expect(zone.level).toBe('CRITICAL');
  engine.apply(zone, 1, 0.04, time + 21000);
  engine.apply(zone, 1, 0.04, time + 29000);
  expect(alert.status).toBe('NEW');
  expect(alert.condition_active).toBe(false);
  expect(alert.peak_level).toBe('CRITICAL');
  expect(
    state.events.some(
      (e) => e.alert_id === alert.id && e.type === 'FEED_RESTORED',
    ),
  ).toBe(true);
});
it('auto-clears only unacknowledged warning peaks and uses a 60-second trend', () => {
  const state = createState(),
    engine = createEngine(state, () => {}),
    zone = state.zones[0]!,
    time = Date.now();
  engine.apply(zone, 3, 0.12, time);
  const alert = state.alerts.find((a) => a.id === zone.open_alert_id)!;
  engine.apply(zone, 4, 0.16, time + 1000);
  expect(zone.trend).toBe('STEADY');
  engine.apply(zone, 1, 0.04, time + 2000);
  expect(zone.trend).toBe('FALLING');
  engine.apply(zone, 1, 0.04, time + 10000);
  expect(alert.status).toBe('AUTO_CLEARED');
  expect(zone.open_alert_id).toBeNull();
});
it('re-raises an active resolved condition only after the configured delay', () => {
  const state = createState(),
    engine = createEngine(state, () => {}),
    zone = state.zones[0]!,
    time = Date.now();
  engine.apply(zone, 6, 0.24, time);
  const prior = state.alerts.find((a) => a.id === zone.open_alert_id)!;
  prior.status = 'RESOLVED';
  prior.resolved_at = new Date(time).toISOString();
  zone.open_alert_id = null;
  engine.apply(zone, 6, 0.24, time + 59000);
  expect(zone.open_alert_id).toBeNull();
  engine.apply(zone, 6, 0.24, time + 60000);
  expect(zone.open_alert_id).not.toBe(prior.id);
  expect(
    state.events.find(
      (e) => e.alert_id === zone.open_alert_id && e.type === 'CREATED',
    )?.data,
  ).toEqual({
    reason: 'STILL_ACTIVE_AFTER_RESOLVE',
    previous_alert_id: prior.id,
  });
});
