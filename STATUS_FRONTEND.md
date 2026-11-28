# Frontend status — 28 November 2026

## F5 — Installable PWA and background push (done, pending physical Android phone tunnel test)

Implemented Phase F5 on `fe/f5-pwa-push`:

- **`vite-plugin-pwa` (`2.0.0`) & TypeScript WebWorker split** (`frontend/vite.config.ts`, `frontend/tsconfig.sw.json`, `frontend/tsconfig.json`, `frontend/package.json`, `frontend/index.html`, `frontend/public/icons/`): configured `VitePWA` with `strategies: 'injectManifest'`, `srcDir: 'src'`, `filename: 'sw.ts'`, `injectRegister: false`, standalone web manifest (`name`, `short_name`, `display: 'standalone'`, `start_url: '/'`, `theme_color: '#0f766e'`, `background_color: '#09090b'`), and PNG icons (`icon-192.png`, `icon-512.png`, `icon-512-maskable.png`, `apple-touch-icon.png`). Added `tsconfig.sw.json` (`"lib": ["ES2023", "WebWorker"]`) checked alongside DOM tsconfig in `"typecheck"`. Added preview `Cache-Control: no-cache` headers for `/sw.js`, `/`, and `/index.html`.
- **Service Worker & push handlers** (`frontend/src/sw.ts`, `frontend/src/features/push/swHandlers.ts`, `frontend/src/features/push/registerPwa.ts`, `frontend/src/main.tsx`): `precacheAndRoute(self.__WB_MANIFEST)` + `cleanupOutdatedCaches()` + `NavigationRoute` with `denylist: [/^\/api(?:\/|$)/, /^\/socket\.io(?:\/|$)/]` (no caching or interception of `/api` or `/socket.io`), `SKIP_WAITING` + `clientsClaim()` update lifecycle (`registerPwa()` / `setupPwaRegistration()` checking `registration.update()` on `visibilitychange`), `push` handler parsing JSON payloads (`ALERT`, `SOS`, `TEST`) with invalid/missing-JSON fallback and always calling `registration.showNotification(...)` (`tag`, `requireInteraction: true` when `level === 'CRITICAL' || kind === 'SOS'`, vibrate pattern, sanitized `data: { url }`), and `notificationclick` handler closing the notification, focusing/navigating an existing same-origin window client, or falling back to `clients.openWindow(...)`.
- **`features/push` & alert/shell/auth integration** (`frontend/src/features/push/useWebPush.ts`, `frontend/src/features/push/vapid.ts`, `frontend/src/features/push/pushApi.ts`, `frontend/src/features/push/InstallHint.tsx`, `frontend/src/features/alerts/useAlertAudio.ts`, `frontend/src/features/alerts/AlertCenter.tsx`, `frontend/src/features/auth/session.ts`, `frontend/src/app/layouts/AppShell.tsx`, `frontend/src/features/zones/api.ts`, `frontend/eslint.config.js`):
  - `useWebPush()` enables only when `/config.vapid_public_key` is non-null, `'serviceWorker' in navigator`, `'PushManager' in window`, and `'Notification' in window`; converts base64url VAPID key via `urlBase64ToUint8Array`; subscribes with `userVisibleOnly: true` and `POST /push/subscriptions`; exposes `unsupported` / `off` / `on` / `blocked` status and non-error fallback notices so in-app banners and siren keep working.
  - `ArmAlertsButton` unlocks audio, requests notification permission once, and subscribes to Web Push on the same tap while showing push status (`Push: On/Off/Blocked/Unsupported`).
  - `useSession.getState().logout()` captures the bearer token before clearing credentials and calls `unsubscribePushOnLogout` (`sub.unsubscribe()` + `DELETE /push/subscriptions?endpoint=`).
  - Police/admin user menu adds `"Send test notification"` calling `POST /push/test` and showing the delivered count toast.
  - `InstallHint` handles Android `beforeinstallprompt` install prompts and iOS Safari `"Share -> Add to Home Screen"` guidance (noting iOS 16.4+ installed app requirement).
  - Banned direct `new Notification(...)` calls via ESLint `no-restricted-syntax` (`0` occurrences verified in ESLint and `tests/sw.test.ts`).

**Verification (run after final frontend edit).** From `frontend/`:
- `npm.cmd run build` (`tsc --noEmit && tsc -p tsconfig.sw.json --noEmit && vite build`): exited `0`, generated `dist/manifest.webmanifest` and `dist/sw.js` (`21207` bytes, `41` precached entries (`3126.02 KiB`); zero `/api/v1` or `socket.io` precache entries; pre-existing Vite >500 kB chunk warning on `ZoneMap`/`index`).
- `npm.cmd test`: **18 test files passed, 184 of 184 tests passed** (`9` new tests in `tests/sw.test.ts` covering SW `push`/`notificationclick`/fallback/denylist/update lifecycle/static `new Notification(` scan, plus `11` new tests in `tests/push.test.tsx` covering `urlBase64ToUint8Array`, `useWebPush` state machine, `ArmAlertsButton` single-tap flow, `logout()` push unsubscribe, `"Send test notification"`, `InstallHint`, and `vitest-axe`).
- `npm.cmd run lint`, `npm.cmd run format:check`, and `npm.cmd run check:fixtures` (`43` fixtures) all exited `0`.
- **Live mock browser check (Playwright Chromium against `npm.cmd run mock` + `vite preview` built bundle):** verified `/sw.js` returns `200` with `Cache-Control: no-cache`, `/manifest.webmanifest` serves `200` JSON with `192x192` and `512x512` (`any` + `maskable`) icons, Chromium activated `http://127.0.0.1:4173/sw.js`, SW-controlled `GET /api/v1/health` returned `200 application/json` cleanly bypassing SPA routing, signed in as `police1@demo.local` showing `Push: Unsupported` gracefully when mock `vapid_public_key` is `null`, and `"Send test notification"` displayed `Sent test notification to 0 devices.` with zero console or page errors.

**Untested / pending.** Real locked-phone Android Chrome testing over HTTPS tunnel (install to Home Screen, VAPID-configured Flask backend `POST /push/test`, locked-screen notification arrival, and tap-through deep-link opening `/police/alerts?focus=<id>` / `/police/reports?focus=<id>`) remains pending a physical phone + Person A's Flask/VAPID runtime. No backend, eval, or contract files were modified.

## F4b — Monitor page, source picker, and zone live view (done, pending real-backend manual check)

Implemented Phase F4b on `fe/f4b-monitor-page`:

- **`SourcePicker` & source API** (`frontend/src/features/monitor/SourcePicker.tsx`, `frontend/src/features/police/data.ts`): zone and active-source selection (`GET /sources?zone_id=...`), inline RHF + Zod source creation (`POST /sources` sending only `{ zone_id, name, kind }`, never `coverage_area_m2`) with `422` field-error mapping, and read-only coverage display (`{coverage_area_m2} m² (set by an admin in /admin/sources)`). `updateSource` now also patches cached `sources` queries on `source:status`.
- **`MonitorPage` (`/police/monitor`)** (`frontend/src/features/monitor/MonitorPage.tsx`, `frontend/src/features/monitor/streamStore.ts`, `frontend/src/app/router.tsx`): Webcam / Video file mode switch, Start / Stop (releasing all webcam `MediaStreamTrack`s on Stop, zone/source/mode switch, and unmount), mobile camera facing toggle (`user` / `environment`), plain-HTTP warning banner (`!window.isSecureContext`), `SOURCE_IN_USE` ("This source is already being streamed from another tab or device") and other F4a/frame error states, single-active-stream-per-tab coordination (`claimActiveStream`), live `ZoneStatusCard` (from `zone:detail`) beside the HUD, and zero 3 FPS parent re-renders (`syncState: false` + Zustand store selectors + `React.memo` on `MonitorHud`, `DetectionOverlay`, `ConnectedMonitorHud`, and `ConnectedDetectionOverlay`).
- **Lazy-loaded `ZoneChart` & `/police/zones/:id`** (`frontend/src/features/zones/ZoneChart.tsx`, `frontend/src/features/zones/PoliceZoneDetail.tsx`, `frontend/src/components/ui/chart.tsx`): installed plan-listed `recharts@^3.8.0` and added shadcn `chart` component (adapted to `@/lib/utils`); `ZoneChart` builds as its own lazy chunk (`ZoneChart-*.js`, 355.54 kB / 104.44 kB gzip), merges `GET /zones/{id}/history` with live `useSeries` rolling points (up to 300 points, `isAnimationActive={false}`), switches metric and amber/red `ReferenceLine`s between `DENSITY` and `COUNT` modes, and renders level text in tooltips. `/police/zones/:id` displays `LevelBadge`, `TrendIcon`, count/density, thresholds, `30 min` / `2 h` / `24 h` (`bucket_s=10/60/300`) history controls with skeleton/error-retry/empty states, accessible summary text next to the chart, sources (`ONLINE` / `OFFLINE` + `Last frame ...`), and zone advisories.
- **Dashboard links** (`frontend/src/features/police/Dashboard.tsx`): zone cards link to `/police/zones/:id` (added explicit `View live chart` link alongside the zone heading link).

**Verification (run after final edit).** From `frontend/`:
- `npm.cmd test`: **16 test files passed, 164 of 164 tests passed** (including 8 tests in `tests/monitorPage.test.tsx` and 5 tests in `tests/zoneLiveView.test.tsx`; `vitest-axe` ran on both `/police/monitor` and `/police/zones/:id` with `color-contrast` disabled in jsdom).
- `npm.cmd run lint`, `npm.cmd run format:check`, `npm.cmd run check:fixtures` (`43` fixtures), and `npm.cmd run build` (`tsc --noEmit && vite build`) all exited `0` (`ZoneChart` emitted as separate lazy chunk; pre-existing Vite >500 kB chunk warning remains for `ZoneMap` and entry bundle).
- **Live mock browser check (Playwright Chromium against `npm.cmd run mock` + `npm.cmd run dev`):** signed in as `police1@demo.local`, opened `/police/zones/1` from the dashboard card link, switched `30 min`/`2 h`/`24 h` history ranges, opened `/police/monitor`, created `Demo Video Cam` (`VIDEO_FILE`, verified `POST /sources` omitted `coverage_area_m2`), streamed a looping synthetic WebM video (`overlay_non_zero_pixels: 3292`, HUD updated to `Source count 3 | Zone smoothed 3 | Zone density 0.1 people/m² | Zone level Safe | Latency p50: 20 ms · p95: 20 ms | Drops 0`), stopped streaming, verified `.recharts-surface` rendered on `/police/zones/1`, and confirmed `0` px horizontal overflow at `360px` on both pages with zero console or page errors.

**Untested / pending.** Real backend + YOLOv8n (`be/b5b`) webcam streaming check (1–5 people count parity, real HUD `p50`/`p95` latency, physical camera LED off on Stop) and physical mobile devices (Android Chrome / iPhone Safari) were not run here (no `backend/.venv` or `.pt` model weights in this workspace). No backend or contract files were modified.

## F4a — Camera and frame-streaming hooks, overlay (done)

Built and tested the browser camera/video pipeline hooks, overlay, HUD, and dev-only test harness under `frontend/src/features/monitor/` (plus the dev-only `/police/monitor-dev` route behind `import.meta.env.DEV` in `frontend/src/app/router.tsx`):

- **`useWebcam(facing)`** (`frontend/src/features/monitor/useWebcam.ts`): `getUserMedia({ video: { facingMode, width: { ideal: 1280 } }, audio: false })` feeding `<video autoPlay playsInline muted>`. Checks `!window.isSecureContext` ("Camera needs HTTPS (use the tunnel URL)") and missing `mediaDevices`, maps `NotAllowedError` / `NotFoundError` / `NotReadableError` (and aliases), and stops every `MediaStreamTrack` on `stop()`, unmount, and superseded/late-resolving requests (idempotent under React `StrictMode`).
- **`useVideoFile()`** (`frontend/src/features/monitor/useVideoFile.ts`): creates and revokes `URL.createObjectURL` on replacement, `unload()`, and unmount; provides `play`, `pause`, `toggleLoop`, and `clearLoopRestart`; detects loop restarts when `currentTime` decreases on `timeupdate`.
- **`useFrameStreamer({ video, sourceId, enabled, ... })`** (`frontend/src/features/monitor/useFrameStreamer.ts`): reads `GET /config` via TanStack Query (`target_fps`, `frame_width`, `jpeg_quality`) with optional override; waits for `loadedmetadata` before reading dimensions; enforces strictly one frame in flight (including during async `toBlob`/`arrayBuffer`); paces to `>= 1000 / target_fps`; encodes to `image/jpeg` (never PNG/WebP); increments `seq` from 1 with `reset: true` on start and loop restart; counts drops after a 2 s timeout; stops without retry on `SOURCE_IN_USE` (`state: 'in-use'`); pauses webcam streams on `document.hidden` while keeping video-file streams active; cleans up listeners and timers on unmount; exposes `{ state, fps, latencyMs: { p50, p95 }, drops, lastResult, lastResultAt, stop }`.
- **`overlay.ts` & `DetectionOverlay`** (`frontend/src/features/monitor/overlay.ts`, `frontend/src/features/monitor/DetectionOverlay.tsx`): pure `computeContainRect` and `mapBoxes` helpers accounting for `object-fit: contain` letterboxing/pillarboxing and `devicePixelRatio`; thin canvas overlay that clears after 1 s without a new result and keeps confidence hidden by default with an `aria-pressed` toggle.
- **`MonitorHud`** (`frontend/src/features/monitor/MonitorHud.tsx`): shows `Source count` alongside clearly labelled zone metrics (`Zone smoothed`, `Zone density` via `DensityValue`, `Zone level` via `LevelBadge`), `FPS`, `Latency` (`p50`/`p95`), `Drops`, `NO_DATA` / "No data yet" initially, and a quiet `DETECTOR_BUSY` warning chip.
- **`MonitorDev`** (`frontend/src/features/monitor/MonitorDev.tsx`): dev-only harness excluded from production builds to exercise webcam, video file, overlay, and HUD against the mock server.

**Verification (post-merge with `origin/main` F3b + B7).** From `frontend/`: `npm.cmd test` passed **151 of 151 tests in 14 files** (including 29 tests in `tests/monitor.test.tsx`); `npm.cmd run lint`, `npm.cmd run format:check`, and `npm.cmd run build` (`tsc --noEmit && vite build`) all passed with exit code 0 (`MonitorDev` excluded from production bundle; pre-existing Vite >500 kB chunk warning unchanged).

**Live mock browser check.** Headless Edge + Playwright against `npm.cmd run mock` + `npm.cmd run dev` on `/police/monitor-dev` (logged in as `police1@demo.local`): streamed a recorded looping 640×360 WebM video (HUD updated to `Source count 5`, `Zone smoothed 4.5`, `Zone density 0.2 people/m²`, `Zone level Warning`, `FPS 2.9`, `Latency p50: 4 ms · p95: 6 ms`, `Drops 0`, overlay canvas `640×360` with 7006 non-zero pixels, `max_in_flight: 1` across 16 WebSocket frames, confidence toggle working, 0 overflow at `360px`) and switched to fake webcam (`hasSrcObj: true`, live HUD updates, `Reset` ended all tracks `['ended']`), with zero console/page errors.

**Untested / next.** Physical camera LED/mobile browsers (Android Chrome / iOS Safari) and real Flask + YOLOv8n (`be/b5b`) integration were not tested here; `vitest-axe` ran with `color-contrast` disabled in jsdom. No contract or backend files changed and no libraries added. Ready for review and F4b.

## F3b — Alert center implemented, human listening check pending

Police and admin routes share one alert center. It restores NEW alerts and pending urgent SOS reports on entry and reconnect, shows three banners plus an overflow count, and uses F3a's optimistic acknowledgement mutation. Alert density is labelled “Peak” to match the contract field. Arming requests audio, notification permission and vibration in one gesture. Arming intent and mute persist, while reload requires a fresh tap. Push subscription remains scheduled for F5.

**Verification from `frontend/`.** `npm.cmd test` passed 122/122 tests in 13 files (15.35 s). Coverage includes StrictMode cleanup, vibration requests, warning and critical sound timing, mute, audio suspension, the 60-second cap, optimistic acknowledgement, all five SOS types, reduced motion and banner axe. The jsdom axe check excludes color contrast. `npm.cmd run lint` and `npm.cmd run build` passed, including TypeScript. Vite emitted its large-chunk warning. The first suite had 10 sandbox loopback failures and five read-only module-spy errors. Loopback permission and a module mock fixed these. The first build with the new tests rejected Promise.withResolvers. The test now uses a standard Promise.

**Desktop Chrome exercise.** Ran a temporary Playwright probe with `python ../.f3b-chrome.py` against the production bundle and an isolated mock in desktop Chrome 158.0.8127.88, headless with muting disabled. Cleared the unrelated seed alert and seed SOS first. Signed in as police, armed from the queue, advanced the Main Gate ramp through WARNING and CRITICAL, acknowledged from the banner, waited 11 seconds and reloaded. Chrome produced nonzero audio waveforms for the arming tone, warning chime and critical siren. The banner disappeared, no fourth burst started, and reload showed the not-armed chip with zero audio bursts. No uncaught page errors. Earlier probe attempts hit a temporary-path mismatch and short-tone sampling timeouts. The passing run used a longer sample window.

**Human listening sign-off.** Person B verified in desktop Chrome/Edge with laptop volume up that the arming tone, warning chime and critical two-tone siren were clearly audible. Acknowledging silenced the siren immediately, and reloading required arming again. Android vibration and iPhone Safari will be tested on physical devices during M5. No new dependencies or contract changes.

## F3a — Police dashboard, alert queue and alert detail

Police and admins can monitor live zones, filter and paginate alerts, open timelines, and acknowledge, respond or resolve with an optional note. The dashboard shows zone thresholds, trend, source availability and the age of the last live reading. Socket events update zone and alert caches and maintain up to 300 live samples per zone. Alert writes update visible lists immediately, roll back on failure and refetch after a conflict. The arming chip is a preview. Monitor, reports and zone live view retain their placeholder routes.

**Verification.** From `frontend/`, `npm.cmd test` passed 110 of 110 tests in 11 files in 18.54 seconds. Coverage includes legal actions, cleared conditions awaiting review, feed and re-raise timeline labels, list membership, deduplication, the series cap, rollback on 409, access guards, keyboard operation and axe checks on both dashboard and queue. `npm.cmd run lint` and `npm.cmd run build` passed, including TypeScript. The build emitted its large-chunk warning. The jsdom axe checks exclude color contrast and use a map stub.

**Browser checks.** On the mock ramp, filtered to Main Gate, acknowledged alert #100 with a note, verified its timeline, resolved it, and saw the dashboard count drop from two to one. A later ramp raised #121. At a 390 px viewport the queue displayed cards without horizontal overflow. B4b was already merged in PR #5 (89211f4). A second run used its Flask fake feed and a temporary seeded SQLite database. Police responded to and resolved Main Gate #1, saw the empty Active queue, and found the resolved record in All. The mock and Flask lifecycle checks recorded zero browser console errors. Physical devices and assistive-technology sessions were not tested.

**Contract decision.** `GET /settings` stays admin-only. The admin resolve dialog uses the returned re-raise interval. The approved police fallback refers to “the delay configured in Settings.” This preserves contract 1.1.0. Absolute timestamps and date filters use browser-local time. F3a is ready for review.

## F2 — Public screens and realtime complete on the mock

The public map, zone detail, advisories and help routes use the public REST contract. A shared Socket.IO connection follows the session token, resyncs active queries on hello and displays a stale-data bar during disconnects. MapLibre loads on demand using the OpenFreeMap Liberty style. The map and list share a selection and the zone list stays accessible when the map fails.

On fe/f2-public-map, npm.cmd test passed 98 tests in 10 files. Lint, all 43 fixtures, typecheck and the production build passed. The ZoneMap JS chunk was 310.93 kB gzip, separate from the entry and worker. Vite emitted its large-chunk warning. The Windows checkout caused 83 line-ending warnings from the default format check. Prettier passed with --end-of-line auto.

Headless Edge at 360 px verified the mock ramp, polygon and list selection, stable map dimensions when the sheet opened, stale status after mock shutdown, REST resync after restart, and authenticated socket refresh. Browser axe found zero violations across all four routes. The final four-route browser pass recorded zero console errors. Testing caught and corrected a missing glyph font, advisory heading order, and map controls and polygons underneath the mobile sheet. Physical devices and the real Flask backend were outside this mock run.

F2 is ready for human review. Contract 1.1.0 applies. The absolute display timezone question remains open for later work. The clean F2 branch was fast-forwarded to F1 before implementation.

## F1 — Authentication and route guards complete, pending human review

Login, citizen registration, session restoration via /auth/me, single-flight refresh, role guards, role-aware navigation and logout are implemented on `fe/f1-auth`. Protected redirects preserve path, query and fragment. A failed refresh clears the session and query cache, returns to login and shows an expiry toast. Logout has an extension point for F5 push cleanup.

- From frontend, `npm.cmd test` passed 92 tests in nine files. Three concurrent unauthorized requests shared one refresh on success and failure. The suite covers the four-audience guard matrix, navigation, form errors and axe on both forms.
- `npm.cmd run check:fixtures` checked 43 fixtures. `npm.cmd run lint`, `npm.cmd run format:check`, and `npm.cmd run build` passed, including TypeScript. Vite warned about the 535.22 kB main chunk.
- Headless Edge, 360 px, verified all four seed logins and logout on the mock and an isolated seeded copy of the merged Flask backend with VITE_USE_MOCKS=0. Admin landed on /admin/zones, both police users on /police and citizen on /. Anonymous /police preserved next; citizen /admin/zones showed Forbidden.
- On the mock, browser checks also passed for citizen registration, allowed and disallowed next destinations, 404, silent refresh after mock expiry, and the toast and redirect after a simulated refresh rejection. Browser axe found zero violations on login and registration, including contrast. Physical devices and elapsed real-token expiry were not exercised.
- During verification five guard assertions matched duplicate headings and TypeScript rejected a test query option. Selecting the level-one heading fixed both. One formatting failure was corrected. A second Vite instance needed its command-lock override. jsdom emitted canvas warnings; browser axe ran with the native canvas.
- No contract or dependency changes. No F1 questions for Person A or B. Human M1 review is next. The absolute timestamp timezone question remains open for screens that display it.

## F0 implementation complete, pending human review

The frontend contains the strict React/Vite scaffold, all 24 planned route placeholders, 17 shadcn components, shared status components, API/query utilities, contract 1.1.0 types and 43 JSON fixtures. The local Express and Socket.IO mock provides REST and realtime scenarios. Run instructions are in frontend/README.md.

Person B requested a visual revision of F0. The public dashboard uses ivory surfaces, frosted cards, a schematic venue plan, a zone directory and visitor resources. Police and admin previews use an operations desk. Desktop navigation collapses into a labeled Lucide icon rail with a saved preference. Mobile users access navigation through tabs and the More drawer. The route tree and contract remain at F0. All venue readings displayed in the redesign come from the public demo fixture. The schematic is illustrative.

## Verification

The latest F0 visual revision fills the viewport and uses an ivory-to-peach background, copper accents and a charcoal feature card. The venue diagram uses matching neutral and clay tones. Browser measurements at desktop and mobile widths confirmed a zero origin and no horizontal overflow. Mobile screenshot capture was unavailable. After this change, `npm.cmd test` passed all 62 tests, `npm.cmd run lint` and `npm.cmd run format:check` passed, and `npm.cmd run build` passed its TypeScript check and production compilation.

Ran from frontend on Windows:

- `npm.cmd test` — 62 passed in 8 files, including the sidebar persistence regression, 24 route checks, axe checks, mock REST and socket behavior.
- `npm.cmd run build` — passed, including `npm run typecheck` (`tsc --noEmit`) and Vite production bundling.
- `npm.cmd run lint` and `npm.cmd run format:check` — passed.
- `npm.cmd run check:fixtures` — all 43 passed. Running this concurrently with Vitest's fixture test initially failed because both used the same generated file. Run the commands sequentially.
- `node scripts/report-contrast.mjs` — all eight badge text/background pairs passed. Light ratios for safe, warning, critical and no data were 4.79, 6.84, 5.91 and 6.92. Dark ratios were 6.49, 6.29, 5.28 and 6.97.
- Local browser — visually checked the cream overview, toggled the desktop rail and opened the mobile drawer. Earlier F0 proxy smoke test (`node scripts/smoke.mjs`) passed for REST, WebSocket hello and deep links.

## Limits and decisions

Physical phones, real Flask/detector integration and push delivery remain untested. The scaffold uses mock data. UI guards and automatic token refresh remain scheduled for F1. The requested cream/glass art direction supersedes the original slate/no-glass styling. No additional libraries were needed for the redesign. F0 tooling approvals and the mock-only expiry control are recorded in docs/DECISIONS.md.

## Next

Person A and Person B review the contract and fixtures for M0. Clarify IST versus browser-local absolute display time before implementing timestamp displays. Await the next assigned phase.

## F0 typography revision

The dashboard now serves Bricolage Grotesque, Inter, Geist Mono and the JetBrains Mono fallback locally with font-display swap. The full-bleed frame and glass cards use 24px corners. Alert previews show the fixture's zone name and peak count beside its critical count threshold. Contract 1.1.0 and the F0 route scope still apply.

From `frontend/`, `npm.cmd test` passed 63 tests in eight files, including grouped alert counts and missing thresholds. `npm.cmd run lint`, `npm.cmd run format:check` and `npm.cmd run build` passed. The build includes `npm run typecheck` (`tsc --noEmit`). `npm.cmd run check:fixtures` passed all 43 fixtures.

In the browser, verified the rendered font families, sizes and weights on the overview and opened the police alert preview showing “Stage Area · 12 / 10”. The mobile browser check reported a 396px content width matching the viewport. A second Vite launch declined to start because the existing preview server was already running. Physical devices and the real backend were not tested.

## Shared clone verification

Phase F0 is done on `fe/f0-scaffold`. From `frontend/` with Node 24.18.0, `npm.cmd install` reported zero vulnerabilities. After extracting the types from the repository contract, `npm.cmd run check:fixtures` passed all 43 fixtures, `npm.cmd test` passed 63 tests in eight files with loopback access, and `npm.cmd run lint` and `npm.cmd run typecheck` both passed. M0 contract sign-off is pending human review.
