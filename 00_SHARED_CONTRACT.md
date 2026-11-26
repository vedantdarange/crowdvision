# 00 — Shared Contract: Crowd Safety Monitor

> **Contract version:** `1.1.0` (see the Changelog in section 15)
> **Read this file first.** It is the single source of truth between the two people (and their two AIs).
> `01_BACKEND_PLAN.md` = Person A's AI. `02_FRONTEND_PLAN.md` = Person B's AI.
> If this file and a plan disagree, **this file wins**. If this file is wrong, fix it through the change process in §2.5 — never work around it.

---

## 0. How to use these documents

| Who | Reads | Owns |
|---|---|---|
| Person A + AI-A ("Backend & Detection") | 00 + 01 | `/backend`, `/eval`, backend half of `/contract` review |
| Person B + AI-B ("Frontend & UX") | 00 + 02 | `/frontend`, `/contract/examples`, `/contract/types.ts`, mock server |
| Both | 00 | `/docs` (decisions, demo runbook), `/scripts` shared tooling |

**Every AI session starts with:** (1) read `00_SHARED_CONTRACT.md`, (2) read your own plan, (3) read your `STATUS_*.md` file, (4) read `/docs/DECISIONS.md`. **Every session ends with:** update your `STATUS_*.md` (done / in progress / blocked / next / questions for the other side).

---

## 1. Project snapshot

**Problem.** At large public gatherings in India, authorities lack real-time density information, so overcrowding is noticed too late and stampedes follow.

**Solution (college mini-project).** A web app (mobile-first, desktop OK) where camera sources (laptop webcam, uploaded demo videos, citizen photos) are analysed by a YOLOv8n person detector. The server turns detections into per-zone **people/m² density**, applies smoothing + hysteresis, raises **Warning/Critical alerts**, and pushes them to police (live over WebSocket and as background Web Push). Citizens see a read-only live status map and can submit crowd reports and SOS requests. Admins draw zones on a map and configure everything.

**Roles:** `citizen` (public viewing needs no login) · `police` · `admin` (superset of police).

**Non-goals (do not build):** facial recognition, storing video/photos, SMS/Telegram, multi-city scaling, native apps, RTSP/CCTV ingest, crowd-counting (density-map) models. These are "future work" slides only.

**Privacy rules (hard):** frames and photos are processed in RAM and discarded (never written to disk, including temporary files created by the web framework's upload parser); only numbers (count, density, level, boxes in the live response) are kept. No face recognition. Citizen reports store a count, location, optional note and the reporter's user id, never the image; report rows are deleted after `REPORT_RETENTION_DAYS` (default 30).

**Fixed decisions (already agreed):**

| Topic | Decision |
|---|---|
| Thresholds (default) | SAFE < 3.0, WARNING 3.0–<4.0, CRITICAL ≥ 4.0 people/m² (editable per zone) |
| Simple demo mode | Per-zone `mode: "COUNT"` uses count thresholds instead (e.g. 8 / 10) |
| DB | SQLite (WAL) |
| Push | Web Push (VAPID) is core, in addition to in-app alerts |
| Zones | Drawn as polygons on a map by admin |
| Citizen reports | Core feature |
| Backend | Flask + Flask-SocketIO (threading) + separate detection worker process |
| Frontend | Vite + React 19 + TypeScript (strict) + Tailwind v4 + shadcn/ui |
| Maps | MapLibre GL JS + OpenFreeMap tiles; Terra Draw for drawing; Turf for area |
| Licence | Repo is public under **AGPL-3.0** (Ultralytics requirement) |
| Occupancy count | Number of person detections with confidence ≥ `detect_conf` after NMS in each frame. A tracker is **not** used for the count (confirmed-track counts undercount at ~3 FPS and low confidence); tracking is optional (`USE_TRACKER=false` default) and only for analytics |
| Display time zone | Asia/Kolkata (IST, UTC+5:30); API timestamps stay UTC |

---

## 2. Collaboration protocol

### 2.1 Repository layout (monorepo)

```
crowd-safety/
├─ 00_SHARED_CONTRACT.md          # this file (copy into /docs too)
├─ 01_BACKEND_PLAN.md
├─ 02_FRONTEND_PLAN.md
├─ STATUS_BACKEND.md              # AI-A handoff notes (updated every session)
├─ STATUS_FRONTEND.md             # AI-B handoff notes
├─ LICENSE                        # AGPL-3.0
├─ README.md
├─ contract/
│  ├─ CONTRACT_VERSION            # "1.1.0"
│  ├─ types.ts                    # TypeScript types = §5 (AI-B maintains)
│  └─ examples/                   # JSON fixtures (see §2.4)
├─ backend/                       # Flask app (AI-A only)
├─ frontend/                      # Vite React app (AI-B only)
├─ eval/                          # counting + latency evaluation (AI-A)
├─ scripts/                       # seed_demo, run_demo, tunnel notes (shared)
└─ docs/
   ├─ DECISIONS.md                # one-paragraph ADR per decision
   ├─ DEMO.md                     # demo runbook (§13)
   └─ model/best.pt               # NOT committed if large; see backend plan
```

### 2.2 Ownership rules
- AI-A never edits `/frontend`. AI-B never edits `/backend`.
- `/contract` is edited only through §2.5.
- A bug in the other side's code is reported in the other side's `STATUS_*.md` "Requests from the other side" section, not fixed directly.

### 2.3 Git workflow
- `main` is always runnable. Work on branches `be/<topic>` and `fe/<topic>`. Small PRs (≤ ~400 lines of change where possible).
- **Each human reviews the other human's PRs** (read the diff, run it). AI review is a bonus, not a substitute.
- Conventional commits: `feat(be): …`, `fix(fe): …`, `docs(contract): …`.
- Never commit secrets. `.env` is git-ignored; `.env.example` lists every variable.
- Large files (model weights, demo videos) are **not** committed; share via a drive link in `docs/DEMO.md`.

### 2.4 Contract-first with fixtures
- `contract/examples/` holds one JSON fixture per response/event shape, named after §5/§6/§7 (e.g. `zone_state_public.json`, `alert.json`, `frame_result.json`, `error_validation.json`).
- **Backend tests** assert real responses match the fixture's *shape* (keys and types).
- **Frontend mock server and tests** are driven by the same fixtures.
- Result: both sides can work independently and integrate with few surprises.

### 2.5 Contract change process
1. Whoever needs a change opens a PR touching `contract/` + this file, titled `contract: <what>`, and describes impact on both sides.
2. **Both humans approve.** Bump `contract/CONTRACT_VERSION` (patch for clarifications/additive optional fields, minor for new endpoints/events, major for breaking changes).
3. Update fixtures and `types.ts` in the same PR.
4. Add a line to `docs/DECISIONS.md`.
5. Additive, optional fields are always safe; renames and removals are breaking — avoid.

### 2.6 AI working agreements (paste into both AIs' context)
1. Do not invent endpoints, fields, enum values, or event names. If the contract lacks something, stop and raise a contract change.
2. Prefer the simplest thing that satisfies the contract. This is a mini-project; do not add libraries not listed in your plan without asking the human.
3. Every PR includes tests for the logic it adds (see each plan's test section).
4. No `console.log` / bare `print` for diagnostics in committed code; use the logging approach in your plan.
5. At the end of every session update `STATUS_*.md` honestly, including what is untested.
6. Ask the human when a decision changes behaviour visible to the other side.

---

## 3. Enums (exact strings, case-sensitive)

| Name | Values |
|---|---|
| `Role` | `citizen`, `police`, `admin` |
| `Level` | `SAFE`, `WARNING`, `CRITICAL`, `NO_DATA` |
| `Trend` | `RISING`, `STEADY`, `FALLING` |
| `MetricMode` | `DENSITY`, `COUNT` |
| `AlertStatus` | `NEW`, `ACKNOWLEDGED`, `RESPONDING`, `RESOLVED`, `AUTO_CLEARED` |
| `AlertEventType` | `CREATED`, `ESCALATED`, `REMINDER`, `ACKNOWLEDGED`, `RESPONDING`, `RESOLVED`, `AUTO_CLEARED`, `REOPENED`, `FEED_LOST`, `FEED_RESTORED`, `NOTE` |
| `SourceKind` | `WEBCAM`, `VIDEO_FILE` |
| `SourceStatus` | `ONLINE`, `OFFLINE` |
| `ReportKind` | `CROWD`, `SOS` |
| `ReportStatus` | `PENDING`, `VERIFIED`, `DISMISSED` |
| `SosType` | `MEDICAL`, `CRUSH_RISK`, `FIRE`, `LOST_CHILD`, `OTHER` |
| `AdvisorySeverity` | `INFO`, `WARNING`, `URGENT` |

Level colour semantics (UI): SAFE green, WARNING amber, CRITICAL red, NO_DATA grey. **Never colour alone** — always pair with a text label and an icon.

---

## 4. Domain rules (the "crux" — backend implements, frontend must understand)

### 4.1 Counting and density
- A **source** produces a raw person count per processed frame (current occupancy; a person staying in view is **not** re-counted across frames). The raw count is the number of person detections with confidence ≥ `detect_conf` after NMS in that frame; tracker confirmation is never required.
- Per source: `smoothed_count = median(last N raw counts)` (N = `smoothing_window`, default 5).
- `source_density = smoothed_count / source.coverage_area_m2`. `coverage_area_m2` defaults to the zone's `area_m2` and can be lowered by the admin when the camera sees only part of the zone.
- **Multiple sources in one zone are never added.** Zone metric = **max** over sources that are `ONLINE`.
- `mode = DENSITY` → metric is density (people/m²). `mode = COUNT` → metric is `smoothed_count` (demo mode).

### 4.2 Level, hysteresis, debounce
Let `W`, `C` be the zone's warning/critical thresholds (density or count per mode), `h = hysteresis_ratio` (default 0.85).

| Current level | Moves up when | Moves down when |
|---|---|---|
| SAFE | metric ≥ W → WARNING; metric ≥ C → CRITICAL | — |
| WARNING | metric ≥ C → CRITICAL | metric < W·h → SAFE |
| CRITICAL | — | metric < C·h → WARNING (or SAFE if also < W·h) |

- A candidate level must hold continuously for `debounce_s` (default **3 s**) before moving **up**, and for `clear_s` (default **8 s**) before moving **down**. The timer resets whenever the candidate changes.
- **NO_DATA:** if no source of the zone sent a frame within `stale_after_s` (default **10 s**), the zone becomes `NO_DATA` immediately (never shown as "0 people" / safe). When data returns from NO_DATA, the first confirmed level is applied immediately (no debounce). NO_DATA never clears an alert condition (see 4.3).
- **Trend:** change of the metric over the last 60 s — `RISING` if ≥ +0.3 people/m² (or ≥ +2 people in COUNT mode), `FALLING` if ≤ the negative of that, else `STEADY`.

### 4.3 Alert lifecycle
- Entering WARNING or CRITICAL (confirmed) creates an **Alert** (`NEW`, `condition_active = true`) unless the zone already has an **open** alert (`NEW`/`ACKNOWLEDGED`/`RESPONDING`):
  - open alert with `condition_active = false` → **reopened** (`REOPENED` event, `condition_active = true`, `condition_cleared_at = null`);
  - open alert with `condition_active = true` (for example after `NO_DATA` or a server restart) → **no new alert**: update level and peaks, and write `ESCALATED` if the level rose.
  - There is never more than one open alert per zone. At boot the engine loads each zone's open alert from the database.
- WARNING → CRITICAL on an open alert: `level` changes, `peak_*` update, `ESCALATED` event.
- Back to SAFE: `condition_active = false`, `condition_cleared_at` set. If status is still `NEW` **and `peak_level` is `WARNING`** it becomes `AUTO_CLEARED` (final). A `NEW` alert whose peak was `CRITICAL` is never auto-cleared: it stays open (shown as "condition cleared, awaiting review") until police acknowledge or resolve it. If someone had acknowledged/responded, it also stays open until police `resolve` it.
- **NO_DATA while an alert is open:** the alert stays open and `condition_active` is unchanged. A `FEED_LOST` event is written once when the zone becomes `NO_DATA`, and `FEED_RESTORED` when data returns. Reminders continue while `condition_active = true`.
- Unacknowledged CRITICAL alert with `condition_active = true`: `REMINDER` event + re-push every `escalation_s` (default **60 s**).
- Push cooldown: at most one WARNING push per zone per `cooldown_s` (default **60 s**). A WARNING→CRITICAL escalation, an alert created or reopened **at CRITICAL**, and reminders always push.
- Manual transitions (police/admin): `NEW → ACKNOWLEDGED → RESPONDING → RESOLVED`; `NEW → RESPONDING` allowed; any non-final state → `RESOLVED`. Repeating the same transition is a harmless no-op (200). Anything else = `409 INVALID_TRANSITION`.
- **Resolve while still over threshold:** allowed (police may have dealt with it), but if the zone is still WARNING/CRITICAL `reraise_after_s` (setting, default **60 s**) after the resolve, a **new** alert is created (`CREATED` event with `data.reason = "STILL_ACTIVE_AFTER_RESOLVE"` and `data.previous_alert_id`). A zone must never stay red with no open alert.

### 4.4 Citizen reports
- A crowd report (photo + GPS) is detected once on the server, the image is discarded, and a **hint** (`count`, `density_hint` if the zone is known) is stored. Reports **never** create or escalate alerts by themselves; police verify or dismiss them.
- GPS point is matched to the zone polygon containing it (`zone_id` null if none).

---

## 5. Data shapes (TypeScript, snake_case on the wire)

```ts
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
```

---

## 6. REST API v1

### 6.1 Conventions
- **Base path:** `/api/v1`. JSON UTF-8. Timestamps ISO-8601 UTC with `Z`. IDs are integers. Field names are `snake_case`.
- **Auth:** `Authorization: Bearer <access_token>`. Refresh endpoint uses the **refresh token** in the same header.
- **Token trust:** the token proves identity only. On every authenticated request the server loads the user and uses the **database** role and `is_active` (a disabled or demoted user loses access immediately; a disabled user gets `403 FORBIDDEN`).
- **Success:** `200`/`201` with `{ "data": … }`; lists that are paginated also include `"pagination"`. Deletes return `204` with no body.
- **Errors:** always `{ "error": { "code", "message", "details"? } }`.
- **Pagination:** `?page=1&limit=20` (default 20, max 100). Sorting where relevant: `sort=-created_at`.
- **Roles legend:** `P` public · `C` citizen+ (any logged-in user) · `Po` police+admin · `A` admin only.
- **Rate limits (HTTP 429, code `RATE_LIMITED`):** register 10/h/IP · login 20/min/IP · crowd report 1/min/user · SOS 3/10 min/user.
- **Client IP:** in the demo the app sits behind a tunnel/proxy, so the server must honour the trusted proxy's forwarded address (`TRUSTED_PROXY_COUNT`, Werkzeug `ProxyFix`) before keying IP rate limits; otherwise every visitor shares one limit.
- **Common error codes:** `401 UNAUTHENTICATED` (missing/expired token) · `403 FORBIDDEN` (wrong role) · `422 VALIDATION_ERROR` (`details` = `{field: [messages]}`) · `400 BAD_REQUEST` (malformed JSON) · `404 NOT_FOUND` · `405 METHOD_NOT_ALLOWED` · `409 CONFLICT` / `INVALID_TRANSITION` · `413 PAYLOAD_TOO_LARGE` · `503 DETECTOR_UNAVAILABLE`. Only deviations are listed per endpoint below.

### 6.2 Endpoints

#### Auth
| Method & path | Role | Request | Success | Notes / errors |
|---|---|---|---|---|
| `POST /auth/register` | P | `{name, email, password}` (password ≥ 8) | `201 {data:{user, access_token, refresh_token, expires_in}}` | Always creates `citizen`. `409 CONFLICT` email taken. |
| `POST /auth/login` | P | `{email, password}` | `200 {data:{user, access_token, refresh_token, expires_in}}` | `401 UNAUTHENTICATED` with generic message; disabled user → `403 FORBIDDEN`. |
| `POST /auth/refresh` | refresh token | — | `200 {data:{access_token, expires_in}}` | Expired refresh → `401`. |
| `GET /auth/me` | C | — | `200 {data: User}` | |

Token lifetimes: access 60 min, refresh 7 days. There is no server logout; the client discards tokens.

#### Users
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `GET /users` | A | `?role=&is_active=&q=&page&limit` | `200 ApiList<User>` | |
| `POST /users` | A | `{name, email, password, role: 'police'\|'admin'}` | `201 {data: User}` | `409` email taken. Audit `USER_CREATED`. |
| `PATCH /users/{id}` | A | any of `{name, role, is_active, password}` | `200 {data: User}` | Cannot disable or demote yourself → `409 CONFLICT`. |

#### Zones
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `GET /zones/live` | P | — | `200 {data: PublicZoneState[]}` | Active zones only. |
| `GET /zones/{id}/public` | P | — | `200 {data:{state: PublicZoneState, alternatives: PublicZoneState[]}}` | `alternatives` = up to 3 nearest `SAFE` zones (by centroid distance). |
| `GET /zones` | Po | — | `200 {data: ZoneState[]}` | Includes inactive when `?include_inactive=true` (admin). |
| `GET /zones/{id}` | Po | — | `200 {data: ZoneState}` | |
| `POST /zones` | A | `{name, description?, geometry, area_m2, mode?, warning_density?, critical_density?, warning_count?, critical_count?}` | `201 {data: ZoneState}` | `geometry` valid closed Polygon; the server recomputes the area from the polygon (local equirectangular projection) and stores that value, and returns `422` if the client's `area_m2` differs by more than 10 %; `1 ≤ area_m2 ≤ 10_000_000`; `warning < critical`; COUNT mode requires both counts; name unique among **active** zones. |
| `PATCH /zones/{id}` | A | any subset of the POST fields + `is_active` | `200 {data: ZoneState}` | Audit `ZONE_UPDATED`. |
| `DELETE /zones/{id}` | A | — | `204` | Soft delete (`is_active=false`); frees the name for reuse. `409 CONFLICT` while the zone has an open alert (resolve it first). |
| `GET /zones/{id}/history` | Po | `?from&to&bucket_s=10` (bucket ∈ 10, 60, 300) | `200 {data: HistoryPoint[]}` | Default last 30 min; max 5000 points. |

#### Sources
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `GET /sources` | Po | `?zone_id=` | `200 {data: SourceInfo[]}` | |
| `POST /sources` | Po | `{zone_id, name, kind, coverage_area_m2?}` | `201 {data: SourceInfo}` | `coverage_area_m2` defaults to the zone area and may only be sent by an **admin** (police sending it → `403 FORBIDDEN`); allowed range `1 ≤ coverage ≤ zone area × 2`. |
| `PATCH /sources/{id}` | A | `{name?, coverage_area_m2?, is_active?}` | `200 {data: SourceInfo}` | |
| `DELETE /sources/{id}` | A | — | `204` | Soft delete. |

#### Alerts
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `GET /alerts` | Po | `?status=NEW,ACKNOWLEDGED&level=&zone_id=&from=&to=&active=true&page&limit&sort=-created_at` | `200 ApiList<Alert>` | `active=true` → status not in (`RESOLVED`,`AUTO_CLEARED`). |
| `GET /alerts/{id}` | Po | — | `200 {data: AlertDetail}` | |
| `POST /alerts/{id}/acknowledge` | Po | `{note?}` | `200 {data: Alert}` | `409 INVALID_TRANSITION`. Audit + realtime `alert:updated`. |
| `POST /alerts/{id}/respond` | Po | `{note?}` | `200 {data: Alert}` | |
| `POST /alerts/{id}/resolve` | Po | `{note?}` | `200 {data: Alert}` | Allowed even while the condition is still active; see the re-raise rule in 4.3. |

#### Advisories
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `GET /advisories` | P | `?zone_id=` | `200 {data: Advisory[]}` | Active, non-expired. Global ones always included; with `zone_id` also that zone's. Newest first. |
| `POST /advisories` | Po | `{title, body, severity, zone_id?, expires_at?}` | `201 {data: Advisory}` | Realtime `advisory:new`. |
| `DELETE /advisories/{id}` | Po | — | `204` | Retract. Realtime `advisory:retracted`. |

#### Reports
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `POST /reports/crowd` | C | `multipart/form-data`: `image` (JPEG/PNG ≤ 5 MB), `lat`, `lng`, `note?` | `201 {data: Report}` | Detects once, discards the image (memory only, never a temp file). `503 DETECTOR_UNAVAILABLE` when the detector is down or its queue is full; `413`. Rate limited. |
| `POST /reports/sos` | C | `{sos_type, lat, lng, note?}` | `201 {data: Report}` | Rate limited. |
| `GET /reports/mine` | C | `?page&limit` | `200 ApiList<Report>` | |
| `GET /reports` | Po | `?kind=&status=&zone_id=&page&limit` | `200 ApiList<Report>` | |
| `PATCH /reports/{id}` | Po | `{status: 'VERIFIED'\|'DISMISSED', review_note?}` | `200 {data: Report}` | Only from `PENDING`, else `409 INVALID_TRANSITION`. |

#### Push
| Method & path | Role | Request | Success | Notes |
|---|---|---|---|---|
| `POST /push/subscriptions` | Po | `{endpoint, keys:{p256dh, auth}}` | `201 {data:{id}}` | Upsert by `endpoint`. |
| `DELETE /push/subscriptions` | Po | `?endpoint=<url-encoded>` | `204` | |
| `POST /push/test` | Po | — | `200 {data:{sent: number}}` | Sends a test push to the caller's subscriptions. |

#### Config, settings, help, analytics, audit, health
| Method & path | Role | Success | Notes |
|---|---|---|---|
| `GET /config` | P | `{data: RuntimeConfig}` | Frontend reads this on boot. |
| `GET /help-info` | P | `{data: HelpInfo}` | |
| `GET /settings` | A | `{data: Settings}` | |
| `PATCH /settings` | A | `{data: Settings}` | Partial update; validated ranges; audit `SETTINGS_UPDATED`. |
| `GET /analytics/summary?from&to` | Po | `{data: AnalyticsSummary}` | Default: last 24 h. Peak hours are bucketed in IST. |
| `GET /analytics/export/alerts.csv?from&to` | A | `text/csv` | Columns: id, zone, level, peak_level, status, peak_density, peak_count, created_at, acknowledged_at, resolved_at. |
| `GET /audit-logs?page&limit&action=&actor_id=` | A | `ApiList<AuditLog>` | |
| `GET /health` | P | `{status:'ok', db:'ok', detector:'ready'\|'loading'\|'unavailable', worker_alive:boolean, version:string}` | Served at `/api/v1/health`. |

Audit `action` values: `USER_CREATED USER_UPDATED ZONE_CREATED ZONE_UPDATED ZONE_DELETED SOURCE_CREATED SOURCE_UPDATED SOURCE_DELETED SETTINGS_UPDATED ALERT_ACKNOWLEDGED ALERT_RESPONDING ALERT_RESOLVED ADVISORY_CREATED ADVISORY_RETRACTED REPORT_REVIEWED`.

---

## 7. Realtime contract (Socket.IO v4, default namespace `/`, path `/socket.io`)

### 7.1 Connection and rooms
- Client connects with `io({ auth: { token } })`; `token` is optional (anonymous = public viewer).
- Server rooms: every client joins `public`. Authenticated clients also join `user:{id}`, and `role:police` (police **and** admin) and/or `role:admin`. There are no per-zone rooms.
- If a token is present but invalid or expired, the server still accepts the connection as public and emits `auth:expired`. The client refreshes its token and reconnects.
- **Session freshness:** the server remembers each authenticated socket's token expiry and user id. A 1 Hz task (and every `frame:submit`) checks that the token has not expired and that the user is still active with the same role. On expiry, disable or demotion the server removes the socket from the privileged rooms, emits `auth:expired` and disconnects it; the client refreshes the token and reconnects. A socket must never keep police privileges beyond its token.
- After every (re)connect the server emits `hello` `{ role: Role | null, server_time: ISODateTime, contract_version: string }`. **The client must refetch REST data for every query it cares about on every `hello`** (Socket.IO is at-most-once; missed events are expected).

### 7.2 Server → client events
| Event | Room(s) | Payload | When |
|---|---|---|---|
| `zone:update` | `public` | `PublicZoneState` | Level or trend change, density change ≥ 0.1, or ≥ 2 s since last emit; max 1/s/zone. |
| `zone:detail` | `role:police` | `ZoneState` | Same triggers as `zone:update`. |
| `alert:new` | `role:police` | `Alert` | New alert. |
| `alert:updated` | `role:police` | `Alert` | Any status/level/peak change. |
| `alert:escalated` | `role:police` | `{ alert: Alert, reason: 'LEVEL_UP' \| 'CRITICAL_UNACKNOWLEDGED' }` | Escalation or reminder. Triggers siren/push on the client. |
| `advisory:new` | `public` | `Advisory` | |
| `advisory:retracted` | `public` | `{ id: number }` | Retracted by police **or expired** (the server emits it when `expires_at` passes). |
| `report:new` | `role:police` | `Report` | For `SOS` reports clients treat this like an alert (banner + siren for CRUSH_RISK/FIRE/MEDICAL); the server also sends Web Push (section 9). |
| `report:updated` | `role:police`, `user:{owner}` | `Report` | After review. |
| `source:status` | `role:police` | `{ source_id, zone_id, status: SourceStatus, last_frame_at }` | Source goes ONLINE/OFFLINE. |
| `frame:result` | **sender only** | see §8 | Response to `frame:submit`. |
| `hello` | sender | see above | On connect. |
| `auth:expired` | sender | `{}` | Bad/expired token. |

### 7.3 Client → server events
| Event | Role | Payload |
|---|---|---|
| `frame:submit` | police/admin | see §8 |

---

## 8. Frame pipeline contract

**Source of frames:** the *browser*. A webcam stream or an uploaded demo video plays in a `<video>` element; a script draws frames onto a canvas (default width 640) and sends them as JPEG.

```ts
// client -> server (Socket.IO binary attachment)
interface FrameSubmit {
  source_id: number;
  seq: number;                 // increments per source per session, starts at 1
  captured_at: ISODateTime;
  reset?: boolean;             // true on the first frame of a (re)started stream or when a video loops; clears that source's smoothing buffer (and tracker, if enabled)
  width: number; height: number;   // pixel size of the JPEG
  image: ArrayBuffer;          // JPEG bytes, quality ≈ 0.7 (never PNG/WebP)
}

// server -> sender only, event "frame:result"
interface FrameResult {
  source_id: number; seq: number;
  ok: boolean;
  error?: 'FORBIDDEN' | 'UNKNOWN_SOURCE' | 'BAD_IMAGE' | 'DETECTOR_BUSY' | 'DETECTOR_UNAVAILABLE' | 'SOURCE_IN_USE';
  count: number;                                   // raw count of THIS source's frame (not smoothed)
  boxes: [number, number, number, number, number][]; // [x1,y1,x2,y2,conf], normalised 0..1
  infer_ms: number;
  smoothed_count: number | null; density: number | null; level: Level | null; // ZONE-level state (zone metric after smoothing and max), for the HUD
}
```

**Pacing rules (client):** at most **1 frame in flight per source**. Send the next frame only after the matching `frame:result` arrives **or** 2 s pass (timeout), and not faster than `1000 / target_fps` ms (read from `/config`, default 3 FPS). No frames while the tab is hidden unless a video source is deliberately running.
**Server rules:** drops frames from unknown/inactive sources (`UNKNOWN_SOURCE`), from non-police roles (`FORBIDDEN`), and when the detector queue is full (`DETECTOR_BUSY`) — dropping is normal, not an error. A source is `ONLINE` while frames arrive within `stale_after_s`. **One streamer per source:** the first socket to send a frame for a source holds a lease that expires `stale_after_s` after its last frame or when it disconnects; frames from any other socket get `SOURCE_IN_USE`. Pending frames are tracked per `(socket, source_id, seq)`.
**Latency target (laptop, 640 px):** p95 capture→`frame:result` < 1.5 s.

---

## 9. Web Push contract
- VAPID public key comes from `GET /config` (`vapid_public_key`; `null` = push disabled).
- Alert payload (JSON): `{ "kind": "ALERT", "title": "CRITICAL — Main Gate", "body": "4.6 people/m² (peak). Tap to respond.", "url": "/police/alerts/12", "tag": "alert-12", "level": "CRITICAL", "alert_id": 12, "zone_id": 3 }`.
- SOS payload: `{ "kind": "SOS", "title": "SOS — Crush risk", "body": "Reported near Main Gate. Tap to review.", "url": "/police/reports?focus=45", "tag": "sos-45", "level": "CRITICAL", "report_id": 45, "zone_id": 3 }` (`zone_id` may be null). Sent immediately, no cooldown, for `CRUSH_RISK`, `FIRE` and `MEDICAL`; `LOST_CHILD` and `OTHER` are in-app only.
- Server sends with `ttl = 600` and `Urgency: high`. Stale subscriptions (HTTP 404/410) are deleted by the server.
- Service worker shows the notification (`showNotification`, with `tag` so repeats replace each other) and on click focuses/opens `url`.
- Only police/admin subscribe in v1.

---

## 10. Runtime topology, ports, environment

| Mode | How it runs |
|---|---|
| **Dev** | Flask `:5000`; Vite `:5173` proxies `/api` and `/socket.io` (with `ws: true`) to Flask. Mock mode: `frontend/mock-server` on `:5001` replaces Flask. |
| **Demo** | `npm run build` → Flask serves `frontend/dist` (SPA fallback) at `:5000`. One origin. `cloudflared tunnel --url http://localhost:5000` gives HTTPS for phone camera + Web Push. |

Phone camera and Web Push **require HTTPS**; `localhost` is allowed on the laptop only.

Backend env (`backend/.env.example` is authoritative): `FLASK_ENV`, `DATABASE_URL=sqlite:///instance/app.db`, `SECRET_KEY`, `JWT_SECRET_KEY`, `MODEL_PATH`, `DETECTOR_BACKEND=fake|ultralytics`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT=mailto:you@example.com`, `SERVE_FRONTEND=false`, `CORS_ORIGINS=http://localhost:5173`, `SENTRY_DSN=` (optional), `DEMO_CENTER=<lat>,<lng>` (set to your demo venue — used only by the seed script), `SEED_PASSWORD` (local dev only), `ALLOW_DEFAULT_PASSWORDS=false`, `TRUSTED_PROXY_COUNT=1`, `USE_TRACKER=false`, `REPORT_RETENTION_DAYS=30`.
Frontend env: `VITE_API_BASE=/api/v1`, `VITE_USE_MOCKS=0|1`.

---

## 11. Seed data (dev/demo only; seed script refuses when `FLASK_ENV=production`)

| Account | Email | Password | Role |
|---|---|---|---|
| Admin | `admin@demo.local` | `SEED_PASSWORD` | admin |
| Police 1 | `police1@demo.local` | `SEED_PASSWORD` | police |
| Police 2 | `police2@demo.local` | `SEED_PASSWORD` | police |
| Citizen | `citizen@demo.local` | `SEED_PASSWORD` | citizen |

Passwords come from the `SEED_PASSWORD` environment variable; if it is not set the seed script generates a random password per account and prints it once. `.env.example` may set `SEED_PASSWORD=Demo@1234` for **local development only**. `flask set-password <email>` changes a password. Because the demo is exposed to the internet through the tunnel, the server refuses to start with `SERVE_FRONTEND=true` while an admin account still accepts the default password (override: `ALLOW_DEFAULT_PASSWORDS=true`).

Seed zones (3 small polygons around `DEMO_CENTER`), chosen so every demo path is reachable with few people or a crowd video:
- **Main Gate** (area ≈ 40 m²): `COUNT` mode, warning 3 / critical 5; one `WEBCAM` source (coverage 25 m²).
- **Stage Area** (≈ 120 m²): `COUNT` mode, warning 8 / critical 10; one `VIDEO_FILE` source (coverage 60 m²).
- **Exit Lane** (≈ 25 m²): `DENSITY` mode, 3.0 / 4.0 people/m²; one `VIDEO_FILE` source with `coverage_area_m2 = 6` (about 18 people reach Warning). This zone demonstrates the density story. Seed default settings and `help_info` with the standard Indian emergency numbers (112 unified, 100 police, 102 ambulance, 101 fire).

---

## 12. Integration milestones and dependencies

| Milestone | Backend delivers | Frontend delivers | Joint check |
|---|---|---|---|
| **M0 Contract freeze** (day 1–2) | Skeleton runs; `/health`; fixtures reviewed | Scaffold, mock server runs from fixtures | Both humans sign off this file |
| **M1 Auth** | register/login/refresh/me, RBAC, users | Login/register, guards, role navigation | Login as each seed user on real backend |
| **M2 Zones + public map** | Zones/sources/settings/config/help CRUD; `/zones/live`; Socket.IO connect + `hello` | Public live map, zone detail, help, advisories read | Map shows seeded zones as NO_DATA |
| **M3 Live engine** | Zone engine + alerts + fake feed script + alert endpoints + advisories write | Police dashboard, alert queue/detail/actions, alert banner + siren | `scripts/fake_feed` ramps a zone to CRITICAL; police sees alert, acknowledges, resolves |
| **M4 Real detection** | Detector worker + `frame:submit` pipeline | Webcam + video monitor with overlay and HUD | Webcam count matches people on screen; latency within target |
| **M5 Push** | Web Push + reminders | Service worker, subscription, "Arm alerts" | Locked Android phone buzzes on CRITICAL |
| **M6 Citizen** | Reports (crowd, SOS), review | Report screens, my-reports, police review queue, advisory broadcast | End-to-end SOS from citizen to police |
| **M7 Admin** | Analytics, CSV, audit, history | Zone map editor, sources, users, settings, analytics, audit | Admin draws a zone → area saved → shows on public map |
| **M8 Hardening** | Evaluation scripts, soak test | A11y/responsive polish, e2e demo run | Full demo rehearsed twice |

**Phase dependency map:** F1←B1 · F2←B2 (+B3 for live data) · F3←B4 (mock until then) · F4←B5 (mock until then) · F5←B6 · F6←B7 (+B4 for advisories) · F7←B2 + B8.
Suggested pacing over 5 weeks: W1 M0–M1, W2 M2–M3, W3 M4–M5, W4 M6–M7, W5 M8 + report/PPT.

---

## 13. Definition of done and demo runbook

**Per feature:** matches the contract · tests written and passing · no secrets/console noise · works at 360 px width · keyboard-reachable (frontend) · `STATUS_*.md` updated · reviewed by the other human.

**Demo script (≈ 6 min, `docs/DEMO.md` expands it):**
1. Citizen phone opens the public map (HTTPS tunnel): all zones green/grey.
2. Police laptop logged in; press **Arm alerts** (unlocks sound + notifications). Android phone also logged in as police with push enabled.
3. Start the webcam source in *Main Gate* (COUNT mode, warning 3 / critical 5): 2 people → SAFE; a third person → WARNING alert; five → CRITICAL → siren, banner, phone vibrates and buzzes (locked screen). The admin can change the thresholds live from the zone editor. For the density story use *Exit Lane* (DENSITY mode) with a crowd video.
4. Police acknowledges → responding → resolves. Broadcast an advisory; the citizen phone shows it live.
5. Citizen sends an SOS and a crowd photo; police verifies one.
6. Admin shows analytics (alerts per zone, response times) and the audit log.
7. Mention limits (dense occlusion → undercount; future: density-map model, RTSP).

**Evaluation (backend owns, shared in the report):** counting MAE/RMSE on 10–20 labelled images (ShanghaiTech B / Mall subset, ≤ 100 people) · alert latency (count crosses threshold → alert on second device) · false/missed alert counts on a labelled video · effect of smoothing on flicker · raw-detection count versus tracker count on the same video (justifies not using a tracker for occupancy).

---

## 14. Assumptions to confirm early (put answers in `docs/DECISIONS.md`)
1. Hysteresis ratio is `0.85` (supersedes the earlier "80 %" idea) — gives clear points of 2.55 and 3.4 people/m² at default thresholds.
2. Device for push demo is an Android phone with Chrome; iPhone Safari support is best-effort (PWA installed to home screen only).
3. Access tokens live in `localStorage` (accepted XSS trade-off for a student project; documented in the report).
4. Citizen accounts use email + password (no phone/OTP).
5. Time zone is stored/returned in UTC; the UI formats to the browser's local time. Peak-hour analytics are bucketed in IST.
6. Occupancy uses raw detections, not tracker-confirmed tracks (decision made after reading the tracker source; revisit only if evaluation shows a clear gain).
7. Resolving an alert while the zone is still over the limit is allowed and re-raises after `reraise_after_s` (default 60 s).
8. SOS reports of type CRUSH_RISK, FIRE and MEDICAL trigger Web Push and a siren banner for police; LOST_CHILD and OTHER are in-app only.
9. Only WARNING-peak alerts auto-clear; a CRITICAL-peak alert needs a human to acknowledge or resolve it.

---

## 15. Changelog

**1.1.0** — review fixes (made before any implementation, so renames are safe):
- Occupancy is the raw detection count; tracker optional (`USE_TRACKER`). Citizen uploads must never touch disk (framework spooling), report rows expire.
- Alert lifecycle: no duplicate when an alert is open with active condition; `NO_DATA` never clears; `FEED_LOST`/`FEED_RESTORED` events; CRITICAL-peak alerts are not auto-cleared; resolve-while-active re-raises (`reraise_after_s` setting); reopen at CRITICAL always pushes.
- Frame pipeline: one streamer per source (`SOURCE_IN_USE`), pending frames keyed by socket; `frame:result` HUD fields are zone-level; `reset` also clears the smoothing buffer.
- Security: role and `is_active` re-read from the database on every request; sockets lose privileges when the token expires or the user is disabled/demoted; `zone:subscribe` removed; proxy-aware rate limiting; seed passwords from the environment and a startup check against default passwords.
- SOS: Web Push and banner for CRUSH_RISK, FIRE and MEDICAL; push payload gains `kind`, `report_id`.
- Data: `ZoneState.live_updated_at` replaces `updated_at`; server recomputes zone area; `coverage_area_m2` admin-only; zone delete blocked while an alert is open; zone names unique among active zones; advisories expiring emit `advisory:retracted`; analytics peak hours in IST (`timezone` field); `METHOD_NOT_ALLOWED` error code.
- Seed zones changed so the demo reaches Warning/Critical with few people (Main Gate and Stage Area in COUNT mode, Exit Lane in DENSITY mode).
- Fixed the phase dependency map in section 12 (it was off by one against the plans).

**1.0.0** — initial contract.
