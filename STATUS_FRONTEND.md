# Frontend status — 28 November 2026

## Phase: F4a — Camera and frame-streaming hooks, overlay (done)

## Done since last update

Built and tested the browser camera/video pipeline hooks, overlay, HUD, and dev-only test harness under `frontend/src/features/monitor/` (and registered the dev-only route in `frontend/src/app/router.tsx`):

1. **`useWebcam(facing)`** (`frontend/src/features/monitor/useWebcam.ts`): Calls `navigator.mediaDevices.getUserMedia({ video: { facingMode, width: { ideal: 1280 } }, audio: false })` feeding `<video autoPlay playsInline muted>`. Checks `!window.isSecureContext` ("Camera needs HTTPS (use the tunnel URL)") and missing `mediaDevices`, maps `NotAllowedError` / `NotFoundError` / `NotReadableError` (and aliases) to clear messages, stops every `MediaStreamTrack` on `stop()`, unmount, and superseded/late-resolving `getUserMedia` requests (idempotent under React `StrictMode`).
2. **`useVideoFile()`** (`frontend/src/features/monitor/useVideoFile.ts`): Creates and revokes `URL.createObjectURL` on unload, replacement, and unmount; provides `play`, `pause`, `toggleLoop`, and `clearLoopRestart`; detects loop restarts when `currentTime` decreases on `timeupdate` and exposes `loopRestarted`.
3. **`useFrameStreamer({ video, sourceId, enabled, ... })`** (`frontend/src/features/monitor/useFrameStreamer.ts`): Reads `GET /config` via TanStack Query (`target_fps`, `frame_width`, `jpeg_quality`) with optional override and defaults; waits for `loadedmetadata` before reading `videoWidth`/`videoHeight`; enforces strictly one frame in flight (including while `canvas.toBlob` and `blob.arrayBuffer()` are async); paces emissions to `>= 1000 / target_fps` ms; encodes frames to JPEG (`image/jpeg`, never PNG or WebP) at `frame_width` preserving aspect ratio; emits `frame:submit` with incrementing `seq` starting at 1 and `reset: true` on start or loop restart; clears in-flight on matching `(source_id, seq)` `frame:result` or 2 s timeout (counting a drop); stops without retrying and sets `state` to `'in-use'` on `SOURCE_IN_USE`; pauses webcam streams while `document.hidden` (while keeping video-file streams active); cleans up socket listeners, DOM listeners, and timers on unmount; exposes `{ state, fps, latencyMs: { p50, p95 }, drops, lastResult, lastResultAt, stop }`.
4. **`overlay.ts` & `DetectionOverlay`** (`frontend/src/features/monitor/overlay.ts`, `frontend/src/features/monitor/DetectionOverlay.tsx`): Pure `computeContainRect` and `mapBoxes` helpers mapping normalised `[x1, y1, x2, y2, conf]` boxes into displayed pixel coordinates accounting for `object-fit: contain` letterboxing/pillarboxing and `devicePixelRatio`; `DetectionOverlay` draws thin boxes onto an absolutely positioned canvas, clears after 1 s without a new result, keeps confidence labels hidden by default with an accessible `aria-pressed` toggle button, and updates on container/window resize.
5. **`MonitorHud`** (`frontend/src/features/monitor/MonitorHud.tsx`): Presentational stats panel displaying this source's raw `count`, clearly labelled zone-level values (`Zone smoothed`, `Zone density` via `DensityValue`, `Zone level` via `LevelBadge`), `FPS`, `Latency` (p50/p95), `Drops`, `NO_DATA` / "No data yet" when no result exists, and `DETECTOR_BUSY` as a quiet `bg-warning-bg text-warning` chip with `TriangleAlert` icon.
6. **`MonitorDev`** (`frontend/src/features/monitor/MonitorDev.tsx`, route `/police/monitor-dev` behind `import.meta.env.DEV` in `frontend/src/app/router.tsx`): Dev-only harness excluded from production builds to exercise webcam, video file, overlay, and HUD against the mock server.

## Verification

From `frontend/` after the final edit to frontend source/tests:

- `npm.cmd test` (`vitest run`) — **139 passed in 12 files** (including 29 tests in `tests/monitor.test.tsx`). Covers `computeContainRect`/`mapBoxes` (including letterboxed 16:9 in 4:3 at `dpr = 2`), `useFrameStreamer` (1 frame in flight incl. deferred `toBlob`, matching `frame:result`, 2 s timeout drop, strict `target_fps` pacing, `seq` increment, `reset` on start & loop restart, `loadedmetadata` wait, `/config` query read, `SOURCE_IN_USE` stop with no retry, `document.hidden` webcam pause vs video-file continue, cleanup, JPEG mime type + quality), `useWebcam` (`!isSecureContext`, error mappings, `StrictMode` track stop, late-resolving unmount track release), `useVideoFile` (URL revocation on unload & unmount, loop-restart `currentTime` decrease), `MonitorHud` (`NO_DATA`, zone metrics, `DETECTOR_BUSY` chip, `vitest-axe` zero non-contrast violations), and `DetectionOverlay` (confidence toggle and 1 s stale clear).
- `npm.cmd run lint` — passed (0 errors, 0 warnings).
- `npm.cmd run format:check` — passed (Prettier clean).
- `npm.cmd run build` (`tsc --noEmit && vite build`) — passed; `MonitorDev` excluded from production bundle. Pre-existing Vite >500 kB chunk warning on `ZoneMap`/`index` unchanged.
- **Live browser check (headless Edge + Playwright) against `npm.cmd run mock` + `npm.cmd run dev` on `/police/monitor-dev`:**
  - Logged in as `police1@demo.local`; loaded a recorded looping 640×360 WebM video file and streamed to the mock server (`VITE_USE_MOCKS=1`): observed live HUD updates (`Source count 5`, `Zone smoothed 4.5`, `Zone density 0.2 people/m²`, `Zone level Warning`, `FPS 2.9`, `Latency p50: 4 ms · p95: 6 ms`, `Drops 0`), `Overlay canvas` (`640×360`, 7006 non-zero drawn pixels), `max_in_flight: 1` across 16 WebSocket frames, confidence toggle (`Show conf` -> `Hide conf`), and zero horizontal overflow at `360px` width.
  - Switched to Webcam mode (`--use-fake-device-for-media-stream`): observed `hasSrcObj: true`, live `frame:result` updates in HUD (`Source count 3`, `Drops 0`), and verified `Reset` ended all `MediaStreamTrack`s (`['ended']`).
  - Zero browser console errors and zero page errors.

## Blocked / questions for Person B

- None blocking F4a. Ready for F4b (`SourcePicker`, `/police/monitor`, `/police/zones/:id` live chart) when assigned.

## Requests for AI-A (backend)

- None.

## Using: mock server (`VITE_USE_MOCKS=1`)

All F4a hooks and browser checks ran against the local mock server (`frontend/mock-server/server.ts`).

## Untested / known issues

- Physical webcam hardware LED behaviour, mobile browsers (Android Chrome / iOS Safari), and physical insecure HTTP LAN tunnel access were not tested in this environment (verified via fake media stream and mocked `window.isSecureContext`).
- Live integration against the real Flask + YOLOv8n (`be/b5b`) backend detector worker was not run in F4a (scheduled after/alongside F4b).
- `vitest-axe` in `MonitorHud` ran in jsdom with `color-contrast` disabled (jsdom limitation; theme tokens in `index.css` were previously verified by `contrast.test.ts`).

## Next 3 steps

1. Await F4b assignment (`SourcePicker`, `/police/monitor` production page, `/police/zones/:id` live view + Recharts chart, rolling series store integration).
2. Run joint M4 integration check against real Flask backend (`DETECTOR_BACKEND=ultralytics`, `VITE_USE_MOCKS=0`) with webcam and crowd video.
3. Proceed to F5 (PWA & Web Push) after F4 review.

## Lighthouse / axe results once available

- `vitest-axe` on `MonitorHud` passed with 0 violations (`color-contrast` excluded in jsdom). Lighthouse not run for F4a (dev-only harness).
