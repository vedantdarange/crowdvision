# 01 — Backend Implementation Plan (Person A + AI-A)

> **Scope:** everything under `/backend`, `/eval`, and review of `/contract`.
> **Prerequisite:** read `00_SHARED_CONTRACT.md` completely. It defines every endpoint, event, enum and rule you must implement. This plan tells you *how* and *in what order*.

---

## 0. Kickoff prompt (paste at the start of every AI-A session)

```
You are AI-A, the backend + detection engineer for the "Crowd Safety Monitor" college project
(Flask + Flask-SocketIO + YOLOv8n + SQLite). Person A is your human.
1. Read 00_SHARED_CONTRACT.md, then 01_BACKEND_PLAN.md, then STATUS_BACKEND.md, then docs/DECISIONS.md.
2. Work on exactly one phase at a time (B0..B9). Follow the phase's tasks, files and acceptance criteria.
3. Never edit /frontend. Never invent endpoints/fields/events: if the contract is missing something, stop and
   propose a contract change (contract §2.5).
4. Layering is strict: routes (thin) -> services (rules) -> repositories (queries) -> models. The zone/alert
   engine is pure Python with no Flask imports.
5. Write tests with the code. Run them. Report what you ran and the results.
6. At the end, update STATUS_BACKEND.md (done / in progress / blocked / next / requests for AI-B).
Skills to apply: backend-architect, backend-dev-guidelines, api-endpoint-builder, api-designer.
```

---

## 1. Responsibilities

1. Flask REST API v1 exactly as in contract §6 (auth, RBAC, zones, sources, alerts, advisories, reports, push, settings, analytics, audit, health).
2. Socket.IO server (rooms, `hello`, event emission) exactly as in contract §7.
3. Detection pipeline: receive frames, run YOLOv8n in a **separate process**, count person detections per frame (tracker optional, off by default), return `frame:result` (contract §8).
4. **Zone engine**: smoothing, density, hysteresis, debounce, trend, stale detection, alert state machine (contract §4).
5. Web Push (VAPID) and escalation reminders.
6. SQLite persistence, migrations, seed script, retention.
7. Evaluation scripts (`/eval`) and the fake feed tool the frontend relies on.
8. Serving the built frontend in demo mode.

---

## 2. Skill guidance translated to Flask

The backend skills assume Node/Express/Prisma. We keep the **rules** and use the Flask equivalent:

| Skill rule | Our Flask equivalent |
|---|---|
| Layered: routes → controllers → services → repositories | Blueprint view functions act as **thin controllers** (parse → call service → respond) → `services/` → `repositories/` → `models/` |
| Validate all input (Zod) | **Pydantic v2** schemas in `schemas/`; one `validate(model, data)` helper raising `ValidationAppError` |
| Unified config, never read env directly | `app/config.py` is the **only** place that reads `os.environ`; everything else imports `settings` |
| Central error handling, custom errors | `core/errors.py` `AppError` hierarchy + one global handler producing the contract error envelope |
| Dependency injection | Services receive repositories via constructor; wiring in `app/container.py` (no globals inside services) |
| Observability (Sentry for every error) | Structured JSON logging with a request id; **optional** Sentry via `SENTRY_DSN` (free tier); `/health` |
| Testing: unit + integration, edge cases | pytest; engine unit tests with an injected clock; API tests with Flask test client and in-memory SQLite |
| API design: versioned, pagination, consistent envelopes, status codes | Contract §6 (`/api/v1`, `{data}`/`{data,pagination}`/`{error}`) |
| Security: auth, rate limits, no sensitive data in errors | JWT + argon2; Flask-Limiter; generic login error; no stack traces in responses |

---

## 3. Backend risk assessment (BFRI) and what it forces

`BFRI = (Architecture Fit + Testability) − (Complexity + Data Risk + Operational Risk)`, each 1–5. Higher is safer. 0–2 = risky → isolate behind an interface and test heavily. < 0 = dangerous → redesign before coding.

| Module | A | T | C | D | O | BFRI (naive) | Action | BFRI (after) |
|---|---|---|---|---|---|---|---|---|
| Auth / RBAC | 5 | 5 | 2 | 3 | 3 | 2 | Use proven libs; role-matrix tests for every route | 5+5−(2+2+2) = 4 |
| Zone/Source/Settings CRUD | 5 | 5 | 1 | 2 | 1 | 6 | Straight CRUD | 6 |
| **Frame pipeline (worker process)** | 3 | 2 | 5 | 1 | 4 | **−5 dangerous** | **Redesign**: explicit message protocol, `FakeDetector`, bounded queue, drop-not-block; build fake first | 5+4−(3+1+3) = 2 |
| **Zone/alert engine** | 5 | 5 | 4 | 3 | 3 | 0 | Pure module, injected clock, table-driven tests | 5+5−(3+2+2) = 3 |
| Web Push | 4 | 3 | 3 | 1 | 3 | 0 | `Notifier` interface + `FakeNotifier`; delete dead subscriptions | 5+4−(3+1+2) = 3 |
| Citizen reports | 5 | 4 | 2 | 2 | 2 | 3 | Rate limits, discard image, tests | 3 |
| Analytics | 5 | 4 | 2 | 1 | 1 | 5 | SQL aggregates, tests on seeded data | 5 |

**Consequence for ordering:** build and test the engine and the fake detector *before* the real YOLO worker (phases B3–B4 before B5). The frame pipeline must not be started until the `Detector` interface, the worker message protocol, and `FakeDetector` exist.

---

## 4. Dependencies (`backend/requirements.txt`)

Only add libraries from this list without asking the human.

| Purpose | Package |
|---|---|
| Web | `Flask`, `Flask-Cors`, `gunicorn` (demo) |
| Realtime | `Flask-SocketIO`, `simple-websocket` (threading mode; **no eventlet/gevent**) |
| DB | `SQLAlchemy`, `Flask-SQLAlchemy`, `Flask-Migrate` |
| Validation | `pydantic` (v2) |
| Auth | `Flask-JWT-Extended`, `argon2-cffi` |
| Rate limit | `Flask-Limiter` |
| Detection | `ultralytics`, `opencv-python` (**not** `-headless`: Ultralytics pulls in `opencv-python` itself, and two OpenCV wheels in one environment clash), `numpy`, `supervision` (only for the `Detections` container; **`supervision` 0.32 has no ByteTrack**), CPU build of `torch` (install the `+cpu` wheel from the PyTorch CPU index) |
| Optional tracking | `trackers` (provides `ByteTrackTracker`) — install **only** if `USE_TRACKER=true` is wanted for analytics; not needed for the occupancy count |
| Optional speed-up | `openvino` or `onnxruntime` (after export; see B5) |
| Geometry | `shapely` (point-in-polygon). Zone area is recomputed with a local equirectangular projection (metres per degree at the polygon's latitude); no extra dependency |
| Push | `pywebpush`, `py-vapid` |
| Tests | `pytest`, `pytest-cov`, `freezegun` or your own injected clock |
| Eval | `scikit-learn` (MAE/RMSE), `pandas` (optional) |
| Observability | `python-json-logger` (or stdlib `logging` with a JSON formatter); optional `sentry-sdk` |

Pin versions in `requirements.txt` after the first successful install and run `pip check` (it must report no conflicts). Verify exact APIs against the installed versions — especially `pywebpush.webpush` and, only if the tracker is enabled, `trackers.ByteTrackTracker` (constructor arguments `lost_track_buffer`, `frame_rate`, `track_activation_threshold`, `minimum_consecutive_frames`, `minimum_iou_threshold`, `high_conf_det_threshold`).

---

## 5. Directory structure

```
backend/
├─ wsgi.py                      # creates app + socketio for gunicorn / dev
├─ requirements.txt  .env.example  pytest.ini
├─ migrations/                  # Flask-Migrate
├─ instance/                    # sqlite file (git-ignored)
├─ app/
│  ├─ __init__.py               # create_app(): config, extensions, blueprints, handlers, realtime, background tasks
│  ├─ config.py                 # ONLY place that reads env
│  ├─ extensions.py             # db, migrate, jwt, limiter, socketio, cors
│  ├─ container.py              # builds repositories + services (dependency injection)
│  ├─ core/
│  │  ├─ errors.py              # AppError, ValidationAppError, NotFound, Forbidden, Conflict, InvalidTransition...
│  │  ├─ responses.py           # ok(), created(), paginated(), no_content(), error_response()
│  │  ├─ auth.py                # roles_required(...) decorator, current_user()
│  │  ├─ logging.py             # JSON logging + request-id middleware
│  │  ├─ clock.py               # Clock protocol: SystemClock, FakeClock (tests)
│  │  └─ time.py                # to_iso_z(), utcnow()
│  ├─ models/                   # SQLAlchemy models (one file per table group)
│  ├─ schemas/                  # Pydantic request/response models
│  ├─ repositories/             # all queries; no business rules
│  ├─ services/                 # business rules: auth, users, zones, sources, alerts, advisories,
│  │                            #   reports, push, analytics, settings, audit
│  ├─ api/v1/                   # blueprints (thin): auth.py users.py zones.py sources.py alerts.py
│  │                            #   advisories.py reports.py push.py config.py analytics.py audit.py health.py
│  ├─ engine/                   # PURE PYTHON (no Flask/SQLAlchemy imports)
│  │  ├─ smoothing.py           # rolling median
│  │  ├─ zone_machine.py        # per-zone level state machine (hysteresis/debounce/NO_DATA/trend)
│  │  ├─ alert_rules.py         # decisions: create/reopen/escalate/clear/remind (returns "actions")
│  │  └─ zone_engine.py         # orchestrates sources -> zone metric -> machine -> actions
│  ├─ detection/
│  │  ├─ protocol.py            # dataclasses: DetectRequest, DetectResult, control messages
│  │  ├─ detector.py            # Detector interface; FakeDetector; UltralyticsDetector
│  │  ├─ worker.py              # separate-process loop (spawned)
│  │  ├─ manager.py             # DetectionManager: start/stop worker, queues, result pump thread
│  │  └─ model_loader.py        # loads best.pt (or exported model), warm-up
│  ├─ realtime/
│  │  ├─ events.py              # Socket.IO handlers: connect, disconnect, frame:submit (no per-zone subscribe events)
│  │  ├─ emitter.py             # emit_zone_update(), emit_alert_new(), ... (room routing, throttling)
│  │  └─ tasks.py               # 1 Hz tick: stale detection, reminders, re-raise checks, advisory expiry, stale-socket kick, sample persistence, retention
│  ├─ push/
│  │  ├─ notifier.py            # Notifier interface, WebPushNotifier, FakeNotifier
│  └─ cli.py                    # flask seed-demo, flask create-admin, flask set-password, flask fake-feed
├─ scripts/
│  └─ fake_feed.py              # drives the engine with scripted counts (for FE + demos)
└─ tests/
   ├─ unit/ (engine, smoothing, rules, schemas)
   ├─ integration/ (api per resource, role matrix, realtime)
   └─ fixtures/ (loads /contract/examples)
/eval/  eval_counting.py  eval_latency.py  README.md
```

---

## 6. Coding standards (enforced)

1. **Thin routes.** A view does: authenticate/authorize → validate input → call one service method → return an envelope. No SQL, no business rules.
2. **Services own rules and transactions.** They raise `AppError` subclasses; never return `(None, "error")` tuples.
3. **Repositories own queries.** Return model objects or plain dicts; no Flask objects.
4. **Engine is pure.** `app/engine/*` imports only the stdlib/`numpy` if needed. Time is injected via `Clock`. It returns **actions** (e.g. `CreateAlert`, `EmitZoneUpdate`, `SendPush`) that the caller applies — so rules are testable without a DB.
5. **One error envelope** (contract §6.1). Never leak stack traces or SQL in responses; log them with the request id.
6. **Config in one place.** `from app.config import settings`.
7. **Type hints everywhere**; `ruff`/`black` if the human wants them.
8. **UTC everywhere**; serialise with `to_iso_z()`.
9. **Audit** every privileged mutation listed in contract §6.2 via `AuditService.log(actor, action, entity, data)`.
10. **No `print`.** Use the logger.

### 6.1 Skeletons to follow

```python
# core/errors.py
class AppError(Exception):
    status = 500; code = "INTERNAL"
    def __init__(self, message="Something went wrong", details=None):
        super().__init__(message); self.message = message; self.details = details
class ValidationAppError(AppError): status, code = 422, "VALIDATION_ERROR"
class Unauthenticated(AppError): status, code = 401, "UNAUTHENTICATED"
class Forbidden(AppError): status, code = 403, "FORBIDDEN"
class NotFound(AppError): status, code = 404, "NOT_FOUND"
class Conflict(AppError): status, code = 409, "CONFLICT"
class InvalidTransition(AppError): status, code = 409, "INVALID_TRANSITION"
# + RateLimited(429), PayloadTooLarge(413), DetectorUnavailable(503), BadRequest(400), MethodNotAllowed(405, code METHOD_NOT_ALLOWED)

# one global handler -> {"error": {"code", "message", "details"?}}; unknown exceptions -> 500 INTERNAL + log

# core/auth.py
def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*a, **kw):
            # The token proves identity only. Re-read the user on EVERY request and trust the DB role,
            # so a disabled or demoted user loses access immediately (a stale role claim is ignored).
            user = user_repository.get(int(get_jwt_identity()))
            if user is None or not user.is_active: raise Forbidden()
            if user.role not in roles: raise Forbidden()
            g.current_user = user                 # current_user() reads this, never the claims
            return fn(*a, **kw)
        return wrapper
    return deco
# role hierarchy: admin satisfies any role set that includes "police"; encode this once in the helper.
# The same freshness rule applies to Socket.IO (section 8.3) and to /auth/refresh (re-check is_active).
```

```python
# extensions.py or db init: SQLite pragmas (REQUIRED, otherwise "database is locked")
@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL"); cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON"); cur.execute("PRAGMA synchronous=NORMAL"); cur.close()
```

```python
# JWT: identity must be a string; role lives in claims
create_access_token(identity=str(user.id), additional_claims={"role": user.role})
# Passwords: argon2.PasswordHasher().hash(pw) / .verify(hash, pw); never log passwords or tokens.
```

```python
# Behind the cloudflared tunnel every request arrives from the proxy. Without this, all visitors share one IP
# and the per-IP rate limits (register, login) lock everyone out after a few attempts.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count, x_host=settings.trusted_proxy_count)
# Limiter key: request.remote_addr (already the real client IP after ProxyFix). TRUSTED_PROXY_COUNT=1 for the tunnel, 0 for local dev.

# Citizen uploads must stay in memory. Werkzeug spools form-file parts larger than 500 KB to a temp file on disk
# (default_stream_factory -> SpooledTemporaryFile(max_size=500 KB)); override the factory so uploads never touch disk:
class MemoryRequest(flask.Request):
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return io.BytesIO()
app.request_class = MemoryRequest
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024   # reject bigger bodies early (413); verify the hook name on the installed Werkzeug/Flask
```

---

## 7. Data model (SQLite)

All timestamps stored as naive UTC `DATETIME`; serialised with `Z`. IDs are integer PKs. Use `CHECK` constraints for enums. Add indexes as listed.

| Table | Columns | Indexes / notes |
|---|---|---|
| `users` | id, name, email (unique, NOCASE), password_hash, role, is_active, created_at, updated_at | |
| `zones` | id, name, description, geometry_json (TEXT GeoJSON Polygon), centroid_lat, centroid_lng, area_m2, mode, warning_density, critical_density, warning_count NULL, critical_count NULL, is_active, created_at, updated_at | centroid and `area_m2` computed server-side (client value only cross-checked, 422 if > 10 % apart); **partial unique index** on `name` `WHERE is_active = 1` (so a soft-deleted zone frees its name) |
| `sources` | id, zone_id FK, name, kind, coverage_area_m2, is_active, created_by FK, created_at | idx(zone_id) |
| `zone_samples` | id, zone_id FK, ts, count, density, level | idx(zone_id, ts DESC); write ≤ 1 per 2 s per zone; keep 7 days |
| `alerts` | id, zone_id FK, level, peak_level, status, condition_active, peak_density, peak_count, created_at, acknowledged_at/by, responding_at/by, resolved_at/by, resolution_note, condition_cleared_at, last_escalated_at, last_push_at, reraise_check_at NULL, previous_alert_id NULL FK | idx(zone_id, created_at DESC), idx(status); **partial unique index** on `zone_id` `WHERE status IN ('NEW','ACKNOWLEDGED','RESPONDING')` (at most one open alert per zone, enforced by the database) |
| `alert_events` | id, alert_id FK, type, actor_id NULL, data_json, created_at | idx(alert_id, created_at) |
| `advisories` | id, title, body, severity, zone_id NULL, created_by FK, created_at, expires_at NULL, is_active | idx(is_active, created_at DESC) |
| `reports` | id, kind, status, zone_id NULL, lat, lng, count NULL, density_hint NULL, note NULL, sos_type NULL, created_by FK, created_at, reviewed_by NULL, reviewed_at NULL, review_note NULL | idx(status, created_at DESC), idx(created_by); rows deleted after `REPORT_RETENTION_DAYS` (default 30) by the retention job |
| `push_subscriptions` | id, user_id FK, endpoint (unique), p256dh, auth, user_agent, created_at, last_success_at NULL, failure_count | |
| `audit_logs` | id, actor_id NULL, action, entity_type, entity_id NULL, data_json, created_at | idx(created_at DESC) |
| `settings` | key (PK), value_json | defaults come from code, DB overrides |

---

## 8. Detailed specifications

### 8.1 Zone engine (pure, the crux)

**Inputs:** `ingest(source_id, raw_count, now)` and `tick(now)`; zone config (thresholds, mode, area), source config (coverage area), engine settings (`smoothing_window`, `debounce_s`, `clear_s`, `hysteresis_ratio`, `stale_after_s`, `cooldown_s`, `escalation_s`, `reraise_after_s`).

**Per-source state:** `deque(maxlen=N)` of raw counts, `last_frame_at`, `smoothed_count`, `density`.

**Zone metric:** over sources with `now - last_frame_at ≤ stale_after_s`: `max(density)` (DENSITY mode) or `max(smoothed_count)` (COUNT mode). No such source → `NO_DATA`.

**Level machine (per zone):**
```
state: level, pending_target, pending_since, metric_history (for trend)
def step(metric, now):
    if metric is None: level = NO_DATA; clear pending; return
    if level == NO_DATA: level = target_for_fresh(metric); clear pending; return   # no debounce after outage
    target = level
    if level == SAFE:
        target = CRITICAL if metric >= C else WARNING if metric >= W else SAFE
    elif level == WARNING:
        target = CRITICAL if metric >= C else SAFE if metric < W*h else WARNING
    elif level == CRITICAL:
        if metric < W*h: target = SAFE
        elif metric < C*h: target = WARNING
    if target == level: clear pending; return
    if target != pending_target: pending_target, pending_since = target, now
    hold = debounce_s if rank(target) > rank(level) else clear_s
    if now - pending_since >= hold: level = target; clear pending; emit transition(old, new)
```
`rank`: SAFE 0 < WARNING 1 < CRITICAL 2.

**Trend:** keep (t, metric) for 60 s; compare metric now vs the value ~60 s ago (or the oldest within the window); thresholds `+0.3` density / `+2` count (contract §4.2).

**Alert rules (`alert_rules.py`)** — input: transition + current open alert (or none) + clock; output: list of actions:
The engine is given, per zone, a read-only snapshot of the zone's **open alert** (id, status, level, `condition_active`, `peak_level`, `created_at`, `last_escalated_at`) or `None`. Decisions (contract §4.3):
- Transition to WARNING/CRITICAL and **no open alert** → `CreateAlert` (+ `SendPush`; a WARNING push respects `cooldown_s`, a CRITICAL push never does).
- Transition to WARNING/CRITICAL and an open alert with `condition_active=false` → `ReopenAlert` (`REOPENED` event, `condition_active=true`, `condition_cleared_at=null`; pushes if the new level is CRITICAL or the cooldown has passed).
- Transition to WARNING/CRITICAL and an open alert with `condition_active=true` (after `NO_DATA` or a restart) → **no new alert**; `UpdateAlert` for level/peaks, plus `ESCALATED` + push if the level rose.
- WARNING→CRITICAL on an open alert → `UpdateAlert(level=CRITICAL, event=ESCALATED)` + `SendPush` (+ `alert:escalated reason=LEVEL_UP`).
- Transition to SAFE → `ClearCondition`. If status is `NEW` **and `peak_level == WARNING`** → `AUTO_CLEARED`. A `NEW` alert with `peak_level == CRITICAL` stays open (UI: "condition cleared — awaiting review"). Acknowledged/responding alerts stay open.
- Transition to `NO_DATA` → never clears anything; write `FEED_LOST` once on the open alert (if any). When data returns → `FEED_RESTORED`, then normal rules with the first level applied immediately.
- `tick`: reminder if level `CRITICAL` + `condition_active=true` + status `NEW` + `now - max(created_at,last_escalated_at) ≥ escalation_s` → `Remind` (event `REMINDER`, push, `alert:escalated reason=CRITICAL_UNACKNOWLEDGED`).
- `tick` **re-raise check**: when `AlertService.resolve` runs while `condition_active=true` it stores `reraise_check_at = resolved_at + reraise_after_s`. In `tick`, for each resolved alert whose `reraise_check_at ≤ now`: if the zone is still WARNING/CRITICAL and has no open alert → `CreateAlert` (event `CREATED` with `data = {reason: "STILL_ACTIVE_AFTER_RESOLVE", previous_alert_id}`, push at CRITICAL); then clear `reraise_check_at`. A zone must never stay red without an open alert.
- Peak tracking: update `peak_density/peak_count/peak_level` whenever exceeded.

**Applying actions:** `AlertService.apply(actions)` runs inside one DB transaction, then the emitter sends realtime events and the notifier sends push **after commit** (never inside the transaction).

**Concurrency:** engine instance lives in the main process; guard `ingest`/`tick` with one `threading.Lock`. Engine loads zone/source config **and each zone's open alert** at boot (so a restart neither forgets alerts nor duplicates them), and reloads config on zone/source/settings changes (service calls `engine.reload()`). `reload()` must **preserve** smoothing buffers, levels and pending timers for zones/sources that still exist; it only adds, removes or updates config.

**Required unit tests (table-driven, with `FakeClock`):**
1. SAFE→WARNING only after `debounce_s`; a 1-frame spike does nothing.
2. Hysteresis: at W=3, metric 2.8 stays WARNING; 2.5 (<2.55) for `clear_s` → SAFE.
3. CRITICAL→WARNING→SAFE paths with holds; direct CRITICAL→SAFE.
4. Two sources: zone metric is the **max**, not the sum; one source going stale does not drop a zone that another source still reports.
5. All sources stale → `NO_DATA` immediately; recovery applies level immediately.
6. Alert created once; reopened (not duplicated) if the zone re-enters while the previous alert is `ACKNOWLEDGED`.
7. Escalation and reminder timing; cooldown suppresses repeated WARNING pushes.
8. COUNT mode with `W=8, C=10`.
9. Trend RISING/FALLING/STEADY.
10. Open alert with `condition_active=true` + zone returns from `NO_DATA` at WARNING/CRITICAL → no second alert (level/peaks updated, `FEED_RESTORED` written); a restart with a loaded open alert behaves the same.
11. `NO_DATA` while an alert is open: alert stays open, `condition_active` unchanged, exactly one `FEED_LOST` event; reminders keep going while the condition was active.
12. CRITICAL-peak alert in status `NEW` that falls back to SAFE is **not** auto-cleared; a WARNING-peak one is.
13. Resolve while still WARNING/CRITICAL → after `reraise_after_s` a new alert is created with `previous_alert_id`; if the zone went SAFE in between, nothing is created.
14. `engine.reload()` keeps smoothing buffers and levels; a tick never sends a reminder when `condition_active=false`.

### 8.2 Detection pipeline

**Architecture**
```
browser --frame:submit--> Socket.IO handler (main process, thread)
   validate role/source/size  ->  DetectionManager.submit(req)  -> mp.Queue (maxsize 16)
                                                    |
                                       WORKER PROCESS (spawned)
                       loads model once; predict (conf >= detect_conf, class person); count = number of boxes; optional per-source tracker (analytics only)
                                                    |
                              result mp.Queue -> pump thread in main process
   pump: emit frame:result to the sender sid (map (sid, source_id, seq)); engine.ingest(source_id, count)
```

**Rules**
- Start the worker with `multiprocessing.get_context("spawn")`. Do not use `fork` (torch + threads deadlock risk). The worker is started once from `create_app` (guard so it is not started twice by the Flask reloader: only when `WERKZEUG_RUN_MAIN == "true"` or when not in debug).
- Queue protocol lives in `detection/protocol.py` as plain dataclasses with primitive fields (JPEG as `bytes`, ids as ints, timestamps as floats) so it pickles cleanly:
  `DetectRequest(source_id, seq, jpeg: bytes, width, height, reset: bool, conf: float, imgsz: int, received_at: float)` →
  `DetectResult(source_id, seq, ok, error, boxes: list[tuple[float,float,float,float,float]], count: int, infer_ms: float)`; control: `Shutdown`, `ResetSource(source_id)`, `Ping` → `Pong`.
- **Never block** the main process: if `queue.Full`, immediately answer `frame:result {ok:false, error:'DETECTOR_BUSY'}`.
- **One streamer per source (lease):** the first socket that submits a frame for a `source_id` holds a lease (renewed by every frame, released on disconnect or after `stale_after_s` without frames). Frames for that source from any other socket get `frame:result {ok:false, error:'SOURCE_IN_USE'}` and are not queued. This prevents two tabs from interleaving frames and corrupting one source's smoothing buffer.
- **`reset=true`** clears that source's smoothing buffer in the engine (and the tracker, if enabled) so a looped video or restarted camera does not blend with old data.
- Worker: decode JPEG with OpenCV, `model.predict(frame, imgsz=640, conf=conf, classes=[0], verbose=False)`. **The count is the number of person boxes returned** (confidence ≥ `detect_conf`, after the model's NMS). Do **not** use tracker-confirmed tracks as the count. Reason (checked in the `trackers` 2.7.0 source): `ByteTrackTracker` only starts a track from a detection with confidence ≥ `track_activation_threshold` (default **0.7**), needs `minimum_consecutive_frames` (default 2) hits before a track gets an id, and scales its buffers for `frame_rate=30`; at ~3 FPS and `detect_conf` 0.35 it would silently undercount exactly when the crowd is dense and detections are weak. Smoothing (median over 5 frames, contract §4.1) already removes single-frame ghosts. `supervision` is used only as a `Detections` container (0.32 has no ByteTrack).
- **Optional tracker** (`USE_TRACKER=true`, default `false`): per-source `trackers.ByteTrackTracker(frame_rate=target_fps, track_activation_threshold=detect_conf, ...)` stored in a dict, used only for analytics/eval (e.g. the raw-vs-tracked comparison in B9). Reset the tracker on `reset=True` or after 30 s without frames for that source. It never changes the count sent to the engine.
- Normalise boxes to 0..1 by the frame size.
- Verify `model.names` — your single-class model should be class `0` = person; fall back to no class filter if needed.
- **Detector interface** (`detection/detector.py`): `class Detector(Protocol): def detect(self, frame, source_id, conf, imgsz) -> list[Box]`. Implementations: `FakeDetector` (returns a scripted/random count, no torch, used by tests, the fake feed and CI) and `UltralyticsDetector`. `DETECTOR_BACKEND=fake|ultralytics` chooses.
- Health: `/health` reports `detector`: `loading` until the worker answers `Pong` after warm-up, `ready`, or `unavailable` if the process died (supervisor thread restarts it up to 3 times with backoff).
- Pump thread uses `socketio.start_background_task`. Keep a small dict `inflight[(sid, source_id, seq)] = sent_at` with TTL cleanup (60 s) — keyed by socket too, so two clients can never receive each other's results. In `frame:result`, `count` is this source's raw count; `smoothed_count`, `density` and `level` are **zone-level** values read from the engine.
- Stale: a source is OFFLINE when no frame result for `stale_after_s`; the 1 Hz tick emits `source:status` on changes.
- **Speed-up (optional, after it works):** export `best.pt` to OpenVINO (Intel CPU) or ONNX and compare with `eval/eval_latency.py`. Remember FP16 weights do **not** run faster on CPU; the gain is from the compiled runtime. Keep the `.pt` path as the default if the export is awkward.
- **Calibration / tuning:** `detect_conf` default 0.35, `imgsz` 640. For distant people try 800–960 (slower). Do not lower `conf` below ~0.2.
- **AGPL:** keep the repo public; mention in README.

### 8.3 Realtime layer
- `SocketIO(app, async_mode="threading", cors_allowed_origins=settings.cors_origins)`.
- `connect(auth)`: decode JWT if present (use `flask_jwt_extended.decode_token`); load the user from the DB and require `is_active`; join `public`; if valid also `user:{id}`, `role:police` (police+admin), `role:admin` — based on the **DB role**. Invalid/expired/disabled → stay public and `emit('auth:expired')`. Always `emit('hello', {...})`.
- **Session registry:** `sessions[sid] = {user_id, role, token_exp}` (guarded by a lock). `tasks.py` checks it every second and again on each `frame:submit`: if the token has expired, or the user is disabled or no longer has that role, `leave_room` the privileged rooms, `emit('auth:expired', to=sid)` and `disconnect(sid)`. A socket never keeps police rights beyond its token. There are no `zone:subscribe`/per-zone rooms.
- `frame:submit`: check session freshness and role ∈ {police, admin}; source exists & active; JPEG size ≤ 300 KB and dimensions ≤ 1280 wide; source lease (`SOURCE_IN_USE`); then `DetectionManager.submit`.
- `emitter.py` centralises rooms and throttles `zone:*` (≤ 1/s/zone unless the level/trend changed). All payloads are built by the **same serializers** used by REST (`ZoneState`, `PublicZoneState`, `Alert`, …) so they cannot drift.
- `tasks.py` runs one background loop (every 1 s): `engine.tick(now)`; source online/offline; reminders; persist `zone_samples` (≤ 1 per 2 s per zone with data); hourly retention delete (`zone_samples` > 7 days, `reports` > `REPORT_RETENTION_DAYS`); advisory expiry (when `expires_at` passes: set inactive and emit `advisory:retracted {id}`); re-raise checks (§8.1); stale-socket kick (above). **Every background thread must run inside `app.app_context()`** (use one helper) or database access fails.

### 8.4 Web Push
- `Notifier` interface: `notify_alert(alert, reason)` and `notify_sos(report)` → `WebPushNotifier` loops through `push_subscriptions` of police/admin users. Payload shapes (with `kind: "ALERT"` or `"SOS"`, `report_id`) are in contract §9. `notify_sos` runs immediately with no cooldown for `CRUSH_RISK`, `FIRE` and `MEDICAL`; `LOST_CHILD` and `OTHER` are in-app only.
- Call: `webpush(subscription_info={endpoint, keys}, data=json_payload, vapid_private_key=KEY, vapid_claims={"sub": "mailto:…"}, ttl=600, headers={"Urgency": "high"})`.
  **Pitfalls:** build a **fresh** `vapid_claims` dict for every call (the library mutates it); `sub` must be a valid `mailto:` (Apple rejects `localhost`/malformed); a `ttl` of 0 drops messages for sleeping phones; delete the subscription on HTTP 404/410; count other failures and drop after 5 consecutive.
- Generate keys once with `py-vapid` (`vapid --gen`), store in `.env`, expose only the public key through `/config`.
- `POST /push/test` sends a harmless test message to the caller.
- `FakeNotifier` records calls for tests.

### 8.5 Citizen reports
- `POST /reports/crowd`: enforce content type, size ≤ 5 MB, read the file **from memory** (the `MemoryRequest` stream factory in §6.1; verify with a test that no temp file is created), decode with OpenCV; run one detection via the manager's **synchronous helper** (`manager.detect_once(jpeg, timeout=5s)`, uses a dedicated request id and no tracker); if the detector is down or its queue is full return `503 DETECTOR_UNAVAILABLE`; **drop the bytes**; match GPS to zone with shapely (`shape(geom).contains(Point(lng, lat))`); set `density_hint = count / zone.area_m2` when a zone matches; status `PENDING`; emit `report:new`.
- `POST /reports/sos`: validate enum + coordinates (lat −90..90, lng −180..180); emit `report:new`; for `CRUSH_RISK`, `FIRE`, `MEDICAL` call `notifier.notify_sos(report)` after commit.
- Review (`PATCH`) emits `report:updated` to police rooms and `user:{owner}`; audit `REPORT_REVIEWED`.
- Reports never touch the engine.

### 8.6 Analytics
- `alerts_by_zone`: counts of alerts per zone grouped by `peak_level` in the range.
- `avg_ack_seconds`: mean of `acknowledged_at − created_at` over acknowledged alerts; `avg_resolve_seconds` similar.
- `peak_hours`: from `zone_samples` average density per zone by **IST hour** (convert UTC → Asia/Kolkata, i.e. +5:30, before bucketing; a plain `hour + 5` is wrong), return the top hour per zone. The response carries `timezone: "Asia/Kolkata"`.
- Keep queries in a repository; test against seeded rows.

### 8.7 Demo-mode static serving
When `SERVE_FRONTEND=true`: serve `frontend/dist` with an SPA fallback (any non-`/api`, non-`/socket.io` path returns `index.html`); serve `sw.js` from the root with `Cache-Control: no-cache`.

**Startup safety check:** the demo is reachable from the internet through the tunnel. If `SERVE_FRONTEND=true` and any `admin` account still verifies against the default seed password, refuse to start with a clear message (override: `ALLOW_DEFAULT_PASSWORDS=true`). `flask seed-demo` takes passwords from `SEED_PASSWORD` or generates random ones and prints them once; `flask set-password <email>` changes a password.

---

## 9. Phases

Each phase lists **tasks → acceptance criteria → what the frontend can do after it**. Complete tests with each phase. Update `STATUS_BACKEND.md` when done.

### B0 — Scaffold and contract fixtures (day 1–2)
**Tasks:** create repo layout (§5); `create_app`, config, extensions, logging, error handlers, response helpers; SQLite pragma listener; models + first migration; `/api/v1/health`; pytest setup; `flask seed-demo` (passwords from `SEED_PASSWORD` or random, printed once; seed zones/modes as in contract §11) and `flask set-password <email>`; `ProxyFix` + `TRUSTED_PROXY_COUNT`; the partial unique indexes from §7; help AI-B produce `contract/examples/*.json` from the contract and write one test that checks a response against a fixture.
**Acceptance:** `flask run` works; `GET /api/v1/health` returns the contract shape; `pytest` passes; seed creates the 4 accounts + 3 zones + sources; fixtures reviewed by both humans (**M0**).
**Frontend can:** run against the mock server; real server only returns health.

### B1 — Auth, users, audit (**M1**)
**Tasks:** register/login/refresh/me; argon2; JWT with role claim (informational only); `roles_required` re-reads the user from the DB on every request (§6.1); `/auth/refresh` re-checks `is_active`; users endpoints; audit service; Flask-Limiter on auth routes; generic login errors.
**Acceptance:** role matrix test — every protected route returns 401 without a token and 403 for the wrong role; disabled user cannot log in; admin cannot disable/demote self; passwords never appear in logs/responses; a token issued before a user was disabled or demoted stops working on the next request; the login/register limiter keys on the real client IP (test with `X-Forwarded-For` and `TRUSTED_PROXY_COUNT=1`).
**Frontend can:** build login/register/guards against the real backend.

### B2 — Zones, sources, settings, config, help (**M2**)
**Tasks:** CRUD per contract; server-side centroid; validation (closed polygon, thresholds, area recomputed server-side with 422 on > 10 % mismatch, coverage 1..2× area and **admin-only**, name unique among active zones, `DELETE` → 409 while an alert is open); `GET /zones/live` and `/zones/{id}/public` (with nearest-SAFE alternatives; all NO_DATA until the engine runs); `/config`, `/settings`, `/help-info`; Socket.IO connect/rooms/`hello`/`auth:expired` and the session registry (§8.3); audit entries.
**Acceptance:** CRUD tests incl. validation failures; public endpoints never include counts/thresholds/sources (test asserts key set equals `PublicZoneState`); Socket.IO test connects anonymous / police / bad token and checks rooms and `hello`; police sending `coverage_area_m2` → 403; disabling a police user kicks their socket from the privileged rooms.
**Frontend can:** render the public map with seeded zones; connect realtime; read config.

### B3 — Fake feed (critical for collaboration) (**M3 part 1**)
**Tasks:** `Clock` abstraction; `FakeDetector`; `scripts/fake_feed.py` / `flask fake-feed --zone 1 --profile ramp` that calls the **same code path** as real frames (`DetectionManager` fake mode → engine) with scripted profiles: `ramp` (0→critical in ~60 s then back), `spike` (1-frame), `flap` (hovers near threshold), `offline` (stops sending).
**Acceptance:** running the profile produces `zone:update`/`zone:detail` events that a Socket.IO test client receives; documented in `README`.
**Frontend can:** see live-changing zones without a camera.

### B4 — Engine, alerts, advisories (**M3 part 2**) — heaviest
**Tasks:** implement §8.1 completely with all 14 unit tests listed (including the NO_DATA, restart, CRITICAL-no-auto-clear and re-raise cases); `AlertService.apply`; alert endpoints + transitions (`409 INVALID_TRANSITION`); alert events/timeline; realtime emission after commit; advisories endpoints (+ realtime); `/zones/{id}/history` once samples exist; `tasks.py` 1 Hz loop (reminders, re-raise checks, advisory expiry with `advisory:retracted`, stale-socket kick, `FEED_LOST`/`FEED_RESTORED`); load open alerts at boot.
**Acceptance:** all engine unit tests pass; integration test: fake `ramp` creates exactly one alert, escalates to CRITICAL, auto-clears when `NEW`; acknowledging prevents `AUTO_CLEARED`; reminder appears after `escalation_s` (use a fake clock); advisory create/retract and **expiry** emit events; a restart in the middle of an alert does not create a duplicate; resolving a still-active alert re-raises after `reraise_after_s`.
**Frontend can:** build the police dashboard, alert queue/detail/actions, alert banner.

### B5 — Real detector worker (**M4**)
**Tasks:** §8.2 end-to-end; `model_loader` with warm-up; spawn/supervise worker; `frame:submit` handler; `frame:result`; raw-detection count (tracker only if `USE_TRACKER=true`); per-source lease → `SOURCE_IN_USE`; busy/drop behaviour; `/health` detector status; `eval/eval_latency.py` skeleton; optional OpenVINO/ONNX export experiment documented in `docs/DECISIONS.md`.
**Acceptance:** with a real webcam (via the frontend) count tracks people in view within ±1–2 in easy scenes; p95 latency < 1.5 s at 640 px on the demo laptop (record the number); queue-full test returns `DETECTOR_BUSY` without blocking; killing the worker process is detected and restarted; no frame is ever written to disk (test greps for writes / temp files).
**Frontend can:** run the real monitor screen.

### B6 — Web Push and reminders (**M5**)
**Tasks:** §8.4; subscription endpoints; push on alert create/escalate/reminder with cooldown; `notify_sos` for `CRUSH_RISK`/`FIRE`/`MEDICAL`; `POST /push/test`; `FakeNotifier` tests; cleanup of dead subscriptions.
**Acceptance:** unit tests for cooldown rules; manual test: locked Android Chrome phone receives CRITICAL push within ~5 s; 410 deletes the subscription.
**Frontend can:** subscribe and show notifications.

### B7 — Citizen reports (**M6**)
**Tasks:** §8.5 (uploads read from memory, 503 when the detector is down/full, SOS push); rate limits; review endpoint; realtime events; report retention in the retention job.
**Acceptance:** rate-limit tests (429 with `RATE_LIMITED`); oversize upload → 413; wrong role → 403; GPS inside/outside zone cases; `report:new` reaches police only; a >500 KB upload creates no temp file (test); SOS `FIRE` triggers `FakeNotifier.notify_sos`, `OTHER` does not.
**Frontend can:** build citizen report screens and the police review queue.

### B8 — Analytics, export, history, demo serving (**M7**)
**Tasks:** §8.6 (IST peak hours, `timezone` field); CSV export; startup default-password check and `flask set-password` (§8.7); `/audit-logs`; retention job; static serving (§8.7); `scripts/run_demo` notes (gunicorn: `gunicorn -w 1 --threads 100 wsgi:app` — **one worker only**); document the cloudflared command.
**Acceptance:** analytics tests on seeded data; CSV opens in Excel; built frontend loads from Flask at `:5000`; deep links (e.g. `/police/alerts/3`) work via SPA fallback.
**Frontend can:** finish admin analytics/audit screens.

### B9 — Evaluation and hardening (**M8**)
**Tasks:** `eval/eval_counting.py` (MAE/RMSE on labelled images, prints a table + CSV), `eval/eval_latency.py` (alert latency, frame latency), flicker comparison with/without smoothing; raw-detection vs tracker-confirmed count on the same labelled video (record both in `docs/EVALUATION.md`); soak test (30 min fake feed + 1 real source, check memory and queue); fix leaks; update `README` (install, run, env, AGPL notice); freeze dependencies.
**Acceptance:** numbers recorded in `docs/EVALUATION.md` for the report; soak run shows no growing memory/queues; demo rehearsed twice with AI-B/Person B.

---

## 10. Testing plan

| Level | What | Tool |
|---|---|---|
| Unit | smoothing, zone machine, alert rules, schemas, geometry helpers, rate-limit keys | pytest + FakeClock |
| Integration | each resource's happy path + validation + auth/role matrix; realtime (Socket.IO test client) | Flask test client, in-memory SQLite |
| Contract | each real response/event matches the fixture's keys/types | pytest loading `/contract/examples` |
| Pipeline | FakeDetector end-to-end; queue-full; worker restart | pytest |
| Manual | real webcam, phone push, tunnel | checklist in `docs/DEMO.md` |

Target: the engine and alert rules are well covered (aim ≥ 90 % line coverage on `app/engine`); overall coverage is secondary to the role matrix and engine tests.

---

## 11. Observability and operations
- Structured JSON logs with `request_id`; log level via env; log every alert transition and push result (without personal data).
- `/api/v1/health` covers DB and detector status.
- Optional Sentry (`SENTRY_DSN`) capturing unhandled errors; never send request bodies or tokens.

## 12. Common pitfalls (read before coding)
1. **Do not** use eventlet/gevent; PyTorch/OpenCV freeze greenlet loops. Threading mode + one Gunicorn worker.
2. **Do not** run inference inside a Socket.IO handler.
3. **Do not** run more than one Gunicorn worker (in-memory engine/rooms).
4. SQLite needs the pragma listener; commit short transactions; avoid long-held write transactions in the 1 Hz loop.
5. `multiprocessing` on Windows spawns a fresh interpreter: the worker entry point must be importable and guarded by `if __name__ == "__main__"` where relevant; pass only picklable data.
6. Never emit realtime events or send push **inside** a DB transaction.
7. Flask debug reloader starts two processes: guard the worker start.
8. Browsers cache `sw.js`; serve with `no-cache`.
9. Do not store or log image bytes; do not add face recognition.
10. A silent camera is `NO_DATA`, never "0 people".
11. **Tracker undercount:** never use tracker-confirmed tracks as the occupancy count (activation threshold 0.7, confirmation delay, 30 FPS assumptions at ~3 FPS). Count detections; track only for analytics.
12. **Werkzeug spools uploads > 500 KB to disk.** Override the stream factory (§6.1) and test that no temp file appears — otherwise "images are never stored" is false.
13. **Proxy IP:** behind the tunnel `request.remote_addr` is the proxy. Use `ProxyFix` with `TRUSTED_PROXY_COUNT`, or every visitor shares one rate-limit bucket.
14. **App context in threads:** background tasks and the result pump need `app.app_context()`; otherwise DB calls fail only in the thread and look like random outages.
15. **`supervision` 0.32 has no ByteTrack** and installing both `opencv-python` and `opencv-python-headless` breaks imports. Use `opencv-python` only; run `pip check`.

## 13. `STATUS_BACKEND.md` template
```
# Backend status — updated <date/time>
## Phase: B_  (not started | in progress | done)
## Done since last update
## In progress
## Blocked / questions for Person A
## Requests for AI-B (frontend)
## Untested / known issues
## Next 3 steps
## Numbers (latency, MAE, coverage) once available
```
