# Crowd Safety Monitor — Backend

Flask + Flask-SocketIO + SQLite backend for the Crowd Safety Monitor project.

## Setup & Database

Run all commands from `backend/`:

```powershell
cd d:\crowdvision\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set environment variables (or copy `.env.example` to `.env`):

```powershell
$env:FLASK_APP = "wsgi:app"
$env:DATABASE_URL = "sqlite:///instance/app.db"
$env:SEED_PASSWORD = "Demo@1234"
flask db upgrade
flask seed-demo
```

Run the API + Socket.IO development server:

```powershell
flask run --port 5000
# or (with WebSocket upgrade support on Windows/Linux):
python wsgi.py
```

## Demo Mode & Serving the Built Frontend

Build the frontend bundle first (`cd d:\crowdvision\frontend && npm run build`, producing `frontend/dist/`), then set in `backend/.env`:

```env
FLASK_ENV=production
SERVE_FRONTEND=true
TRUSTED_PROXY_COUNT=1
ALLOW_DEFAULT_PASSWORDS=false
```

### Startup Default-Password Safety Check
When `SERVE_FRONTEND=true`, the app refuses to start if any `admin` account still verifies against the default local seed password (`Demo@1234`), preventing accidental internet exposure through a tunnel.

Fix it before launching demo mode:

```powershell
flask set-password admin@demo.local
```

(Only set `ALLOW_DEFAULT_PASSWORDS=true` for isolated offline testing; never behind a public tunnel.)

### Running Demo Mode (Linux vs Windows)

**Linux / macOS (Gunicorn, 1 worker only):**

```bash
gunicorn -w 1 --threads 100 -b 0.0.0.0:5000 wsgi:app
```

- **Why `-w 1` (ONE worker only):** Live `ZoneEngine` state (smoothing windows, hysteresis, debounce, cooldown timers), `DetectionManager` (spawned YOLO subprocess, source stream leases, single-frame citizen report queue), `WebPushNotifier` bounded async queue, Socket.IO `sessions`/rooms, `Flask-Limiter` `memory://` buckets, and the `1 Hz` background loop all live inside the single Flask process. Running multiple Gunicorn workers (`-w > 1`) forks isolated copies of that state, spawns duplicate detector workers and `1 Hz` loops, breaks WebSocket room broadcasts/leases, and causes SQLite lock contention.
- **Gunicorn + Socket.IO + Detector Worker:** Passing `--threads 100` selects Gunicorn's `gthread` worker, which matches `Flask-SocketIO`'s `async_mode="threading"` and provides `environ["gunicorn.socket"]` to `simple-websocket` for full WebSocket upgrades. `DetectionManager` uses `multiprocessing.get_context("spawn")`, avoiding fork-after-threads issues with PyTorch/OpenCV/SQLAlchemy.

**Windows (where Gunicorn is not supported):**

Gunicorn relies on POSIX `fcntl`/signals and does not run on Windows (`gunicorn` is commented out in `requirements.txt` for Linux-only installs). Do **not** use `waitress`: Waitress does not expose a raw socket in `environ` for `simple-websocket`, which causes WebSocket upgrades to fail (`Cannot obtain socket from WSGI environment`).

Instead, run the threaded Werkzeug + Socket.IO server directly from `wsgi.py`:

```powershell
$env:FLASK_ENV = "production"
$env:SERVE_FRONTEND = "true"
python wsgi.py
```

`wsgi.py` runs `socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)` when `FLASK_ENV=production`, enabling full WebSockets (`werkzeug.socket`) and single-process `DetectionManager` spawning without the Werkzeug debugger or reloader.
- **Limits of `wsgi.py` on Windows:** It uses Werkzeug's single-process threaded WSGI server (not hardened for high-concurrency untrusted internet traffic and intended strictly for local/tunneled demo sessions with controlled concurrency).

### HTTPS Tunnel (`cloudflared`) for Phone Camera & Web Push

Phone camera streaming and Web Push require HTTPS outside `localhost`:

```powershell
cloudflared tunnel --url http://localhost:5000
```

Set `TRUSTED_PROXY_COUNT=1` so `ProxyFix` extracts real client IPs from `X-Forwarded-For` for rate limiting.

## Environment Variables (`backend/.env`)

See [backend/.env.example](.env.example) for defaults:
- **Core:** `FLASK_ENV` (`development` | `production`), `DATABASE_URL` (`sqlite:///instance/app.db`), `SECRET_KEY`, `JWT_SECRET_KEY`
- **Detection:** `DETECTOR_BACKEND` (`fake` | `ultralytics`), `MODEL_PATH` (`docs/model/best.pt`), `USE_TRACKER` (`false`)
- **Web Push:** `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (`mailto:<email>`)
- **Demo & Security:** `SERVE_FRONTEND` (`false` | `true`), `ALLOW_DEFAULT_PASSWORDS` (`false` | `true`), `TRUSTED_PROXY_COUNT` (`0` local | `1` behind `cloudflared`), `CORS_ORIGINS` (`http://localhost:5173`), `DEMO_CENTER`, `SEED_PASSWORD`
- **Retention & Rate Limits:** `REPORT_RETENTION_DAYS` (`30`), `RATE_LIMIT_REGISTER` (`10/hour`), `RATE_LIMIT_LOGIN` (`20/minute`), `RATE_LIMIT_REPORT_CROWD` (`1/minute`), `RATE_LIMIT_REPORT_SOS` (`3 per 10 minutes`), `SENTRY_DSN` (optional)

## Fake Feed (`flask fake-feed`)

Use `flask fake-feed` to simulate crowd density changes through `FakeDetector` -> `DetectionManager.ingest_count` -> `emitter` without a camera or PyTorch model:

```powershell
flask fake-feed --zone <id> --profile ramp|spike|flap|offline [--source <id>] [--speed 1.0]
```

Options:
- `--zone <id>`: Target active zone ID (required; `seed-demo` creates zones `1` Main Gate, `2` Stage Area, `3` Exit Lane).
- `--profile`:
  - `ramp`: linearly ramps from `0` to above `critical` and back down to `0` over ~60 s (scaled by `--speed`).
  - `spike`: baseline `0`, single-frame jump above `critical`, immediate return to `0`.
  - `flap`: oscillates just below and above the `warning` threshold.
  - `offline`: sends 0 frames so the zone remains/becomes stale (`NO_DATA`).
- `--source <id>`: Optional active source ID within the zone (defaults to the zone's first active source).
- `--speed <float>`: Playback speed multiplier (e.g. `--speed 5.0` runs 5x faster).
- `--serve`: Runs the HTTP + Socket.IO server in the same process on `--port` (default `5000`) while executing the profile in the background — useful for driving a connected browser before the multi-process frame pipeline is active.

Examples:

```powershell
# Run a 1-minute ramp on seeded Zone 1 (Main Gate, COUNT mode)
flask fake-feed --zone 1 --profile ramp

# Fast 5x flap test on Zone 3 (Exit Lane, DENSITY mode)
flask fake-feed --zone 3 --profile flap --speed 5.0

# Single-process live server + ramp for frontend integration
flask fake-feed --zone 1 --profile ramp --serve

# Or run the standalone script directly from backend/
python scripts/fake_feed.py --zone 1 --profile ramp
```

## Privacy, Upload Limits & Retention

- Live frames and citizen crowd photos (`POST /api/v1/reports/crowd`) are processed strictly in RAM (`MemoryRequest` overrides Werkzeug's upload stream factory so parts > 500 KB never spool to temporary files on disk) and image bytes are discarded immediately after single-frame inference.
- `MAX_CONTENT_LENGTH` caps `POST /api/v1/reports/crowd` at **5 MiB (5,242,880 bytes) for the entire `multipart/form-data` HTTP request** (including multipart boundaries, part headers, and `lat`/`lng`/`note` form fields). Any request exceeding 5 MiB total returns `413 PAYLOAD_TOO_LARGE`, so an image plus multipart framing must fit within 5,242,880 bytes (e.g. a 5,000,000-byte decimal 5 MB image fits easily, whereas a raw 5,242,880-byte file plus headers exceeds the total cap).
- Database `reports` rows store only derived counts, coordinates, optional notes, and reporter IDs (never images). The hourly background task automatically deletes `reports` older than `REPORT_RETENTION_DAYS` (default `30` days) and `zone_samples` older than `7` days.

## Running Tests

```powershell
cd d:\crowdvision\backend
python -m pytest tests/ -v
```
