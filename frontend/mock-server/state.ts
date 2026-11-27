import { readFileSync } from 'node:fs';
import type {
  Advisory,
  Alert,
  AlertEvent,
  AnalyticsSummary,
  AuditLog,
  HelpInfo,
  Report,
  RuntimeConfig,
  Settings,
  User,
  ZoneState,
  PublicZoneState,
  ApiOne,
  ApiList,
} from '../../contract/types';

export const now = () => new Date().toISOString();
export function fixture<T>(name: string): T {
  return JSON.parse(
    readFileSync(
      new URL(`../../contract/examples/${name}.json`, import.meta.url),
      'utf8',
    ),
  ) as T;
}
export function publicZone(z: ZoneState): PublicZoneState {
  return {
    zone_id: z.id,
    name: z.name,
    geometry: z.geometry,
    centroid: z.centroid,
    level: z.level,
    trend: z.trend,
    density: z.density === null ? null : Math.round(z.density * 10) / 10,
    updated_at: z.live_updated_at,
  };
}
export function createState() {
  const zones = fixture<ApiOne<ZoneState[]>>('zones').data;
  return {
    zones,
    users: fixture<ApiList<User>>('users_list').data,
    alerts: fixture<ApiList<Alert>>('alerts_list').data,
    events: fixture<{ events: AlertEvent[] }>('alert_detail').events,
    reports: fixture<ApiList<Report>>('reports_list').data,
    advisories: fixture<ApiOne<Advisory[]>>('advisories').data,
    audit: fixture<ApiList<AuditLog>>('audit_logs_list').data,
    config: fixture<RuntimeConfig>('config'),
    settings: fixture<Settings>('settings'),
    help: fixture<HelpInfo>('help_info'),
    analytics: fixture<AnalyticsSummary>('analytics_summary'),
    subscriptions: new Map<string, { id: number; userId: number }>(),
    passwords: new Map<number, string>(),
    tokens: new Map<
      string,
      { userId: number; kind: 'access' | 'refresh'; expires: number }
    >(),
    nextId: 100,
  };
}
export type MockState = ReturnType<typeof createState>;
export type MockEmit = (
  event: string,
  payload: unknown,
  room?: string | string[],
) => void;
export function recordAudit(
  state: MockState,
  user: User,
  action: string,
  entity: string,
  id: number | null,
) {
  state.audit.unshift({
    id: state.nextId++,
    actor: { id: user.id, name: user.name },
    action,
    entity_type: entity,
    entity_id: id,
    data: {},
    created_at: now(),
  });
}
