# Demo & Manual Verification Checklist

## M5 — Web Push on Locked Android Chrome Phone

### Prerequisites
1. Generate VAPID keys once (from `backend/` with `.venv` active):
   ```powershell
   vapid --gen
   ```
2. Set in `backend/.env` (never commit `.env`):
   - `VAPID_PUBLIC_KEY=<generated public key>`
   - `VAPID_PRIVATE_KEY=<generated private key>`
   - `VAPID_SUBJECT=mailto:<your real email>`
   - `SERVE_FRONTEND=true`
   - `TRUSTED_PROXY_COUNT=1`
3. Build the frontend once from `frontend/`:
   ```powershell
   npm run build
   ```
4. Start the backend server (`backend/`):
   ```powershell
   python wsgi.py
   ```
5. Start the HTTPS tunnel in another terminal (required by mobile browsers for Web Push & camera):
   ```powershell
   cloudflared tunnel --url http://localhost:5000
   ```
6. Ensure `GET /api/v1/config` returns your non-null `vapid_public_key`.

### Manual Test Steps
1. On an Android phone in **Chrome**, open the HTTPS `cloudflared` URL.
2. Log in as a **police** (or **admin**) account and navigate to the Police alerts / push screen (F5).
3. Tap **Arm alerts** / **Enable Web Push** and grant the browser notification permission prompt.
4. Click **Send test push** (`POST /api/v1/push/test`) -> verify `{data: {sent: >= 1}}` and that the harmless test notification appears on the phone.
5. **Lock the Android phone screen.**
6. On the laptop (or via `flask fake-feed --zone 1 --profile ramp --speed 3`), push Zone 1 (`Main Gate`) into **CRITICAL** (either with live camera people or fake feed).
7. **Verify within ~5 seconds:**
   - The locked Android phone buzzes / displays a notification with title `CRITICAL — Main Gate`, metric body, and sound/vibration.
   - Tapping the notification unlocks Chrome and opens `/police/alerts/<id>` directly to that alert.
8. **Stale subscription (`410`) check (optional):**
   - Revoke site notification permission or clear site data on the phone, send another push / trigger alert, and verify backend logs show the `410` gone subscription deleted from `push_subscriptions`.
