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
```

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
