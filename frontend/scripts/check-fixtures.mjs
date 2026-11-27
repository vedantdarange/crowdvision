import { readFileSync, readdirSync, writeFileSync, unlinkSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const map = {
  user: 'User',
  person_ref: 'PersonRef',
  lat_lng: 'LatLng',
  polygon_geometry: 'PolygonGeometry',
  thresholds: 'Thresholds',
  zone: 'Zone',
  zone_state_public: 'PublicZoneState',
  zone_state: 'ZoneState',
  source_info: 'SourceInfo',
  alert: 'Alert',
  alert_detail: 'AlertDetail',
  alert_event: 'AlertEvent',
  advisory: 'Advisory',
  report_crowd: 'Report',
  report_sos: 'Report',
  report_new: 'Report',
  frame_result: 'FrameResult',
  frame_result_source_in_use: 'FrameResult',
  config: 'RuntimeConfig',
  settings: 'Settings',
  help_info: 'HelpInfo',
  analytics_summary: 'AnalyticsSummary',
  health: 'Health',
  error_validation: 'ApiError',
  error_forbidden: 'ApiError',
  error_method_not_allowed: 'ApiError',
  zones_live: 'ApiOne<PublicZoneState[]>',
  zones: 'ApiOne<ZoneState[]>',
  sources: 'ApiOne<SourceInfo[]>',
  zone_public_detail: 'ApiOne<PublicZoneDetail>',
  alerts_list: 'ApiList<Alert>',
  users_list: 'ApiList<User>',
  reports_list: 'ApiList<Report>',
  audit_logs_list: 'ApiList<AuditLog>',
  advisories: 'ApiOne<Advisory[]>',
  history: 'ApiOne<HistoryPoint[]>',
  history_point: 'HistoryPoint',
  audit_log: 'AuditLog',
  hello: 'HelloPayload',
  alert_escalated: 'AlertEscalatedPayload',
  advisory_retracted: 'AdvisoryRetractedPayload',
  source_status: 'SourceStatusPayload',
  auth_expired: 'AuthExpiredPayload',
};
const dir = new URL('../../contract/examples/', import.meta.url);
const files = readdirSync(dir).filter((f) => f.endsWith('.json'));
if (files.length !== Object.keys(map).length)
  throw new Error('Every fixture must have exactly one explicit type mapping.');
const types = [
  ...new Set(Object.values(map).flatMap((t) => t.match(/\b[A-Z]\w*/g))),
];
const declarations = files.map((file, index) => {
  const type = map[file.slice(0, -5)];
  if (!type) throw new Error('Unmapped fixture: ' + file);
  return `export const fixture${index}: ${type} = ${JSON.stringify(JSON.parse(readFileSync(new URL(file, dir), 'utf8')))};`;
});
const generated = new URL('.fixtures.generated.ts', import.meta.url);
try {
  writeFileSync(
    generated,
    `import type { ${types.join(',')} } from '../../contract/types';\n` +
      declarations.join('\n'),
  );
  const result = spawnSync(
    process.execPath,
    [
      fileURLToPath(
        new URL('../node_modules/typescript/bin/tsc', import.meta.url),
      ),
      '--noEmit',
      '--strict',
      '--noUncheckedIndexedAccess',
      '--skipLibCheck',
      '--target',
      'ES2023',
      '--moduleResolution',
      'bundler',
      '--module',
      'ESNext',
      '--ignoreConfig',
      fileURLToPath(generated),
    ],
    { stdio: 'inherit' },
  );
  process.exitCode = result.status ?? 1;
  if (result.status === 0)
    process.stdout.write(
      `Type-checked all ${files.length} fixtures against contract/types.ts.\n`,
    );
} finally {
  unlinkSync(generated);
}
