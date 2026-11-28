# CrowdVision — Real-Time Crowd Safety Monitor

Real-time crowd occupancy monitoring, threshold alerting, citizen reporting, and police dispatch web application built with **Flask + Flask-SocketIO + SQLite** on the backend, **React + TypeScript + Vite + Tailwind + MapLibre (PWA)** on the frontend, and **Ultralytics YOLO** running inside a spawned detection worker process.

## Architecture Overview

- **Backend (`backend/`)**: Single-process Flask + Flask-SocketIO (`threading` mode) REST API (`/api/v1`) and WebSocket push server, SQLite + SQLAlchemy 2 + Alembic, Argon2id + JWT authentication, Web Push (`pywebpush`), and a pure-Python `ZoneEngine` (5-frame rolling median smoothing, 0.85× hysteresis, 3 s trigger debounce, 8 s clear hold, and per-zone cooldown/escalation state machines).
- **Detection Worker (`backend/app/detection/`)**: Spawned `multiprocessing` (`spawn` context for Windows/CUDA safety) running `UltralyticsDetector` (COCO `person` class, tracker-free raw box counts sent to `ZoneEngine`) or deterministic `FakeDetector` for development/testing.
- **Frontend (`frontend/`)**: Role-scoped SPA + Service Worker PWA supporting Citizen public advisories & crowd/SOS reports, Police live monitor (webcam / video file streaming at capped frame rate + WebSocket overlay), Alert queue & advisory management, and Admin zone/source/user management.
- **Evaluation (`eval/`)**: Reproducible accuracy, latency, alert flicker, and memory/queue soak scripts; see [docs/EVALUATION.md](docs/EVALUATION.md).

---

## Quickstart & Installation

### 1. Backend Setup (`backend/`)

Python 3.11+ (tested on Python 3.13) is required. Run backend commands from `backend/`:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Optional (NVIDIA CUDA 12.6 GPU acceleration — install before requirements.txt):
# pip install torch==2.14.1+cu126 torchvision==0.29.1+cu126 --index-url https://download.pytorch.org/whl/cu126

pip install -r requirements.txt
pip check
```

Initialize the database and seed the 3 demo zones & accounts:

```powershell
Copy-Item .env.example .env
$env:FLASK_APP = "wsgi:app"
$env:DATABASE_URL = "sqlite:///instance/app.db"
$env:SEED_PASSWORD = "Demo@1234"
flask db upgrade
flask seed-demo
```

Seeded local accounts (when `SEED_PASSWORD=Demo@1234`):
- `admin@demo.local` (`admin`)
- `police1@demo.local`, `police2@demo.local` (`police`)
- `citizen@demo.local` (`citizen`)

Rotate seed passwords before serving behind any tunnel or demo network:

```powershell
flask set-password admin@demo.local
flask set-password police1@demo.local
```

### 2. Frontend Setup (`frontend/`)

Node.js **24 LTS** (`>=24.0.0`) is required:

```powershell
cd frontend
npm.cmd ci
Copy-Item .env.example .env
```

See [frontend/README.md](frontend/README.md) for mock mode (`VITE_USE_MOCKS=1`) and frontend verification scripts.

---

## Running the Application

### Development Mode (Two Terminals)

Terminal 1 — Backend (`backend/`):

```powershell
cd backend
$env:FLASK_APP = "wsgi:app"
$env:DETECTOR_BACKEND = "ultralytics"     # or "fake" without GPU/weights
$env:MODEL_PATH = "../people_model.pt"    # path to YOLO weights
python wsgi.py
```

Terminal 2 — Frontend (`frontend/`):

```powershell
cd frontend
$env:VITE_USE_MOCKS = "0"
npm.cmd run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/socket.io` to `http://127.0.0.1:5000`.

### Single-Origin Demo / Production Build

Build the frontend bundle so Flask serves both API/Socket.IO and static assets on port `5000`:

```powershell
cd frontend
$env:VITE_USE_MOCKS = "0"
$env:VITE_API_BASE = "/api/v1"
npm.cmd run build

cd ..\backend
$env:FLASK_ENV = "production"
$env:SERVE_FRONTEND = "true"
$env:CORS_ORIGINS = "http://localhost:5000"
$env:DETECTOR_BACKEND = "ultralytics"
$env:MODEL_PATH = "../people_model.pt"
# Note: change default admin password with `flask set-password admin@demo.local`
# unless running strictly offline with ALLOW_DEFAULT_PASSWORDS=true
python wsgi.py
```

> **Single-worker requirement:** Always run with **one** web worker process (`python wsgi.py` on Windows, or `gunicorn -w 1 --threads 100 -b 0.0.0.0:5000 wsgi:app` on Linux/macOS). Live `ZoneEngine` windows, source leases, and the spawned detector subprocess are stateful in-process. See [docs/DEMO.md](docs/DEMO.md) for the full live demo rehearsal & HTTPS tunnel (`cloudflared`) checklist.

---

## Environment Variables

All backend configuration is read in [`backend/app/config.py`](backend/app/config.py). Copy [`backend/.env.example`](backend/.env.example) to `backend/.env`:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `FLASK_ENV` | `development` | `development` \| `production` \| `testing` |
| `SECRET_KEY` / `JWT_SECRET_KEY` | dev defaults | Signing keys (required & validated non-default in production) |
| `DATABASE_URL` | `sqlite:///instance/app.db` | SQLite database URI |
| `DETECTOR_BACKEND` | `fake` | `ultralytics` \| `fake` |
| `MODEL_PATH` | `docs/model/best.pt` | Path to YOLO `.pt` weights (e.g., `../people_model.pt`) |
| `USE_TRACKER` | `false` | Optional `ByteTrackTracker` analytics hook (never alters count) |
| `SERVE_FRONTEND` | `false` | Serve `frontend/dist` from Flask; enforces non-default admin password |
| `ALLOW_DEFAULT_PASSWORDS` | `false` | Local offline bypass for startup seed-password check |
| `TRUSTED_PROXY_COUNT` | `0` | Set `1` behind `cloudflared` / reverse proxy for `ProxyFix` |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | unset | Web Push VAPID keys (`flask vapid-keys` generates a pair) |
| `DEMO_CENTER` | `28.6139,77.2090` | Default lat,lng center for `flask seed-demo` |
| `SEED_PASSWORD` | random once if unset | Initial demo account password (`Demo@1234` in `.env.example`) |
| `REPORT_RETENTION_DAYS` | `30` | Hourly pruning threshold for resolved citizen reports |
| `RATE_LIMIT_*` | `10/hour`, `20/minute`, `1/minute`, `3 per 10 minutes` | Register, login, crowd report, and SOS report rate limits |

---

## Evaluation & Verification

Run the backend test suite (unit + integration + RBAC role matrix):

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

Run the Phase B9 evaluation and soak benchmarks from the repository root:

```powershell
# Counting accuracy (MAE / RMSE / Mean Signed Error) + optional ByteTrack video comparison
backend\.venv\Scripts\python.exe eval/eval_counting.py --compare --video eval/data/crowd-photos-and-videos/crowd-video.mp4

# Frame inference, in-process e2e, and police alert delivery latency (p50 / p95)
backend\.venv\Scripts\python.exe eval/eval_latency.py --mode all --input eval/data/crowd-photos-and-videos/crowd-video.mp4

# False / missed alarms and smoothing/hysteresis/debounce flicker reduction
backend\.venv\Scripts\python.exe eval/eval_alerts.py --video eval/data/crowd-photos-and-videos/crowd-video.mp4

# 30-minute multi-zone + real-YOLO stability & leak soak test
backend\.venv\Scripts\python.exe eval/eval_soak.py --duration-s 1800 --sample-interval-s 10 --include-real
```

---

## License (AGPL-3.0 Notice)

This project integrates **Ultralytics YOLO** (`ultralytics`), which is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. In compliance with AGPL-3.0, this repository and any network-deployed modifications remain publicly licensed under **AGPL-3.0**.
