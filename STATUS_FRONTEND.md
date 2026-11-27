# Frontend status — 27 November 2026

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
