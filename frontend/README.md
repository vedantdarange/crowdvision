# Crowd Safety Monitor — F0

Run from the `frontend/` directory in the repository. Node 24 LTS is supported. The lockfile pins the installed dependency set; use `npm ci` on another machine.

```powershell
npm.cmd ci
Copy-Item .env.example .env
npm.cmd run mock
# In a second terminal, from frontend:
npm.cmd run dev
```

Open [the local scaffold](http://localhost:5173). `npm.cmd` avoids this machine's PowerShell execution-policy restriction on `npm.ps1`; ordinary `npm` works in other shells. The mock binds to `127.0.0.1:5001`. Vite proxies `/api` and `/socket.io` to it when `VITE_USE_MOCKS=1`, otherwise to Flask on port 5000. No `.env` is committed.

The UI is deliberately a scaffold: every planned route has a lazy placeholder. Preview workspace links expose public/police/admin navigation. Role guards and automatic 401 refresh are explicitly deferred to F1. REST authorization is enforced by the mock. Do not deploy the mock or treat preview navigation as access control.

## Verification

```powershell
npm.cmd run check:fixtures
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
npm.cmd run format:check
node scripts/report-contrast.mjs
node scripts/smoke.mjs # while dev and mock are running
```

Tests include the four LevelBadge variants and axe checks, helper formatting, theme persistence, API envelopes/headers/errors, all 24 planned route matches, verbatim contract extraction, every fixture, contrast calculations, HTTP role/validation/lifecycle behavior, and real local Socket.IO connections. Socket tests need permission to connect to loopback. jsdom axe's canvas-dependent contrast rule is disabled; eight CSS color pairs are separately checked numerically against 4.5:1.

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

Current Vite selected TypeScript 7, incompatible with typescript-eslint's peer range; TypeScript is pinned to 6.0. The shadcn Radix nova preset provides the UI components; the requested RHF form wrapper came from the official new-york registry, preserving the existing label. The generated `cn` helper/font dependencies were removed in favor of plan-listed clsx/tailwind-merge and system fonts. `tw-animate-css`, `next-themes`, and type support packages were approved by Person B.
