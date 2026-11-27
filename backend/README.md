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

## Running Tests

```powershell
cd d:\crowdvision\backend
python -m pytest tests/ -v
```
