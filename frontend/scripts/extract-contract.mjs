import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';

const contract = readFileSync(
  new URL('../../00_SHARED_CONTRACT.md', import.meta.url),
  'utf8',
);
const section = contract
  .split('## 5. Data shapes')[1]
  .split('## 6. REST API')[0];
const section8 = contract
  .split('## 8. Frame pipeline contract')[1]
  .split('## 9. Web Push')[0];
const block = section.match(/```ts\r?\n([\s\S]*?)```/)[1];
const frames = section8
  .match(/```ts\r?\n([\s\S]*?)```/)[1]
  .replaceAll('interface Frame', 'export interface Frame');
const directory = new URL('../../contract/', import.meta.url);
mkdirSync(directory, { recursive: true });
writeFileSync(
  new URL('types.ts', directory),
  block +
    '\n' +
    frames +
    `
export const CONTRACT_VERSION = "1.1.0";
export interface HelloPayload { role: Role | null; server_time: ISODateTime; contract_version: string }
export interface AlertEscalatedPayload { alert: Alert; reason: 'LEVEL_UP' | 'CRITICAL_UNACKNOWLEDGED' }
export interface AdvisoryRetractedPayload { id: number }
export interface SourceStatusPayload { source_id: number; zone_id: number; status: SourceStatus; last_frame_at: ISODateTime | null }
export type AuthExpiredPayload = Record<string, never>;
export interface Health { status: 'ok'; db: 'ok'; detector: 'ready' | 'loading' | 'unavailable'; worker_alive: boolean; version: string }
export interface AuthSession { user: User; access_token: string; refresh_token: string; expires_in: number }
export interface AccessToken { access_token: string; expires_in: number }
export interface PublicZoneDetail { state: PublicZoneState; alternatives: PublicZoneState[] }
export interface ServerToClientEvents {
  hello: (payload: HelloPayload) => void;
  'auth:expired': (payload: AuthExpiredPayload) => void;
  'zone:update': (payload: PublicZoneState) => void;
  'zone:detail': (payload: ZoneState) => void;
  'alert:new': (payload: Alert) => void;
  'alert:updated': (payload: Alert) => void;
  'alert:escalated': (payload: AlertEscalatedPayload) => void;
  'advisory:new': (payload: Advisory) => void;
  'advisory:retracted': (payload: AdvisoryRetractedPayload) => void;
  'report:new': (payload: Report) => void;
  'report:updated': (payload: Report) => void;
  'source:status': (payload: SourceStatusPayload) => void;
  'frame:result': (payload: FrameResult) => void;
}
export interface ClientToServerEvents { 'frame:submit': (payload: FrameSubmit) => void }
`,
);
writeFileSync(new URL('CONTRACT_VERSION', directory), '1.1.0\n');
