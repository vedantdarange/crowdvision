import { mkdirSync, writeFileSync } from 'node:fs';
const dir = new URL('../../contract/examples/', import.meta.url);
mkdirSync(dir, { recursive: true });
const save = (name, value) =>
  writeFileSync(
    new URL(name + '.json', dir),
    JSON.stringify(value, null, 2) + '\n',
  );
const time = '2026-11-24T10:15:30Z';
const person = { id: 2, name: 'Inspector Asha Rao' };
const citizen = { id: 4, name: 'Kiran Shah' };
const users = [
  { id: 1, name: 'Admin Meera', email: 'admin@demo.local', role: 'admin' },
  { ...person, email: 'police1@demo.local', role: 'police' },
  {
    id: 3,
    name: 'Inspector Arjun',
    email: 'police2@demo.local',
    role: 'police',
  },
  { ...citizen, email: 'citizen@demo.local', role: 'citizen' },
].map((user) => ({ ...user, is_active: true, created_at: time }));
const zones = ['Main Gate', 'Stage Area', 'Exit Lane'].map((name, i) => {
  const lat = 18.5195 + i * 0.0005,
    lng = 73.8553;
  const area = [40, 120, 25][i];
  const dy = Math.sqrt(area) / 111195 / 2;
  const dx = dy / Math.cos((lat * Math.PI) / 180);
  return {
    id: i + 1,
    name,
    description: 'Ganesh festival demonstration venue, Pune',
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [lng - dx, lat - dy],
          [lng + dx, lat - dy],
          [lng + dx, lat + dy],
          [lng - dx, lat + dy],
          [lng - dx, lat - dy],
        ],
      ],
    },
    centroid: { lat, lng },
    area_m2: area,
    mode: i === 2 ? 'DENSITY' : 'COUNT',
    warning_density: 3,
    critical_density: 4,
    warning_count: [3, 8, null][i],
    critical_count: [5, 10, null][i],
    is_active: true,
    created_at: time,
    updated_at: time,
    level: 'NO_DATA',
    trend: 'STEADY',
    count: null,
    density: null,
    sources: [
      {
        id: i + 1,
        zone_id: i + 1,
        name: name + ' camera',
        kind: i === 0 ? 'WEBCAM' : 'VIDEO_FILE',
        coverage_area_m2: [25, 60, 6][i],
        is_active: true,
        status: 'OFFLINE',
        last_frame_at: null,
        created_at: time,
      },
    ],
    open_alert_id: i === 1 ? 12 : null,
    live_updated_at: null,
  };
});
const pub = zones.map((z) => ({
  zone_id: z.id,
  name: z.name,
  geometry: z.geometry,
  centroid: z.centroid,
  level: z.level,
  trend: z.trend,
  density: z.density,
  updated_at: z.live_updated_at,
}));
const alert = {
  id: 12,
  zone_id: 2,
  zone_name: 'Stage Area',
  location: zones[1].centroid,
  level: 'CRITICAL',
  peak_level: 'CRITICAL',
  status: 'NEW',
  condition_active: false,
  peak_density: 0.2,
  peak_count: 12,
  created_at: time,
  acknowledged_at: null,
  acknowledged_by: null,
  responding_at: null,
  responding_by: null,
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
  condition_cleared_at: '2026-11-24T10:18:00Z',
  last_escalated_at: null,
};
const events = ['CREATED', 'FEED_LOST', 'FEED_RESTORED'].map((type, i) => ({
  id: i + 1,
  alert_id: 12,
  type,
  actor: null,
  data:
    i === 0
      ? { reason: 'STILL_ACTIVE_AFTER_RESOLVE', previous_alert_id: 11 }
      : {},
  created_at: `2026-11-24T10:1${5 + i}:30Z`,
}));
const advisory = {
  id: 1,
  title: 'Use the marked exit lane',
  body: 'Keep the ambulance access lane clear. Follow police directions.',
  severity: 'INFO',
  zone_id: null,
  zone_name: null,
  created_by: person,
  created_at: time,
  expires_at: null,
  is_active: true,
};
const report = {
  id: 45,
  kind: 'SOS',
  status: 'PENDING',
  zone_id: 1,
  zone_name: 'Main Gate',
  ...zones[0].centroid,
  count: null,
  density_hint: null,
  sos_type: 'CRUSH_RISK',
  note: 'Pressure building near the entrance barricade.',
  created_by: citizen,
  created_at: time,
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
};
const crowd = {
  ...report,
  id: 46,
  kind: 'CROWD',
  count: 14,
  density_hint: 0.35,
  sos_type: null,
  note: 'Queue near the entrance.',
};
const help = {
  emergency_numbers: [
    { label: 'Unified emergency', number: '112' },
    { label: 'Police', number: '100' },
    { label: 'Ambulance', number: '102' },
    { label: 'Fire', number: '101' },
  ],
  medical_points: [
    { name: 'First aid tent', ...zones[1].centroid, note: 'Beside Stage Area' },
  ],
  exits: [{ name: 'Exit Lane', ...zones[2].centroid, note: null }],
};
const config = {
  target_fps: 3,
  frame_width: 640,
  jpeg_quality: 0.7,
  stale_after_s: 10,
  vapid_public_key: null,
  app_version: '0.0.0-mock',
  contract_version: '1.1.0',
};
const settings = {
  detect_conf: 0.25,
  smoothing_window: 5,
  debounce_s: 3,
  clear_s: 8,
  hysteresis_ratio: 0.85,
  cooldown_s: 60,
  escalation_s: 60,
  stale_after_s: 10,
  reraise_after_s: 60,
  target_fps: 3,
  frame_width: 640,
  jpeg_quality: 0.7,
  default_warning_density: 3,
  default_critical_density: 4,
  help_info: help,
};
const frame = {
  source_id: 1,
  seq: 1,
  ok: true,
  count: 2,
  boxes: [
    [0.1, 0.1, 0.3, 0.9, 0.91],
    [0.5, 0.2, 0.7, 0.9, 0.88],
  ],
  infer_ms: 45,
  smoothed_count: 2,
  density: 0.08,
  level: 'SAFE',
};
const analytics = {
  from: time,
  to: '2026-11-25T10:15:30Z',
  alerts_by_zone: [
    { zone_id: 1, zone_name: 'Main Gate', warning: 0, critical: 1 },
  ],
  avg_ack_seconds: null,
  avg_resolve_seconds: null,
  timezone: 'Asia/Kolkata',
  peak_hours: [
    { zone_id: 1, zone_name: 'Main Gate', hour: 15, avg_density: 0.24 },
  ],
  reports_by_status: { PENDING: 2, VERIFIED: 0, DISMISSED: 0 },
};
const list = (data) => ({
  data,
  pagination: {
    total: data.length,
    page: 1,
    limit: 20,
    total_pages: Math.ceil(data.length / 20),
  },
});
const fixtures = {
  user: users[0],
  person_ref: person,
  lat_lng: zones[0].centroid,
  polygon_geometry: zones[0].geometry,
  thresholds: {
    warning_density: 3,
    critical_density: 4,
    warning_count: 3,
    critical_count: 5,
  },
  zone_state_public: pub[0],
  zone_state: zones[0],
  zone: Object.fromEntries(
    Object.entries(zones[0]).filter(
      ([k]) =>
        ![
          'level',
          'trend',
          'count',
          'density',
          'sources',
          'open_alert_id',
          'live_updated_at',
        ].includes(k),
    ),
  ),
  source_info: zones[0].sources[0],
  alert,
  alert_detail: { ...alert, events },
  alert_event: events[0],
  advisory,
  report_crowd: crowd,
  report_sos: report,
  report_new: report,
  frame_result: frame,
  frame_result_source_in_use: {
    ...frame,
    ok: false,
    error: 'SOURCE_IN_USE',
    count: 0,
    boxes: [],
    smoothed_count: null,
    density: null,
    level: null,
  },
  config,
  settings,
  help_info: help,
  analytics_summary: analytics,
  health: {
    status: 'ok',
    db: 'ok',
    detector: 'ready',
    worker_alive: true,
    version: '0.0.0-mock',
  },
  error_validation: {
    error: {
      code: 'VALIDATION_ERROR',
      message: 'Check the highlighted fields.',
      details: { name: ['Name is required.'] },
    },
  },
  error_forbidden: {
    error: {
      code: 'FORBIDDEN',
      message: 'This role cannot perform this action.',
    },
  },
  error_method_not_allowed: {
    error: { code: 'METHOD_NOT_ALLOWED', message: 'Method not allowed.' },
  },
  zones_live: { data: pub },
  zones: { data: zones },
  sources: { data: zones.flatMap((z) => z.sources) },
  zone_public_detail: { data: { state: pub[0], alternatives: [] } },
  alerts_list: list([alert]),
  users_list: list(users),
  reports_list: list([report, crowd]),
  advisories: { data: [advisory] },
  history: { data: [{ ts: time, count: 6, density: 0.24, level: 'CRITICAL' }] },
  history_point: { ts: time, count: 6, density: 0.24, level: 'CRITICAL' },
  audit_log: {
    id: 1,
    actor: person,
    action: 'ALERT_RESOLVED',
    entity_type: 'alert',
    entity_id: 11,
    data: {},
    created_at: time,
  },
  hello: { role: null, server_time: time, contract_version: '1.1.0' },
  alert_escalated: { alert, reason: 'LEVEL_UP' },
  advisory_retracted: { id: 1 },
  source_status: {
    source_id: 1,
    zone_id: 1,
    status: 'OFFLINE',
    last_frame_at: null,
  },
  auth_expired: {},
};
fixtures.audit_logs_list = list([fixtures.audit_log]);
for (const [name, value] of Object.entries(fixtures)) save(name, value);
