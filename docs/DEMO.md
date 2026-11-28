# Demo Runbook & Verification Checklist (Crowd Safety Monitor)

This document is the step-by-step runbook for the **6-minute live demo** (`00_SHARED_CONTRACT.md` §13) and the **pre-demo / M5 device verification checklist**.

---

## 1. Cast & Devices

| Role in demo | Account | Device | Browser / Mode | What it shows |
|---|---|---|---|---|
| **Responder Laptop** (Person A + Presenter 1) | `admin@demo.local` *(one login covers both Police + Admin views cleanly)* **or** two separate Chrome Profiles (`police1@demo.local` + `admin@demo.local`) | Laptop (`localhost:5000` or HTTPS tunnel) | Chrome / Edge Desktop + Webcam | Monitor webcam/video streaming, Alert Queue, Respond/Resolve, Broadcast Advisory, Report Review, Zone Editor, Analytics, Audit Log |
| **Police Field Phone** (Person B / Presenter 2) | `police2@demo.local` | Android phone + Chrome | Installed PWA (or Chrome HTTPS tunnel tab) | **Alerts armed**, `"Push: On"`, **locked-screen Web Push**, vibration, siren, tapping notification deep-link |
| **Citizen Visitor Phone** (Person B or 2nd phone) | Anonymous first -> `citizen@demo.local` for Step 5 | Android/iOS phone (or incognito mobile window if sharing 1 phone) | Mobile Browser over HTTPS tunnel | Live map, real-time level updates, live advisory toast & strip, Crowd photo report + SOS |

> **Session tip:** Authentication tokens are stored in `localStorage` (`cv-auth`). Do not log into two different accounts inside normal tabs of the same browser profile — use separate devices, separate Chrome Profiles, or an Incognito window for a second role.

---

## 2. Pre-Demo Checklist (T-15 minutes before evaluators arrive)

Run commands from the repository root (`d:\Crowd-Vision`) unless noted.

### A. Build the Production Frontend
1. From `frontend/`:
   ```powershell
   # Ensure real backend mode is built (not mock mode)
   # .env or environment: VITE_USE_MOCKS=0
   npm run build
   ```
   Wait for TypeScript + Vite build to finish and verify `frontend/dist/index.html` and `frontend/dist/sw.js` exist.

### B. Configure & Start Backend + Seeded DB
2. Ensure `backend/.env` is configured for demo mode:
   - `FLASK_ENV=production`
   - `SERVE_FRONTEND=true`
   - `TRUSTED_PROXY_COUNT=1` *(mandatory behind `cloudflared` so rate limits use real client IPs)*
   - `ALLOW_DEFAULT_PASSWORDS=false` *(and change default passwords before exposing via tunnel)*
   - `DETECTOR_BACKEND=ultralytics` *(or `fake` only for an offline emergency dry-run)*
   - `MODEL_PATH=docs/model/best.pt` *(or `people_model.pt` path on the demo machine)*
   - `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT=mailto:<your email>` *(generated via `vapid --gen`)*
   - `DEMO_CENTER=<lat>,<lng>` *(demo room / campus courtyard coordinates so GPS pins fall inside Main Gate)*
3. If starting from a fresh demo database (inside `backend/` with `.venv` active):
   ```powershell
   flask db upgrade
   flask seed-demo
   flask set-password admin@demo.local
   flask set-password police1@demo.local
   flask set-password police2@demo.local
   flask set-password citizen@demo.local
   ```
4. Start the single-process production server from `backend/`:
   - **Windows:**
     ```powershell
     python wsgi.py
     ```
   - **Linux / macOS:**
     ```bash
     gunicorn -w 1 --threads 100 -b 0.0.0.0:5000 wsgi:app
     ```
   > **Important:** Always use `-w 1` (single worker) and **never** `waitress`. Live zone smoothing buffers, leases, rate limiters, and the YOLO subprocess are in-process.

### C. Start the HTTPS Tunnel (`cloudflared`)
5. In a separate terminal, start the Cloudflare quick tunnel:
   ```powershell
   cloudflared tunnel --url http://localhost:5000
   ```
6. Copy the printed `https://*.trycloudflare.com` URL and verify from a browser:
   - `https://<tunnel>/api/v1/health` returns `status: "ok"`, `detector: "ready"`, `worker_alive: true`.
   - `https://<tunnel>/api/v1/config` shows a non-null `vapid_public_key`.
   - Opening a deep link such as `https://<tunnel>/police/alerts/1` loads cleanly without 404.

### D. Hardware, Media & Alerts Readiness
7. **Sample videos & photos loaded:**
   - Have a short **crowd video** (`.mp4` / `.webm`, ideally showing ~15–25 people) on the laptop Desktop for the *Exit Lane* (`DENSITY` mode) demo step.
   - Have 1 test crowd photo ready on the citizen phone (or use live rear camera via `<input capture="environment">`).
   - Optionally keep a dry-run terminal ready with `flask fake-feed --zone 1 --profile ramp --speed 2` if all cameras fail.
8. **Laptop check:**
   - Plugged into power; battery >= 50%.
   - Screen auto-sleep disabled for 15+ minutes.
   - Speaker volume >= 70%, NOT muted (so evaluators clearly hear the warning chime & two-tone siren).
   - Laptop webcam LED is **off** before the demo starts, and browser camera permission is allowed for `http://localhost:5000` (or the tunnel URL).
9. **Phone checks (Android Police Phone + Citizen Phone):**
   - Battery >= 50%, Do Not Disturb **OFF**, Ring/Media/Notification volume **UP**, vibrate enabled.
   - Citizen phone: open `https://<tunnel>/` in mobile browser, verify public map tiles load, verify GPS permission prompt is allowed for `https://<tunnel>`.
   - Android Police phone: open `https://<tunnel>/login` in Chrome (or launch the installed PWA from Home Screen), log in as `police2@demo.local`.
10. **Arm alerts & Push test (on BOTH Responder Laptop & Police Android Phone):**
    - On **Responder Laptop** (`/police`), click **Alerts not armed - tap to enable** -> verify short test beep plays and chip reads **`Alerts armed`**.
    - On **Police Android Phone** (`/police`), tap **Alerts not armed - tap to enable** -> allow Notifications -> verify chip shows **`Alerts armed`** and **`Push: On`**.
    - In the user account menu (top-right icon), tap **Send test notification** -> verify toast reports `Sent test notification to N devices.` (`N >= 1`) and the Android phone displays the test notification.
    - **Lock the Android Police Phone screen** just before Step 3 (and make sure any pre-demo test alerts on Main Gate are resolved so Step 3 triggers a clean fresh alert!).

---

## 3. Six-Minute Demo Script (Step by Step)

### Step 1 (~0:45) — Visitor View & Live Map
* **Who / Device:** Person B on **Citizen Phone** (not logged in, public `/` route).
* **Click:** Open `https://<tunnel>/`. Scroll through the legend and tap **`Browse zones (3)`** bottom sheet. Tap **Main Gate**.
* **Expected result:**
  - MapLibre OpenFreeMap polygons and zone list appear with `ConnectionDot` = `Connected` (green).
  - Unmonitored zones show **No data** (`NO_DATA` grey badge + icon + `"No live data"` — never `"0"` or `"Safe"`).
  - Map and sheet remain usable at narrow mobile width with zero horizontal scrolling.

### Step 2 (~0:45) — Responder Setup & Armed Alerts
* **Who / Device:**
  - Person A on **Responder Laptop** logged in as `admin@demo.local` at `/police` (Operations Dashboard).
  - Person B on **Police Android Phone** logged in as `police2@demo.local` at `/police`.
* **Click:**
  - Both confirm **`Alerts armed`** is active (one user tap unlocks `AudioContext`, vibration, and Web Push).
  - Person B shows **`Push: On`** badge, then **locks the Android screen** and places it beside the laptop.
* **Expected result:** Dashboard displays **Active alerts**, **Live zone map**, and zone cards (**Main Gate** in `COUNT` mode `3 / 5`, **Exit Lane** in `DENSITY` mode `3.0 / 4.0 people/m²`).

### Step 3 (~1:45) — Live Webcam Count Thresholds, Siren, Locked-Phone Push & Density Video Story
* **Part A — Webcam in Main Gate (`COUNT` mode: Warning `3`, Critical `5`):**
  - **Who / Device:** Person A on **Responder Laptop**.
  - **Click:** Go to **Monitor** (`/police/monitor`). Select **Zone** = `Main Gate (Count mode)`, **Source** = `Main Gate camera (Webcam)`, mode = **Webcam**, click **Start streaming**.
  - **Action in front of webcam:**
    1. Hold **1–2 people** in frame -> wait ~2 s.
       - *Expected:* Bounding boxes overlay on video, HUD shows `Source count` 1–2, `Zone level` = **`Safe`**, FPS ~3, latency p95 well under 1500 ms.
    2. Bring a **3rd person** into frame -> wait through `debounce_s` (3 s).
       - *Expected:* Zone transitions to **`Warning`**, warning chime plays on laptop, `AlertBanner` appears at top of `/police/*`. Citizen Phone map polygon turns amber (`WARNING`) live.
    3. Bring **5+ people** into frame (or temporarily lower Critical threshold live — see Part B) -> wait through `debounce_s` (3 s).
       - *Expected:* Zone transitions to **`Critical`** (thick red outline on map), laptop plays **two-tone critical siren** and flashes browser tab title, and within ~2–5 s the **locked Android Police Phone vibrates and displays a `CRITICAL — Main Gate` notification**.
  - **Click:** Click **Stop streaming** on `/police/monitor` -> confirm webcam LED turns **off** (`MediaStreamTrack` stopped cleanly).
* **Part B — Live Threshold Edit + Density Mode Story (*Exit Lane*):**
  - **Click:** Optionally jump to `/admin/zones` -> **Edit** *Main Gate* to demonstrate changing `Warning count` / `Critical count` live and seeing server-validated saved area.
  - **Click:** Return to `/police/monitor`, switch **Zone** = `Exit Lane (Density mode)` (`coverage_area_m2 = 6 m²`), **Input mode** = **Video file**, select the preloaded **crowd video**, ensure `Loop: ON`, and click **Start streaming**.
  - **Expected:** Video plays muted inline with detection boxes, `MonitorHud` counts ~18+ people -> `Density` reaches `~3.0+ people/m²` (`WARNING`/`CRITICAL`), illustrating why **density (people/m²)** matters independently of raw count when camera coverage (`6 m²`) vs zone area (`25 m²`) differs. Click **Stop streaming** when done.
  - **Optional Chart Check:** Click **Open zone live view** (`/police/zones/3`) to show the live Recharts time series with amber/red threshold lines, accessible status text, and `30 min` / `2 h` / `24 h` history buttons.

### Step 4 (~1:00) — Alert Lifecycle & Public Advisory Broadcast
* **Who / Device:**
  - Person B unlocks **Police Android Phone** and **taps the `CRITICAL — Main Gate` Web Push notification**.
  - Person A watches **Responder Laptop**; Person B checks **Citizen Phone** afterward.
* **Click:**
  1. Notification tap opens `/police/alerts/<id>` directly on the phone (or click **Open** / **Acknowledge** on the laptop banner -> `/police/alerts`).
  2. Click **Acknowledge** -> confirm dialog -> observe siren **stops immediately** on both devices and timeline records `Acknowledged` + actor + timestamp.
  3. Click **Respond** -> add short note (e.g. `"Two stewards heading to Main Gate"`) -> **Resolve** -> note dialog explains re-raise interval (`reraise_after_s`).
  4. Go to **Broadcast** (`/police/advisories`): Title `"Main Gate congested — use East Exit"`, Severity **`URGENT`**, Scope **`Main Gate`**, click **Broadcast advisory**.
* **Expected result:**
  - Police queue updates optimistically across views; Alert moves from **Active** to **All**.
  - **Citizen Phone** (`/`) receives a live toast + displays the new URGENT advisory banner within ~2 seconds without page reload.

### Step 5 (~1:15) — Citizen Crowd Photo Report & SOS Triage
* **Who / Device:** Person B on **Citizen Phone** -> signs in as `citizen@demo.local` if prompted; Person A on **Responder Laptop** at `/police/reports`.
* **Click:**
  1. On **Citizen Phone**, tap **Report a crowd** (`/report/crowd`). Verify GPS pill shows **`Location ready · accuracy ±... m`**. Capture or select the crowd photo (auto-downscaled to <= 1280 px JPEG). Show privacy notice (`"Your photo is not stored..."`), click **Submit crowd report**.
     - *Expected:* Returns immediately with `"N people counted, about X.X per m² in <zone>"`, and local preview image + blob URL are immediately wiped.
  2. Tap **Send SOS instead** (`/report/sos`). Show permanent **`112`** emergency banner. Tap **Crush risk**, verify GPS ready, tap **Send SOS** -> **Confirm & send SOS** modal.
     - *Expected:* Laptop immediately sounds critical siren + displays **`SOS - Crush risk`** banner with **Open** link (`/police/reports?focus=<id>`). Citizen Phone opens **My reports** (`/my-reports`).
  3. On **Responder Laptop**, click **Open** on the SOS banner -> jumps straight to `/police/reports?focus=<id>` (highlighted card + map pin). Click **Verify** -> add note `"Patrol reached Main Gate"` -> **Confirm verify**.
     - *Expected:* Citizen's **My reports** screen updates from **`Pending`** to **`Verified`** live with the responder note and toast.

### Step 6 (~0:45) — Admin Analytics, Audit Trail & Closing Limits
* **Who / Device:** Person A on **Responder Laptop** (`admin@demo.local`).
* **Click:**
  1. Open **Analytics** (`/admin/analytics`): show **Average acknowledge / resolve times** (`m:ss`), **Alerts per zone** bar chart, **Peak hours by zone (IST)**, **Reports by status**, and click **Download alerts CSV**.
  2. Open **Audit log** (`/admin/audit`): filter or inspect recent actions (`ALERT_ACKNOWLEDGED`, `ALERT_RESOLVED`, `ADVISORY_CREATED`, `REPORT_REVIEWED`) and click `View details`.
* **Talk track (Closing Limitations — `00_SHARED_CONTRACT.md` §13.7):**
  - Mention current system limits honestly: extreme dense-crowd occlusion causes single-head RGB detectors like YOLOv8n to undercount (future work: density-map crowd counting such as CSRNet/DM-Count); browser capture relies on an open foreground tab (production upgrade: server-side RTSP camera ingestion); iPhone Safari only supports Web Push when installed to Home Screen (iOS 16.4+) and does not support `navigator.vibrate`.

---

## 4. Failure Contingencies (What to Do If Something Breaks Live)

| Failure | Symptoms | Immediate Recovery |
|---|---|---|
| **Laptop/phone webcam fails or too dark / zero people nearby** | `NotAllowedError`, `NotReadableError`, or detector cannot see 5 people | Switch `/police/monitor` immediately to **Video file** mode with the preloaded crowd video, OR run `flask fake-feed --zone 1 --profile ramp --speed 2` from a backend terminal to drive real engine alerts & notifications. |
| **Plain HTTP blocks camera or push** | `"Camera needs HTTPS"` warning on `/police/monitor` or `"Push: Unsupported"` | Make sure phones use the **`https://<random>.trycloudflare.com`** URL, never `http://<lan-ip>:5000`. On the laptop itself, `http://localhost:5000` is a secure context. |
| **`SOURCE_IN_USE` shown on `/police/monitor`** | `"This source is already being streamed from another tab or device"` | Another open tab is still holding the source lease. Close/stop the other tab, or pick a second source in `SourcePicker` (or create a quick temporary source if needed); otherwise wait `stale_after_s` (15 s) for the lease to expire. |
| **Locked-phone Web Push does not arrive** | Laptop siren works, phone stays silent | 1) Unlock phone and check **Alerts armed** + **`Push: On`** badge (tap `Enable background push` if `Push: Off`). 2) Check `GET /api/v1/config` `vapid_public_key` is non-null. 3) Trigger **Send test notification** from user menu. 4) Fallback: show the live in-app **AlertBanner** + **siren** running on `/police` directly on the open mobile browser tab. |
| **`cloudflared` tunnel disconnects mid-demo** | Phone shows `"Reconnecting... live data may be stale"` | Restart `cloudflared tunnel --url http://localhost:5000` (URL will change; share new URL cleanly via QR/link), **OR** showcase the deliberate **disconnect -> `"Reconnecting... live data may be stale"` -> automatic `hello` resync** behavior on the laptop if on local Wi-Fi! |
| **Citizen GPS fails indoors (`timeout` / `denied`)** | `"Location required"` / `"timed out after 10 seconds"` on `/report/crowd` or `/report/sos` | Step near a window/doorway and tap **Retry location**. Make sure browser site location permission is set to `Allow` (required on HTTPS tunnel). |
| **429 rate limit hit during rehearsal** | `"Please try again later"` on Login (`20/min`), Crowd (`1/min`), or SOS (`3/10min`) | Wait 60 seconds for crowd photo limit, wait until the `Retry-After` window expires for SOS (the UI explicitly directs citizens to dial **112** during a rate limit), or log in with `police1` / `police2`. |

---

## 5. M5 Reference — Standalone Locked Android Phone Push Verification

Quick reference for testing Web Push in isolation (`00_SHARED_CONTRACT.md` §9):
1. Configure `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `SERVE_FRONTEND=true`, and `TRUSTED_PROXY_COUNT=1` in `backend/.env`.
2. Build `frontend/` (`npm run build`), start `python wsgi.py` (or `gunicorn -w 1 ...`), and start `cloudflared tunnel --url http://localhost:5000`.
3. On Android Chrome over `https://...trycloudflare.com`: log in as `police1@demo.local` -> `/police` -> tap **Alerts not armed - tap to enable** -> allow notifications -> confirm **`Push: On`**.
4. Tap User menu -> **Send test notification** -> verify `sent >= 1` and harmless test notification arrives.
5. Lock the phone screen. Push **Main Gate** to **CRITICAL** (`flask fake-feed --zone 1 --profile ramp --speed 3` or live webcam).
6. Verify within ~5 seconds: phone buzzes with `CRITICAL — Main Gate`; tapping opens `/police/alerts/<id>`.
7. Optional stale-subscription (`410`) check: revoke site notification permission on the phone, trigger another push, and verify backend logs delete the `410` row from `push_subscriptions`.
