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
