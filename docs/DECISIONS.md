# docs/DECISIONS.md — Architecture Decision Records

One paragraph per decision. Format: **Decision**: … **Rationale**: … **Impact**: …

---

**B0 — Polygon area helper is a single shared function.**
*Decision:* `app/core/geometry.py:polygon_area_m2()` is the sole implementation of zone area
calculation. It uses a local equirectangular projection (metres per degree at the polygon's
centroid latitude) followed by the shoelace formula.
*Rationale:* The plan requires this function to be reused by both `flask seed-demo` and
`ZoneService` (B2 validation). One implementation prevents drift.
*Impact:* B2 must import from `app.core.geometry`; no other area calculation is permitted.

---

**B0 — Werkzeug upload stream factory overridden to prevent temp files.**
*Decision:* `MemoryRequest` overrides `_get_file_stream` to always return `io.BytesIO()`.
*Rationale:* Contract §1 requires that citizen report images are processed in RAM and never
written to disk. Werkzeug's default spools files >500 KB to `SpooledTemporaryFile` on disk.
*Impact:* B7 must test that no temp file appears for uploads >500 KB.

---

**B0 — `trusted_proxy_count` defaults to 0 (no proxy) in development and tests.**
*Decision:* `TRUSTED_PROXY_COUNT=0` in `.env.example` default comment; test conftest sets it
explicitly to 0. The tunnel deployment sets it to 1 in the demo `.env`.
*Rationale:* Without this, `ProxyFix` would strip one hop from the IP chain, making `remote_addr`
wrong. With `x_for=0`, ProxyFix is a no-op — safe for local dev.
*Impact:* When demoing behind `cloudflared`, `TRUSTED_PROXY_COUNT=1` must be set in `.env`.

---

## 2026-11-27 — F0 mock expiry control

Person B approved `POST /__mock/auth-expired` as a loopback-only mock control outside `/api/v1`. It expires mock access tokens and disconnects authenticated sockets after `auth:expired`; refresh tokens remain usable. This is not a production endpoint or a shared contract change. No additional client-to-server socket event was introduced.

## 2026-11-27 — F0 dependency compatibility

Person B approved shadcn supporting packages `tw-animate-css`, `next-themes`, and `@types/node`, `@types/react`, `@types/react-dom`, `@types/express`, `@types/cors`. The current Vite template selected TypeScript 7, while typescript-eslint 8.74 supports TypeScript below 6.1, so F0 uses TypeScript 6.0. The generated font and `cn` dependency were removed; system fonts and the plan-listed clsx/tailwind-merge are used. Requested React Hook Form components use shadcn's official new-york form registry because the current nova preset skipped that wrapper.

## 2026-11-28 — Display timezone resolved (browser-local UI, IST analytics)

*Decision:* Absolute UI timestamps (such as `<Age>` hover tooltips and zone history chart tooltips) format in the browser's local timezone (`00_SHARED_CONTRACT.md` §14.5), while relative times show `"N s ago"`. Server-computed analytics (`peak_hours`) remain explicitly bucketed in `Asia/Kolkata` (`IST`, `UTC+5:30`) per §1 and §5.
*Rationale:* Resolves the earlier §1 vs §14.5 ambiguity consistently with F3a's existing `<Age>` implementation while preserving IST venue-hour bucketing for analytics.
*Impact:* Police/public timestamp tooltips stay browser-local; F7 analytics keeps the explicit `IST` label.

---

**B5b — Keep PyTorch `.pt` CPU backend as default over OpenVINO/ONNX export.**
*Decision:* Keep `people_model.pt` (`UltralyticsDetector` with PyTorch CPU `+cpu` wheel) as the default `MODEL_PATH` runtime instead of converting/defaulting to OpenVINO or ONNX.
*Rationale:* On the target laptop (`AMD Ryzen 7 7840HS`), running `eval/eval_latency.py` with `DETECTOR_BACKEND=ultralytics` and `imgsz=640` through the full spawned worker + Socket.IO pipeline measured `infer_ms` `p50=36.67 ms` / `p95=112.78 ms` and end-to-end `p50=45.61 ms` / `p95=123.96 ms` (target `< 1500 ms`), leaving >12x latency headroom without adding compiled-runtime dependencies (`openvino` / `onnxruntime`).
*Impact:* Deployment stays simpler with one `.pt` artifact and `pip check` stays clean; OpenVINO/ONNX export can still be added later if deployed on slower CPUs.
