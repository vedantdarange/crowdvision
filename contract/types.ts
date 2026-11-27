export type Role = 'citizen' | 'police' | 'admin';
export type Level = 'SAFE' | 'WARNING' | 'CRITICAL' | 'NO_DATA';
export type Trend = 'RISING' | 'STEADY' | 'FALLING';
export type MetricMode = 'DENSITY' | 'COUNT';
export type AlertStatus = 'NEW' | 'ACKNOWLEDGED' | 'RESPONDING' | 'RESOLVED' | 'AUTO_CLEARED';
export type AlertEventType = 'CREATED' | 'ESCALATED' | 'REMINDER' | 'ACKNOWLEDGED' | 'RESPONDING'
  | 'RESOLVED' | 'AUTO_CLEARED' | 'REOPENED' | 'FEED_LOST' | 'FEED_RESTORED' | 'NOTE';
export type SourceKind = 'WEBCAM' | 'VIDEO_FILE';
export type SourceStatus = 'ONLINE' | 'OFFLINE';
export type ReportKind = 'CROWD' | 'SOS';
export type ReportStatus = 'PENDING' | 'VERIFIED' | 'DISMISSED';
export type SosType = 'MEDICAL' | 'CRUSH_RISK' | 'FIRE' | 'LOST_CHILD' | 'OTHER';
export type AdvisorySeverity = 'INFO' | 'WARNING' | 'URGENT';

export type ISODateTime = string;            // "2026-11-24T10:15:30Z" (UTC, always with Z)
export interface LatLng { lat: number; lng: number }
export interface PersonRef { id: number; name: string }

/** GeoJSON Polygon, coordinates are [lng, lat], ring closed. */
export interface PolygonGeometry { type: 'Polygon'; coordinates: number[][][] }

export interface User {
  id: number; name: string; email: string; role: Role;
  is_active: boolean; created_at: ISODateTime;
}

export interface Thresholds {
  warning_density: number;          // people/m², default 3.0
  critical_density: number;         // people/m², default 4.0
  warning_count: number | null;     // used when mode = COUNT
  critical_count: number | null;
}

/** Zone configuration (police/admin). */
export interface Zone extends Thresholds {
  id: number; name: string; description: string;
  geometry: PolygonGeometry; centroid: LatLng;
  area_m2: number;                  // client suggests it (Turf); the server recomputes it from the polygon and stores ITS value
  mode: MetricMode;
  is_active: boolean; created_at: ISODateTime; updated_at: ISODateTime;
}

/** What a citizen / anonymous visitor may see. NEVER add counts, sources or thresholds here. */
export interface PublicZoneState {
  zone_id: number; name: string; geometry: PolygonGeometry; centroid: LatLng;
  level: Level; trend: Trend; density: number | null;  // 1 decimal; null when NO_DATA
  updated_at: ISODateTime | null;
}

export interface SourceInfo {
  id: number; zone_id: number; name: string; kind: SourceKind;
  coverage_area_m2: number; is_active: boolean;
  status: SourceStatus; last_frame_at: ISODateTime | null; created_at: ISODateTime;
}

/** Zone config + live state (police/admin). */
export interface ZoneState extends Zone {
  level: Level; trend: Trend;
  count: number | null; density: number | null;  // smoothed, zone metric
  sources: SourceInfo[];
  open_alert_id: number | null;
  live_updated_at: ISODateTime | null;   // last live-state change; null if the zone never had data (Zone.updated_at = config change time)
}

export interface Alert {
  id: number; zone_id: number; zone_name: string; location: LatLng;
  level: 'WARNING' | 'CRITICAL';           // current level
  peak_level: 'WARNING' | 'CRITICAL';
  status: AlertStatus; condition_active: boolean;
  peak_density: number; peak_count: number;
  created_at: ISODateTime;
  acknowledged_at: ISODateTime | null; acknowledged_by: PersonRef | null;
  responding_at: ISODateTime | null; responding_by: PersonRef | null;
  resolved_at: ISODateTime | null; resolved_by: PersonRef | null; resolution_note: string | null;
  condition_cleared_at: ISODateTime | null; last_escalated_at: ISODateTime | null;
}
export interface AlertEvent {
  id: number; alert_id: number; type: AlertEventType;
  actor: PersonRef | null; data: Record<string, unknown>; created_at: ISODateTime;
}
export interface AlertDetail extends Alert { events: AlertEvent[] }

export interface Advisory {
  id: number; title: string; body: string; severity: AdvisorySeverity;
  zone_id: number | null; zone_name: string | null;       // null = global
  created_by: PersonRef; created_at: ISODateTime; expires_at: ISODateTime | null; is_active: boolean;
}

export interface Report {
  id: number; kind: ReportKind; status: ReportStatus;
  zone_id: number | null; zone_name: string | null; lat: number; lng: number;
  count: number | null; density_hint: number | null;     // CROWD only
  sos_type: SosType | null; note: string | null;         // SOS only (note optional for both)
  created_by: PersonRef; created_at: ISODateTime;
  reviewed_by: PersonRef | null; reviewed_at: ISODateTime | null; review_note: string | null;
}

export interface HistoryPoint { ts: ISODateTime; count: number; density: number; level: Level }

export interface HelpInfo {
  emergency_numbers: { label: string; number: string }[];
  medical_points: { name: string; lat: number | null; lng: number | null; note: string | null }[];
  exits: { name: string; lat: number | null; lng: number | null; note: string | null }[];
}

export interface RuntimeConfig {
  target_fps: number; frame_width: number; jpeg_quality: number;   // e.g. 3, 640, 0.7
  stale_after_s: number; vapid_public_key: string | null;
  app_version: string; contract_version: string;
}

export interface Settings {
  detect_conf: number; smoothing_window: number; debounce_s: number; clear_s: number;
  hysteresis_ratio: number; cooldown_s: number; escalation_s: number; stale_after_s: number;
  reraise_after_s: number;          // delay before an alert resolved while still over threshold is raised again (default 60)
  target_fps: number; frame_width: number; jpeg_quality: number;
  default_warning_density: number; default_critical_density: number;
  help_info: HelpInfo;
}

export interface Pagination { total: number; page: number; limit: number; total_pages: number }
export interface ApiList<T> { data: T[]; pagination: Pagination }
export interface ApiOne<T> { data: T }
export interface ApiError {
  error: { code: ErrorCode; message: string; details?: Record<string, string[]> | Record<string, unknown> }
}
export type ErrorCode = 'BAD_REQUEST' | 'VALIDATION_ERROR' | 'UNAUTHENTICATED' | 'FORBIDDEN' | 'NOT_FOUND'
  | 'METHOD_NOT_ALLOWED' | 'CONFLICT' | 'INVALID_TRANSITION' | 'RATE_LIMITED' | 'PAYLOAD_TOO_LARGE' | 'DETECTOR_UNAVAILABLE' | 'INTERNAL';

export interface AuditLog {
  id: number; actor: PersonRef | null; action: string;
  entity_type: string; entity_id: number | null; data: Record<string, unknown>; created_at: ISODateTime;
}

export interface AnalyticsSummary {
  from: ISODateTime; to: ISODateTime;
  alerts_by_zone: { zone_id: number; zone_name: string; warning: number; critical: number }[];
  avg_ack_seconds: number | null; avg_resolve_seconds: number | null;
  timezone: 'Asia/Kolkata';
  peak_hours: { zone_id: number; zone_name: string; hour: number; avg_density: number }[]; // hour 0-23 in IST (UTC+5:30); the server converts before bucketing
  reports_by_status: Record<ReportStatus, number>;
}

// client -> server (Socket.IO binary attachment)
export interface FrameSubmit {
  source_id: number;
  seq: number;                 // increments per source per session, starts at 1
  captured_at: ISODateTime;
  reset?: boolean;             // true on the first frame of a (re)started stream or when a video loops; clears that source's smoothing buffer (and tracker, if enabled)
  width: number; height: number;   // pixel size of the JPEG
  image: ArrayBuffer;          // JPEG bytes, quality ≈ 0.7 (never PNG/WebP)
}

// server -> sender only, event "frame:result"
export interface FrameResult {
  source_id: number; seq: number;
  ok: boolean;
  error?: 'FORBIDDEN' | 'UNKNOWN_SOURCE' | 'BAD_IMAGE' | 'DETECTOR_BUSY' | 'DETECTOR_UNAVAILABLE' | 'SOURCE_IN_USE';
  count: number;                                   // raw count of THIS source's frame (not smoothed)
  boxes: [number, number, number, number, number][]; // [x1,y1,x2,y2,conf], normalised 0..1
  infer_ms: number;
  smoothed_count: number | null; density: number | null; level: Level | null; // ZONE-level state (zone metric after smoothing and max), for the HUD
}

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
