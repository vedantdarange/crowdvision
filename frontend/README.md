# Crowd Safety Monitor — frontend

Run all commands from the `frontend/` directory. **Node 24 LTS** (or `>=24.0.0`) is required. The lockfile pins the installed dependency set; use `npm ci` on another machine.

## Install & Configure

```powershell
npm.cmd ci
Copy-Item .env.example .env
```

(`npm.cmd` avoids PowerShell execution-policy blocks on `npm.ps1`; standard `npm` works in bash/zsh/cmd.) No `.env` file is committed.

## Run in Mock Mode

Start the Express + Socket.IO fixture mock server (`127.0.0.1:5001`) and the Vite dev server (`localhost:5173`):

```powershell
# Terminal 1 (mock server):
npm.cmd run mock

# Terminal 2 (Vite dev server with VITE_USE_MOCKS=1 in .env):
npm.cmd run dev
```

Open [http://localhost:5173](http://localhost:5173). When `VITE_USE_MOCKS=1`, Vite proxies `/api` and `/socket.io` to `http://127.0.0.1:5001`.

## Run Against the Real Backend

With Flask + Socket.IO running on `http://127.0.0.1:5000`:

```powershell
# Set VITE_USE_MOCKS=0 in frontend/.env (or pass it on the command line):
$env:VITE_USE_MOCKS = "0"
npm.cmd run dev
```

Or build the static production bundle so Flask serves `frontend/dist` directly (demo / tunnel mode):

```powershell
$env:VITE_USE_MOCKS = "0"
npm.cmd run build
```

See [docs/DEMO.md](../docs/DEMO.md) for the full Flask + `cloudflared` demo runbook.

## Build & Preview

```powershell
npm.cmd run build    # typecheck (DOM + service worker) and build frontend/dist/
npm.cmd run preview  # serve frontend/dist locally on port 4173
```

## Test & Verification

```powershell
npm.cmd run check:fixtures
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run format:check
node scripts/report-contrast.mjs
node scripts/smoke.mjs # while dev and mock are running
```

Tests include component unit tests (`LevelBadge`, status helpers, camera frame pacing, audio timer, PWA service worker push handlers, geo helpers), routing guards and RBAC matrices, API envelope/token-refresh integration, `vitest-axe` accessibility checks across key screens, mock HTTP/Socket.IO integration tests, and contract fixture validation (`43` fixtures). Socket tests need loopback permission. jsdom axe's canvas-dependent contrast rule is disabled in unit tests; CSS token contrast ratios (>= 4.5:1 for light & dark themes) are verified numerically by `node scripts/report-contrast.mjs` and in headless Chrome.

## Mock controls

Seed accounts: `admin@demo.local`, `police1@demo.local`, `police2@demo.local`, `citizen@demo.local`. Password comes from `SEED_PASSWORD`; `.env.example` supplies `Demo@1234` for local use. Without it, a random password is printed once on startup. Fake tokens contain the role and are held in memory; they are not production JWTs.

- The default Main Gate ramp runs SAFE → WARNING → CRITICAL → SAFE over 44 seconds, with debounce/clear timing. Stage Area contains a separate CRITICAL-peak alert awaiting review, so the Main Gate ramp can create its own alert without violating the one-open-alert rule.
- `GET http://127.0.0.1:5001/__mock/scenario?name=spike|flap|offline&zone=1` changes the synthetic input. Restart the mock to restore the default ramp and fixtures.
- `POST http://127.0.0.1:5001/__mock/auth-expired` expires all mock access tokens, emits `auth:expired`, and disconnects authenticated sockets. Refresh tokens stay valid. This control was explicitly approved by Person B and is **not** a production endpoint or a contract change.
- An advisory and crowd/SOS report are emitted every 20 seconds. Timed advisories retract after 10 seconds. SOS alternates with crowd reports.
- Browser JPEG frames receive synthetic counts/boxes; leases enforce one streamer per source, and frame responses go only to the sender. Uploaded report images are parsed in RAM and discarded. No inference occurs.
- Push is disabled (`vapid_public_key: null`); `/push/test` truthfully returns `sent: 0`. History and analytics are simulated from mock state; they are not detector measurements.
- Full production detector queues, delivery of push, long-term retention, and real-backend parity are outside this scaffold's validation. Settings validate basic types and mathematical constraints, not undocumented backend-specific numeric limits.

## Source and tooling notes

Contract source is currently named `00_SHARED_CONTRACT.md`, and the plan `02_FRONTEND_PLAN.md`. Section 5 is copied verbatim; formatters intentionally do not rewrite `contract/types.ts`. `check:fixtures` generates literal TypeScript assignments, rejecting unknown fixture files or incompatible shapes without unsafe fixture casts. Types for section 6 response wrappers and section 7/8 payloads use only documented wire fields.

Verified official setup references: [Tailwind Vite](https://tailwindcss.com/docs/installation/using-vite), [shadcn Vite](https://ui.shadcn.com/docs/installation/vite), [Vite Node requirements](https://vite.dev/guide/), [React Router 8.5.3 data installation](https://reactrouter.com/start/data/installation), [MSW 3 migration](https://mswjs.io/docs/migrations/2.x-to-3.x).

Current Vite selected TypeScript 7, incompatible with typescript-eslint's peer range; TypeScript is pinned to 6.0. The shadcn Radix nova preset provides the UI components. The generated `cn` helper/font dependencies were removed in favor of plan-listed clsx/tailwind-merge and system fonts; `tw-animate-css` and type support packages are in `package.json`, while unused F0 scaffold dependencies (`date-fns`, `next-themes`) and unused UI wrappers were cleaned up in F8.
