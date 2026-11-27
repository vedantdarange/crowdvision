# 02 — Frontend Implementation Plan (Person B + AI-B)

> **Scope:** everything under `/frontend`, plus `/contract/types.ts`, `/contract/examples/`, and the mock server.
> **Prerequisite:** read `00_SHARED_CONTRACT.md` completely. Endpoints, events, enums, data shapes and domain rules are defined there and are **not** repeated here. This plan tells you *how* to build the UI and *in what order*.

---

## 0. Kickoff prompt (paste at the start of every AI-B session)

```
You are AI-B, the frontend + UX engineer for the "Crowd Safety Monitor" college project
(Vite + React 19 + TypeScript strict + Tailwind v4 + shadcn/ui). Person B is your human.
1. Read 00_SHARED_CONTRACT.md, then 02_FRONTEND_PLAN.md, then STATUS_FRONTEND.md, then docs/DECISIONS.md.
2. Work on exactly one phase at a time (F0..F8). Follow its tasks and acceptance criteria.
3. Never edit /backend. Never invent endpoints/fields/events/enum values; if the contract lacks something,
   stop and propose a contract change (contract §2.5). Types come from contract/types.ts only.
4. Build against the mock server (VITE_USE_MOCKS=1) until the matching backend phase is merged, then switch to the real API.
5. Every screen has loading (skeleton), error (retry) and empty states, works at 360 px, and is keyboard accessible.
6. Write tests with the code, run them, and report the results.
7. At the end, update STATUS_FRONTEND.md (done / in progress / blocked / next / requests for AI-A).
Skills to apply: frontend-developer, frontend-ui-engineering, frontend-dev-guidelines.
```

---

## 1. Responsibilities
1. A mobile-first responsive SPA for four audiences: anonymous visitor, citizen, police, admin (screens in §6).
2. Realtime layer: one Socket.IO connection, cache updates, resync on every `hello` (contract §7).
3. Camera/video pipeline in the browser: capture frames, pace them, display detection overlay and HUD (contract §8).
4. Alerts experience for police: banner, siren, vibration, desktop/phone notifications, installable PWA with Web Push (contract §9).
5. Map experience: live zone polygons (MapLibre) and the admin polygon editor (Terra Draw + Turf).
6. Mock server + fixtures so work never blocks on the backend.
7. Accessibility, responsive polish, and the demo run.

---

## 2. Skill guidance translated to our stack

The frontend skills assume MUI and TanStack Router. We keep their **principles** and use the stack the team agreed on:

| Skill rule | What we do |
|---|---|
| Feature-based folders, small focused components | `src/features/<feature>/{api,components,hooks,store,types,index.ts}` |
| Suspense-first data loading, no `isLoading` early returns | **TanStack Query `useSuspenseQuery`** inside components wrapped by `<SuspenseBoundary>` (skeleton fallback) + error boundary with retry |
| Lazy-load heavy components and routes | `React.lazy` / router `lazy` for every route; map, charts and the editor are separate chunks |
| Strict TypeScript, explicit prop types, no `any` | `strict: true`, `noUncheckedIndexedAccess`; contract types only |
| Import aliases | `@/` → `src/`, `@contract/` → `../contract/` |
| MUI + `sx` styling | **Tailwind v4 + shadcn/ui** (Radix/Base UI primitives); no inline style objects except dynamic map/canvas values |
| TanStack Router | **React Router** (data router, `createBrowserRouter`; install `react-router` and import from it — check the installed version's docs for the exact package and imports) |
| One user feedback mechanism | `sonner` toasts for success/error feedback |
| Performance: memoize, debounce, avoid re-render storms | `React.memo` for list rows; selector-based Zustand; throttle chart updates; rolling buffers |
| Frontend risk scoring (FFCI) | Table in §3 — risky modules are split before building |
| UI quality (not "AI-looking") | Design rules in §5: neutral palette, one accent, semantic colour only for status, real spacing scale, accessible contrast |

---

## 3. Frontend risk assessment (FFCI)

`FFCI = (Architecture Fit + Reusability + Performance safety) − (Complexity + Maintenance burden)`, each 1–5 (**Performance safety:** 5 = safe). Healthy ≥ 8 · watch 5–7 · ≤ 4 means split or simplify **before** building.

| Module | A | R | P | C | M | Naive | Decision | After |
|---|---|---|---|---|---|---|---|---|
| Live zone map (polygons by level) | 4 | 4 | 3 | 3 | 3 | 5 | Split into dumb `ZoneMap` + `useZoneLayers` hook; update GeoJSON via `setData`, never recreate layers | 5+5+4−(3+2) = 9 |
| **Camera frame streamer** | 4 | 3 | 3 | 4 | 3 | 3 | Split into `useWebcam`/`useVideoFile`, `useFrameStreamer` (pacing), `DetectionOverlay`; unit-test pacing with fake timers | 5+4+4−(3+2) = 8 |
| **Admin zone editor** (Terra Draw) | 4 | 3 | 4 | 4 | 3 | 4 | Isolate in `ZoneDrawControl`; the rest of the form knows only "a GeoJSON polygon + area" | 5+4+4−(3+3) = 7 |
| **Alert center** (banner, siren, vibrate, notifications) | 4 | 4 | 4 | 4 | 3 | 5 | Split: `useAlertAudio`, `useWebPush`, `AlertBanner`, `AlertCenter` orchestrator | 5+4+4−(3+2) = 8 |
| Alert queue + actions | 5 | 4 | 4 | 3 | 2 | 8 | Fine; optimistic updates with rollback | 8 |
| Live charts | 5 | 5 | 4 | 2 | 2 | 10 | Rolling buffer, animations off | 10 |

---

## 4. Dependencies

Use a current Node LTS that the Vite release you install supports (read the engine requirement printed by `npm create vite` / the Vite docs; do not assume a version number). Add libraries only from this list without asking the human.

| Purpose | Package |
|---|---|
| Core | `react`, `react-dom`, `react-router`, `typescript`, `vite`, `@vitejs/plugin-react` |
| Styling / UI | `tailwindcss` (v4) + `@tailwindcss/vite`, shadcn/ui (CLI-generated components), `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`, `sonner` |
| Server state | `@tanstack/react-query` |
| Client state | `zustand` |
| Forms/validation | `react-hook-form`, `zod`, `@hookform/resolvers` |
| Realtime | `socket.io-client` (4.x; ships its own types) |
| Maps | `maplibre-gl`, `@vis.gl/react-maplibre`, `@watergis/maplibre-gl-terradraw` (+ `terra-draw` peer), `@turf/area`, `@turf/centroid` (import the modular packages only — never the whole `@turf/turf`) |
| Charts | `recharts` (via shadcn chart components) |
| Utilities | `date-fns`, `react-error-boundary` |
| PWA | `vite-plugin-pwa` (**injectManifest** mode) + the `workbox-*` packages it asks for |
| Tests | `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `msw`, `vitest-axe` |
| Lint/format | `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`, `prettier` |
| Mock server (dev only) | `express`, `socket.io`, `cors`, `tsx` |

Verify exact option names of `@watergis/maplibre-gl-terradraw` and `vite-plugin-pwa` against the installed versions' docs.

---

## 5. Architecture and design system

### 5.1 Directory structure
```
frontend/
├─ index.html  vite.config.ts  tsconfig.json  eslint.config.js  .env.example
├─ mock-server/                  # Express + socket.io driven by /contract/examples (npm run mock)
├─ public/ (icons 192/512, favicon)
└─ src/
   ├─ main.tsx  sw.ts            # service worker (push + notificationclick)
   ├─ app/
   │  ├─ router.tsx              # route tree, lazy routes, RequireRole guards
   │  ├─ providers.tsx           # QueryClient, Theme, Toaster, RealtimeProvider
   │  └─ layouts/                # PublicLayout, PoliceLayout, AdminLayout, AuthLayout
   ├─ components/
   │  ├─ ui/                     # shadcn generated
   │  ├─ SuspenseBoundary.tsx  ErrorFallback.tsx  EmptyState.tsx  PageHeader.tsx
   │  └─ status/                 # LevelBadge, TrendIcon, DensityValue, StatusChip, ConnectionDot
   ├─ features/
   │  ├─ auth/        (api, store/session, LoginForm, RegisterForm, RequireRole, useAuthRefresh)
   │  ├─ zones/       (api, hooks, ZoneMap, useZoneLayers, ZoneCard, ZoneSheet, ZoneDetail, history chart)
   │  ├─ alerts/      (api, AlertQueue, AlertCard, AlertDetail, ActionDialog, AlertCenter, AlertBanner, useAlertAudio)
   │  ├─ monitor/     (useWebcam, useVideoFile, useFrameStreamer, DetectionOverlay, MonitorHud, SourcePicker)
   │  ├─ advisories/  (api, AdvisoryList, AdvisoryForm)
   │  ├─ reports/     (api, CrowdReportForm, SosForm, MyReports, ReportReviewQueue)
   │  ├─ push/        (useWebPush, ArmAlertsButton, InstallHint)
   │  ├─ realtime/    (socket singleton, RealtimeProvider, cache updaters, useRealtimeStatus)
   │  ├─ admin/       (zones: ZoneEditor+ZoneDrawControl, sources, users, settings, analytics, audit)
   │  └─ help/        (HelpPage)
   ├─ lib/            (apiClient.ts, queryClient.ts, queryKeys.ts, socket.ts, format.ts, geo.ts, mapStyle.ts, constants.ts)
   └─ types/          (re-exports from @contract/types)
```
Each feature exposes a public API through `index.ts`; other features import only from there.

### 5.2 Design rules (so it does not look generic)
- **Palette:** neutral slate surfaces, **one** accent (deep teal), and status colours used *only* for status. No purple/blue gradients, no decorative glassmorphism, no emoji as icons.
- **Level tokens** (CSS variables in the Tailwind `@theme`): SAFE green (~`#15803d`), WARNING amber (fill `#f59e0b`, text `#92400e`), CRITICAL red (~`#b91c1c`), NO_DATA slate (~`#64748b`). Check contrast ≥ 4.5:1 for text on its background in light and dark.
- **Never colour alone:** `LevelBadge` = colour + icon (check-circle / alert-triangle / octagon-alert / wifi-off) + text label. Map CRITICAL zones also get a thicker outline.
- **Typography:** system UI font stack or one web font (e.g. Inter); `text-base` body; tabular numbers for densities and counts.
- **Spacing:** Tailwind scale only (4/8/12/16/24/32); 16 px side gutter on mobile; touch targets ≥ 44 px; big, unmistakable primary buttons for police actions and SOS.
- **Responsive:** design for 360 px first; breakpoints 360 / 768 / 1024 / 1440. Bottom tab bar on mobile, sidebar from `lg`. No horizontal page scroll.
- **Dark mode:** class-based; police/admin default dark (control-room feel), public default light; toggle in the header; persist choice.
- **Motion:** minimal; respect `prefers-reduced-motion` (no pulsing/flashing then — use static emphasis).
- **States:** every list/page has skeleton, error-with-retry, and empty state with a clear next action.
- **Copy:** plain language; show relative time ("12 s ago") with absolute time in a tooltip/title.

### 5.3 Coding standards
1. TypeScript strict; no `any`; props typed; contract types only (`@contract/types`).
2. Data fetching only via query hooks in `features/*/api`; components never call `fetch`.
3. Server state in TanStack Query, ephemeral client state in Zustand (session, connection status, audio armed/muted, live series buffers). Never duplicate REST data in Zustand.
4. Components < ~200 lines; extract hooks; pure helpers in `lib/`.
5. Forms: React Hook Form + Zod; show field errors from `ApiError.details`.
6. No `console.log` in committed code.
7. Accessibility: semantic HTML, labelled inputs, focus management in dialogs, `aria-live` for alerts, keyboard operable.
8. `localStorage` access always inside `try/catch`.
9. "Updated N s ago" for a zone: public screens use `PublicZoneState.updated_at` (already the live-state time); police/admin screens use `ZoneState.live_updated_at`. `null` = no data yet → show "No data yet". `Zone.updated_at` (inherited by `ZoneState`) only means "configuration changed" and is never used for "updated N s ago".

---

## 6. Screens and routes

Role hierarchy: `admin ⊃ police ⊃ citizen ⊃ public`. `RequireRole` redirects unauthenticated users to `/login?next=…` and shows a Forbidden page for the wrong role.

### 6.1 Public (no login)
| Route | Screen | Key content |
|---|---|---|
| `/` | Live map | Zone polygons coloured by level, legend, connection dot, bottom sheet (mobile)/side panel (desktop) listing zones with level, trend, density; tap a zone → sheet |
| `/zones/:id` | Zone detail | `LevelBadge`, trend arrow, density, "updated 12 s ago", zone advisories, "less crowded nearby" (from `/zones/{id}/public`) |
| `/advisories` | Advisories | Live list (newest first), severity chips |
| `/help` | Help | Emergency numbers (tap-to-call `tel:`), medical points, exits (from `/help-info`), privacy notice |
| `/login`, `/register` | Auth | Forms; register creates a citizen |

### 6.2 Citizen (login)
| Route | Screen | Key content |
|---|---|---|
| `/report/crowd` | Crowd report | GPS permission + accuracy, photo via `<input type="file" accept="image/*" capture="environment">`, client-side downscale to ≤ 1280 px JPEG, submit multipart, result card ("N people counted, ≈ x.x /m² in *Zone*"), privacy note "Your photo is not stored. The count, location and note are kept for up to 30 days." |
| `/report/sos` | SOS | Large type buttons (Medical, Crush risk, Fire, Lost child, Other), optional note, auto location with manual-retry, confirm step, success screen with reference id; always-visible line "In immediate danger, call 112 — this app is not a replacement for emergency services" |
| `/my-reports` | My reports | Status of each report (live via `report:updated`) |

### 6.3 Police (and admin)
| Route | Screen | Key content |
|---|---|---|
| `/police` | Dashboard | Connection + "Alerts armed" chips, active-alert count, map with zones, live alert feed, zone cards (level, density, trend, sources online/offline) |
| `/police/alerts` | Alert queue | Tabs **Active / All(history)**, filters (status, level, zone, date range), table on desktop / cards on mobile, row actions Acknowledge → Responding → Resolve (note dialog), optimistic updates. A `NEW` alert whose `condition_active` is false shows the chip **"Condition cleared — awaiting review"** (CRITICAL-peak alerts are not auto-cleared). Resolving while the zone is still over the limit is allowed; the dialog notes "a new alert is raised if it is still over the limit after `reraise_after_s`" |
| `/police/alerts/:id` | Alert detail | Summary, timeline (`events`, including `FEED_LOST` → "Camera feed lost" and `FEED_RESTORED` → "Camera feed restored", and a `CREATED` event with `data.reason = STILL_ACTIVE_AFTER_RESOLVE` → "Raised again: still over the limit"), actions, zone mini-map, link to zone live view |
| `/police/zones/:id` | Zone live view | `MonitorHud`-style stats, count/density chart with warning (amber) and critical (red) reference lines, history range (30 m / 2 h / 24 h), sources with status, zone advisories |
| `/police/monitor` | Camera control | Pick zone → pick/create source (police create sources without a coverage area; only admins set it) → **Webcam** or **Video file** → Start; video + overlay + HUD (count, smoothed, density, level, FPS, latency, drops); one active stream per tab |
| `/police/reports` | Report review | Pending first; verify/dismiss with note; map pin; SOS visually prominent; `/police/reports?focus=<id>` scrolls to and highlights that report (target of the SOS push notification) |
| `/police/advisories` | Broadcast | Active list with retract; form (title, body, severity, zone or global, optional expiry) |

### 6.4 Admin only
| Route | Screen | Key content |
|---|---|---|
| `/admin/zones` | Zone list | Table + actions; "New zone" |
| `/admin/zones/new`, `/admin/zones/:id/edit` | Zone editor | Map with Terra Draw polygon tool, area preview (m², read-only; the server recomputes it and its value wins), name, description, mode, thresholds (defaults 3.0 / 4.0; COUNT thresholds when mode = COUNT), inline validation (warning < critical) |
| `/admin/sources` | Sources | List per zone, create/edit/disable, **coverage area (m²)** (admin only) with helper text "area your camera actually sees" |
| `/admin/users` | Users | List, create police/admin, enable/disable, role change (cannot change self) |
| `/admin/settings` | Settings | Detection/alert settings with units and safe ranges (including `reraise_after_s`, default 60 s); help info editor |
| `/admin/analytics` | Analytics | Alerts per zone, avg ack/resolve times, peak hours (labelled "IST"; the API returns `timezone: 'Asia/Kolkata'`), reports by status, CSV download |
| `/admin/audit` | Audit log | Filterable table |

### 6.5 Navigation
Public: bottom tabs *Map · Advisories · Report · Help · Account* ("Report" prompts login). Police: *Dashboard · Alerts · Monitor · Reports · More*. Admin: same plus an *Admin* group (sidebar on desktop, "More" sheet on mobile). Header shows connection dot, theme toggle, user menu.

---

## 7. Data layer and realtime

### 7.1 `apiClient`
A single fetch wrapper (no axios): base `VITE_API_BASE`; attaches `Authorization`; parses the `{data}` / `{data,pagination}` / `{error}` envelopes; throws `ApiRequestError {status, code, message, details}`; skips `Content-Type` for `FormData`; on `401 UNAUTHENTICATED` performs a **single-flight** token refresh then retries once, otherwise clears the session and redirects to `/login`. Tokens in `localStorage` (try/catch), access token mirrored in memory.

### 7.2 Query keys (`lib/queryKeys.ts`)
`['config']` · `['help']` · `['zones','live']` · `['zones','public',id]` · `['zones','list']` · `['zones','detail',id]` · `['zones','history',id,range]` · `['alerts',filters]` · `['alerts','detail',id]` · `['advisories',zoneId|'all']` · `['reports',filters]` · `['reports','mine']` · `['sources',zoneId|'all']` · `['users',filters]` · `['settings']` · `['analytics',range]` · `['audit',filters]`.

### 7.3 Realtime provider
One **module-level singleton** socket (`lib/socket.ts`), connected from `RealtimeProvider` with `auth: { token }`. It must survive React StrictMode double-mounts (no connect/disconnect churn tied to component lifecycle). Reconnect with the library's backoff.

| Socket event | Client reaction |
|---|---|
| `hello` | set status "connected"; **invalidate all active queries** (resync) |
| `auth:expired` | refresh token, then reconnect with the new token. The server also disconnects the socket (expired token, disabled or demoted user), so reconnect even if the connection drops; if the refresh fails, log out |
| `zone:update` | upsert into `['zones','live']` and `['zones','public',id].state` |
| `zone:detail` | upsert into `['zones','list']`, `['zones','detail',id]`; push `{ts, count, density}` into the rolling live-series store (max 300 points per zone) |
| `alert:new` / `alert:updated` | upsert into active alert lists (`setQueriesData`) and `['alerts','detail',id]`; invalidate history lists lightly |
| `alert:escalated` | everything above + `AlertCenter` (banner, siren, vibration) |
| `advisory:new` / `advisory:retracted` | upsert / remove in `['advisories',*]`; toast for citizens. `advisory:retracted` is also sent when an advisory **expires** — treat it the same |
| `report:new` / `report:updated` | invalidate `['reports',*]` and `['reports','mine']`; toast for the owner. For police, an `SOS` `report:new` of type `CRUSH_RISK`/`FIRE`/`MEDICAL` goes to `AlertCenter` (banner + siren, link `/police/reports?focus=<id>`); `LOST_CHILD`/`OTHER` only add a list entry and a toast |
| `source:status` | update the source inside zone cache entries |
| disconnect | show a persistent "Reconnecting… live data may be stale" bar; `LevelBadge` shows last-known data with an age warning |

### 7.4 Optimistic updates
Alert actions update the cache immediately and roll back on error (`409 INVALID_TRANSITION` → toast "Someone already updated this alert" + refetch).

---

## 8. Key components specified

### 8.1 Live map (`ZoneMap`, `useZoneLayers`)
- `@vis.gl/react-maplibre` map with OpenFreeMap vector style (`https://tiles.openfreemap.org/styles/liberty` — verify the current style URL on openfreemap.org; keep the URL in `lib/mapStyle.ts`). Import `maplibre-gl/dist/maplibre-gl.css`. Keep the attribution control visible.
- One GeoJSON source (`zones`) + fill layer coloured by `level` using a `match` expression, outline layer (CRITICAL thicker), label layer (`name` + density). Update with `source.setData(featureCollection)` from memoized query data; **never** add/remove layers on updates.
- Fit bounds to all zones on first load; clicking a polygon selects the zone (sheet/panel). Layout must not shift when the sheet opens.
- Reduced motion → no pulsing animation.

### 8.2 Frame streamer (`monitor/`)
- `useWebcam(facing)`: `getUserMedia({ video: { facingMode, width: { ideal: 1280 } }, audio: false })` → `<video autoPlay playsInline muted>`. Error mapping: not allowed → "Allow camera access"; no device; **`!window.isSecureContext` → "Camera needs HTTPS (use the tunnel URL)"**. Always `track.stop()` on unmount and on stop.
- `useVideoFile()`: file input → `URL.createObjectURL` (revoke on cleanup); `loop` toggle; detect loop restart (currentTime decreases) and mark the next frame `reset: true`.
- `useFrameStreamer({ video, sourceId, enabled })`:
  1. read `/config` (`target_fps`, `frame_width`, `jpeg_quality`);
  2. loop: when `enabled` and no frame in flight and `now − lastSent ≥ 1000/target_fps`: draw video to a hidden canvas (width = `frame_width`, height keeps aspect), `canvas.toBlob(cb, 'image/jpeg', quality)` (**never** PNG/WebP — Safari silently returns PNG for WebP), `await blob.arrayBuffer()`, `socket.emit('frame:submit', {source_id, seq, captured_at, reset, width, height, image})`, mark in flight;
  3. on matching `frame:result` (by `seq`) clear in-flight and publish the result; **2 s timeout** also clears in-flight (count a drop). If the result is `error: 'SOURCE_IN_USE'` (another tab/device is already streaming this source), **stop the streamer** and show "This source is already being streamed elsewhere" — never retry in a loop;
  4. first frame after (re)start has `reset: true`; `seq` starts at 1;
  5. pause on `document.hidden` for webcam; expose `{ fps, latencyMs (p50/p95), drops, lastResult }`;
  6. stop and clean up on unmount/disable.
- `DetectionOverlay`: absolutely positioned canvas over the video; map normalised boxes to the *displayed* video rectangle (account for `object-fit: contain` letterboxing and `devicePixelRatio`); clear when no result for 1 s.
- `MonitorHud`: **this source's** raw `count`, plus the **zone-level** `smoothed_count`, `density` and `level` (label them "Zone" — with several sources in a zone these are the zone's values, not this camera's), FPS, latency, drops; "DETECTOR_BUSY" shown as a subtle warning, not an error.
- Unit-test pacing with fake timers and a mock socket: one in flight, timeout, reset flag, seq increments, cleanup.

### 8.3 Alert center (`alerts/`)
- `AlertCenter` is mounted once in `PoliceLayout`/`AdminLayout`. It listens to `alert:new` and `alert:escalated`.
- **Arming:** a prominent **"Arm alerts"** button (`ArmAlertsButton`) performs, in one tap: create/resume `AudioContext` and play a short test tone, `Notification.requestPermission()`, subscribe to Web Push, brief `navigator.vibrate(30)` if supported. Browsers block sound/notifications without a user gesture. If not armed, show a persistent amber chip "Alerts not armed — tap to enable".
- **Banner:** persistent top banner (`role="alert"`, `aria-live="assertive"`) with zone, level, density and **Acknowledge** / **Open** buttons; stays until the alert leaves `NEW`.
- **SOS:** a police `report:new` of kind `SOS` with type `CRUSH_RISK`, `FIRE` or `MEDICAL` shows the same kind of banner ("SOS — Crush risk", zone/location, **Open** → `/police/reports?focus=<id>`) and uses the same siren; the banner stays until the report is reviewed.
- **Siren:** synthesized with Web Audio (two-tone oscillator, no audio file), repeats every ~10 s while a CRITICAL alert is `NEW` (cap ~60 s), stops on acknowledge; mute toggle; volume hint "check device volume / silent switch".
- **Vibration:** `navigator.vibrate?.([300,100,300])` feature-detected (unsupported on iOS).
- **Title flash** on the browser tab while an unacknowledged alert exists.
- Honour `prefers-reduced-motion` for flashing.

### 8.4 PWA and Web Push (`push/`, `sw.ts`)
- `vite-plugin-pwa` with `strategies: 'injectManifest'`, `srcDir: 'src'`, `filename: 'sw.ts'`; manifest: name, short_name, `display: 'standalone'`, `start_url: '/'`, theme/background colours, icons 192/512 (placeholders OK).
- `sw.ts`: `push` handler parses the JSON payload (contract §9) and **always** calls `showNotification` (required with `userVisibleOnly`); handle both payload kinds (`kind: "ALERT"` and `kind: "SOS"`, contract §9); use `tag` from the payload, `requireInteraction: true` when `level === 'CRITICAL'` or `kind === 'SOS'`, `vibrate`, `data: { url }`. `notificationclick`: close, focus an existing window and navigate, else `clients.openWindow(url)`. Do **not** precache `/api` or `/socket.io`.
- `useWebPush()`: only if `vapid_public_key` from `/config` is non-null and `'serviceWorker' in navigator && 'PushManager' in window`; subscribe with `userVisibleOnly: true` and `applicationServerKey`; `POST /push/subscriptions`; unsubscribe on logout (`DELETE`); handle `denied` with a clear help message.
- `InstallHint`: on iOS Safari explain "Share → Add to Home Screen" (push only works for the installed app on iOS 16.4+); on Android show the install prompt when available.
- Use `ServiceWorkerRegistration.showNotification` from page code too; **never** `new Notification()` (throws on mobile).
- Requires HTTPS (the tunnel); `localhost` works on the laptop only.

### 8.5 Admin zone editor (`ZoneEditor`, `ZoneDrawControl`)
- Map shows existing zones read-only (muted) and the polygon being edited.
- `ZoneDrawControl` wraps `@watergis/maplibre-gl-terradraw` (polygon, select/edit, delete modes). It exposes `onChange(polygon: PolygonGeometry | null)`; the rest of the form never touches Terra Draw. Clean up the control on unmount.
- On every change compute `area_m2 = turf.area(feature)` (square metres) and `centroid` as a **preview**; show "Area: 38.2 m²" read-only. The server recomputes the area and stores its own value (`422` if the client value is more than 10 % off); show the saved value after submit. Require a valid closed polygon with ≥ 3 distinct vertices.
- Form (Zod): name required/unique-looking, mode, thresholds (`warning < critical`, positive), COUNT thresholds required when mode = COUNT. Submit `POST/PATCH /zones`; map `422` field errors onto fields.
- Coverage of a *camera* is configured on the source (`coverage_area_m2`, admin only), not by shrinking the zone.
- Deleting a zone returns `409 CONFLICT` while it has an open alert: show "Resolve its alert first". Zone names must be unique among active zones (a deleted zone's name can be reused).

### 8.6 Charts
Recharts line chart with `ReferenceLine` for warning (amber) and critical (red); X axis time; Y axis density (or count in COUNT mode); rolling window ≤ 300 points; `isAnimationActive={false}`; tooltip with level label; accessible summary text ("Currently 3.4 people per square metre, rising") next to the chart.

### 8.7 Citizen report screens
- Geolocation: `navigator.geolocation.getCurrentPosition` with a 10 s timeout, high accuracy; show accuracy radius; allow manual retry; clear error if denied (explain why location is needed).
- Photo: native file input with `capture`; downscale client-side (canvas → JPEG ≤ 1280 px, quality 0.8) before upload; show spinner and progress; handle `413`, `429`, `503`.
- Always show the privacy note. SOS requires a confirm step to avoid accidental sends.

---

## 9. Mock server and fixtures (build first — F0)

- `contract/examples/*.json`: one fixture per shape named in the contract (e.g. `zone_state_public.json`, `zone_state.json`, `alert.json`, `alert_detail.json`, `advisory.json`, `report_crowd.json`, `report_sos.json`, `frame_result.json`, `config.json`, `settings.json`, `analytics_summary.json`, `error_validation.json`, `error_forbidden.json`). Fixtures must type-check against `contract/types.ts` (a small script/test asserts that).
- `frontend/mock-server` (Express + socket.io on `:5001`) implements the REST endpoints with fixture data and in-memory state: login for the seed users (fake tokens that encode the role), role checks (so guards are exercised), alert transitions with `409` on invalid ones, pagination, `422` validation errors for forms.
- Scenario engine emitting realtime events: default loop `ramp` on zone 1 (SAFE → WARNING → CRITICAL → back), optional `GET /__mock/scenario?name=spike|flap|offline&zone=1`; also emits `advisory:new`, `report:new`. `frame:submit` is answered with a synthetic `frame:result` (random boxes) so the monitor UI can be built without the detector.
- `VITE_USE_MOCKS=1` points the Vite proxy at `:5001`; `0` points at Flask `:5000`.
- MSW (unit/component tests) uses the same fixtures.
- Optional dev-only **contract guard**: when `import.meta.env.DEV`, validate responses of key endpoints with Zod schemas and `console.warn` on mismatch (remove or keep behind a flag).

---

## 10. Phases

Each phase: **tasks → acceptance → depends on backend**. Commit small PRs; update `STATUS_FRONTEND.md` at the end.

### F0 — Scaffold, tokens, mock server (day 1–2, **M0**)
**Tasks:** Vite + React + TS strict; Tailwind v4; shadcn init (button, card, dialog, sheet, tabs, table, form, input, select, badge, skeleton, sonner, dropdown, tooltip); aliases `@/` and `@contract/`; ESLint/Prettier; router skeleton with layouts and lazy routes; theme tokens (§5.2) + dark mode; `apiClient`, `queryClient`, `queryKeys`, `SuspenseBoundary`, `ErrorFallback`, `EmptyState`; `contract/types.ts` (verbatim from contract §5, `CONTRACT_VERSION = "1.1.0"`) and the fixtures (include a `FEED_LOST` event, a `ZoneState` with `live_updated_at: null`, and an SOS `report:new`); mock server (§9); Vitest setup + first test.
**Acceptance:** `npm run dev` and `npm run mock` show routed placeholder pages; `LevelBadge` renders all four levels with icon + text; fixtures type-check; both humans sign off the contract (M0).
**Depends on:** nothing (use mocks).

### F1 — Auth and guards (**M1**)
**Tasks:** login/register forms (RHF + Zod, server field errors), session store (tokens + user), `apiClient` refresh single-flight, `RequireRole`, redirect with `next`, role-aware navigation, logout, Forbidden/404 pages, user menu.
**Acceptance:** each seed user can log in and lands on the right home; wrong role sees Forbidden; expired access token refreshes silently (test with the mock); `401` after refresh failure logs out.
**Depends on:** B1 (works on mock before).

### F2 — Public map, zone detail, advisories, help (**M2**)
**Tasks:** `RealtimeProvider` + cache updaters (§7.3); `ZoneMap` + `useZoneLayers`; legend; bottom sheet/side panel; zone detail with alternatives; advisories page; help page; connection dot and reconnect bar; stale-data indicator; `/config` boot.
**Acceptance:** anonymous user on a 360 px screen sees seeded zones coloured by level; levels change live with the mock scenario; kill/restart the mock server → bar appears and data resyncs on reconnect; no layout shift when the sheet opens; axe checks pass.
**Depends on:** B2 (+ B3 for live data).

### F3 — Police dashboard, alerts, alert center (**M3**)
**Tasks:** `PoliceLayout`; dashboard (map + alert feed + zone cards); alert queue (tabs, filters, pagination); alert detail + timeline; action dialogs with optimistic updates; `AlertCenter`, `AlertBanner`, `useAlertAudio`, `ArmAlertsButton`; SOS banner/siren for `report:new` (§8.3); "Condition cleared — awaiting review" chip; `FEED_LOST`/`FEED_RESTORED` timeline entries; "updated N s ago" from `ZoneState.live_updated_at`; title flash; chip when not armed.
**Acceptance:** with the mock `ramp`, a banner and siren appear after arming; acknowledging stops the siren and updates all views; invalid transitions show the conflict toast and refetch; keyboard-only operation of the queue works; role guard blocks citizens.
**Depends on:** B4 (use mock until merged; then run against `flask fake-feed`).

### F4 — Monitor (webcam + video file) and zone live view (**M4**)
**Tasks:** `SourcePicker` (zone → source, create if none); `useWebcam`, `useVideoFile`, `useFrameStreamer`, `DetectionOverlay`, `MonitorHud` (source count vs zone-level values, `SOURCE_IN_USE` message); `/police/zones/:id` live chart with thresholds + history ranges; rolling live-series store.
**Acceptance:** with the mock, boxes track the synthetic results and pacing keeps one frame in flight; with the real backend, webcam count tracks people within ±1–2 in easy scenes; stopping the stream releases the camera (LED off); video loop sends `reset`; on an `http://` LAN URL a clear HTTPS message appears; HUD shows FPS/latency/drops.
**Depends on:** B5 (mock before).

### F5 — PWA and Web Push (**M5**)
**Tasks:** `vite-plugin-pwa` injectManifest, `sw.ts`, manifest/icons; `useWebPush`; `/push/test` button in the user menu; `InstallHint`; subscription cleanup on logout.
**Acceptance (on a real Android Chrome phone via the HTTPS tunnel):** install works; after arming, a CRITICAL alert produces a notification on a **locked** phone; tapping it opens `/police/alerts/:id`; `denied` permission shows guidance; no `new Notification()` anywhere.
**Depends on:** B6.

### F6 — Citizen reports, report review, advisory broadcast (**M6**)
**Tasks:** crowd report and SOS screens (§8.7); my-reports; police report review queue; advisory form + retract; toasts from realtime events.
**Acceptance:** a citizen submits both report kinds end to end; rate limit (`429`) and `503` are handled with clear messages; police verify/dismiss and the citizen's list updates live; advisory appears on the public map screen within ~2 s; image is never stored client-side after submit.
**Depends on:** B7 (+ B4 for advisories).

### F7 — Admin (**M7**)
**Tasks:** zone list + editor with `ZoneDrawControl`; sources; users; settings (with ranges/units, incl. `reraise_after_s`); analytics page with charts (IST peak hours) + CSV download; audit log; handle the zone-delete `409`.
**Acceptance:** admin draws a polygon, sees computed area, saves, and the zone appears on the public map; validation errors (`warning ≥ critical`, bad polygon) map to fields; admin cannot disable/demote self (UI blocks + server `409` handled); CSV downloads.
**Depends on:** B2, B8.

### F8 — Polish, accessibility, demo (**M8**)
**Tasks:** responsive pass at 360/768/1024/1440; empty/error/skeleton audit; axe pass on login, public map, alert queue, report forms; focus management in dialogs; performance check (Lighthouse mobile; lazy chunks; map not in the initial bundle); dark-mode contrast check; README run instructions; screenshots for the report; two full demo rehearsals using `docs/DEMO.md`.
**Acceptance:** no horizontal scroll at 360 px; Lighthouse accessibility ≥ 90 on key pages; demo script (contract §13) runs end to end twice without intervention.

---

## 11. Testing plan

| Level | What | Tool |
|---|---|---|
| Unit | `apiClient` (envelopes, refresh single-flight), cache updaters (upsert/remove), level/format helpers, geo helpers, frame streamer pacing | Vitest + fake timers |
| Component | `LevelBadge` (4 levels), `AlertCard` actions, `RequireRole`, forms with server errors, `ZoneCard` | Testing Library + MSW |
| Accessibility | login, public map/list, alert queue, report forms | `vitest-axe` |
| Contract | fixtures type-check against `contract/types.ts`; (dev) response guard | tsc + script |
| Manual | device checklist below | human |

**Device checklist:** Android Chrome (install, push on locked phone, siren, vibration, camera); iPhone Safari (map, camera over HTTPS, no push/vibrate — verify graceful fallbacks); desktop Chrome/Edge (webcam, notifications); widths 360 / 768 / 1280; dark and light; offline/reconnect behaviour.

---

## 12. Pitfalls checklist (read before coding)
1. Install `react-router` and import from it; check the installed version's docs before mixing in `react-router-dom` (do not rely on remembered version numbers).
2. Safari ignores WebP in `canvas.toBlob`; always JPEG.
3. `<video playsInline muted autoPlay>` or iOS goes fullscreen / blocks autoplay; read `videoWidth` only after `loadedmetadata`.
4. Stop every `MediaStreamTrack` on unmount (camera LED, battery, next start failing).
5. `getUserMedia`, service workers and push need a **secure context**: laptop `localhost` is fine; phones need the HTTPS tunnel.
6. `AudioContext` must be created/resumed in a user gesture; iPhone silent switch mutes web audio — show a hint.
7. Never `new Notification()`; use the service worker's `showNotification`; every push must show a notification.
8. React StrictMode double-invokes effects: keep the socket a module singleton; make camera/stream hooks idempotent.
9. MapLibre needs its CSS import; update with `setData`; remove Terra Draw control on unmount; do not import the full Turf bundle.
10. Background tabs throttle timers: pause the webcam stream when hidden; keep the video-file demo tab visible.
11. Cap live chart arrays; disable chart animations.
12. Socket.IO is at-most-once: always resync on `hello`.
13. Keep `sw.js` out of long-term caches; test updates.
14. Don't colour-code alone; test with a greyscale filter.
15. One camera tab per source: a second tab gets `SOURCE_IN_USE`. Stop and explain; do not retry in a loop.
16. Push for `kind: "SOS"` must also show a notification (same `userVisibleOnly` rule) and open `/police/reports?focus=<id>`.

## 13. `STATUS_FRONTEND.md` template
```
# Frontend status — updated <date/time>
## Phase: F_  (not started | in progress | done)
## Done since last update
## In progress
## Blocked / questions for Person B
## Requests for AI-A (backend)
## Using: mock server | real backend (which endpoints)
## Untested / known issues
## Next 3 steps
## Lighthouse / axe results once available
```
