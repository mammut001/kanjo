# Kanjo Family Usage Server

Self-hosted report receiver and public dashboard behind Firebase Authentication (Google Sign-In) for Google AI Ultra / AI family usage tracking.

> [!TIP]
> For a comprehensive, step-by-step first-time deployment guide, see **[DEPLOY.md](DEPLOY.md)** (available in English and 简体中文).

## Architecture

- **Public unified ingress (`https://usage.example.com`)**:
  - Accessible via Cloudflare Tunnel (`family-cloudflared`).
  - Routes:
    - `POST /api/report` and `GET /healthz` → `http://family-app:8788` (report intake API)
    - All other paths for hostname `usage.example.com` → `http://family-app:8787` (public dashboard behind Firebase Google Sign-In)
    - Unmatched requests return HTTP 404.
  - Neither port (8788 or 8787) is published on public network interfaces.
  - Port 8787 can optionally be published on Tailscale IP via `PUBLISH_TAILSCALE=1`.
- **Authentication & Security**:
  - Dashboard routes protected by Firebase Authentication with Google Sign-In.
  - Pure-Python RSASSA-PKCS1-v1_5 SHA-256 ID token verification against Google JWKs.
  - Access restricted to allowlisted emails in `FAMILY_ADMIN_EMAILS`.
  - Secure server-side sessions stored in SQLite with `__Host-family_session` cookie (`Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=604800`).
  - Comprehensive hardening: strict CSP, HSTS, X-Content-Type-Options, Referrer-Policy, COOP, CSRF checks on all POSTs, client IP rate limiting (10/min), and 64 KB payload limit.
- **Storage**:
  - SQLite database stored at `/opt/family-usage/data/family.db` (inside container: `/data/family.db`).
  - Members, SHA-256 hashed bearer tokens, 7-day server sessions, daily historical reports (90-day retention), and server settings (`settings(key, value)` table).

---

## Configuration (`/opt/family-usage/family.env`)

Server configuration is read by `deploy.sh` from `/opt/family-usage/family.env`. The file is passed directly to Docker via `--env-file`.

> [!IMPORTANT]
> - Never commit real admin emails or credentials to git. Use placeholders in documentation.
> - **Values in `family.env` are literal (no shell quoting)**: Docker reads `--env-file` literally without shell quote stripping. Do not wrap values in quotes (e.g. write `FIREBASE_PROJECT_ID=your-family-usage` and `FIREBASE_WEB_CONFIG_JSON={"apiKey":...}` rather than `'{"apiKey":...}'`).

Example `/opt/family-usage/family.env`:

```bash
# Firebase Project Configuration (public web config - literal values, no shell quotes)
FIREBASE_PROJECT_ID=your-family-usage
FIREBASE_WEB_CONFIG_JSON={"apiKey":"AIzaSy...","authDomain":"your-project-id.firebaseapp.com","projectId":"your-project-id","appId":"1:...:web:...","messagingSenderId":"..."}

# Allowed Admin Emails (comma-separated, case-insensitive)
FAMILY_ADMIN_EMAILS=admin@example.com,user@example.com

# Public Origin for CSRF enforcement
FAMILY_PUBLIC_ORIGIN=https://usage.example.com

# Server timezone for billing cycle calculations (default: America/Toronto)
FAMILY_TIMEZONE=America/Toronto

# Optional: Set to 1 to publish port 8787 on Tailscale IP
PUBLISH_TAILSCALE=0
```

---

## Deployment Steps

### 1. Prerequisites on VPS (`/opt/family-usage`)

- Docker running on Ubuntu 22.04 / 24.04 (no docker-compose needed).
- Cloudflare Tunnel credentials JSON placed in `/opt/family-usage/cloudflared/<TUNNEL_ID>.json`.
- Environment configuration file placed in `/opt/family-usage/family.env`.

### 2. Run Deployment Script

```bash
cd /opt/family-usage
export TUNNEL_ID="12345678-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # or auto-detected from cloudflared/*.json

./deploy.sh
```

The script is fully idempotent. It:
1. Sources `/opt/family-usage/family.env` if present (for TUNNEL_ID / TAILSCALE_IP / PUBLISH_TAILSCALE) and passes it to Docker via `--env-file`.
2. Renders `cloudflared/config.yml` from `cloudflared/config.yml.template`.
3. Creates Docker network `family-net` if missing.
4. Builds the `family-usage-app` image (`python:3.14-slim`, non-root user).
5. Starts `family-app` connected to `family-net` with environment variables.
6. Starts `family-cloudflared` container connected to `family-net`.

### 3. Verify Deployment

```bash
# Public health check via Cloudflare Tunnel
curl -i https://usage.example.com/healthz
# Expected: HTTP/2 200 {"status":"ok"}

# Unauthenticated access to dashboard redirects to /login
curl -i https://usage.example.com/
# Expected: HTTP/2 302 Found, Location: /login

# Open in browser: https://usage.example.com/
# Sign in with authorized Google account -> dashboard renders with metrics
```

---

## Member Management Commands

Run the CLI inside the running `family-app` container:

### 1. Add a Member

```bash
docker exec family-app python -m family_server member add "Alice"
```
Output:
```text
Successfully added member 'Alice' (ID: 1).
Token: <GENERATED_TOKEN>

IMPORTANT: Store this token now. It will NEVER be shown again.
```
*Give this token to the member to configure in their Kanjo client.*

### 2. List Members

```bash
docker exec family-app python -m family_server member list
```
Output:
```text
ID   Name                 Created At                 Status
-----------------------------------------------------------------
1    Alice                2026-11-09T18:00:00        Active
2    Bob                  2026-11-09T18:15:00        Revoked (2026-11-09T19:00:00)
```

### 3. Revoke a Member

```bash
docker exec family-app python -m family_server member revoke "Bob"
```
Output:
```text
Successfully revoked token for member 'Bob'.
```

### 4. Manual Prune

Reports older than 90 days and intermediate reports on the same day are automatically pruned hourly upon report intake. You can also run it manually:

```bash
docker exec family-app python -m family_server prune
```

---

## Billing Cycle & Admin Settings

The family manager sets the billing cycle anchor day and optional tracking start date via the admin web interface.

### Settings (`/settings`)

- **Routes**:
  - `GET /settings`: Admin-only page (requires valid session in `FAMILY_ADMIN_EMAILS`). Displays settings form with properly escaped values.
  - `POST /settings`: Saves settings, validates inputs, and redirects to `/settings?saved=1`. Changes are logged without PII.
- **Configurable Settings (Stored in `settings` SQLite table)**:
  - `cycle_anchor_day`: Renewal day (1–31) of the Google AI Ultra family plan.
    - If a month does not have that day (e.g. day 31 in February or April), the cycle automatically starts on the last day of the month (e.g. Feb 28/29, Apr 30).
    - If unset, the dashboard prompts the admin with a banner and defaults to calendar month (anchor = 1).
  - `tracking_start`: Optional start date (`YYYY-MM-DD`). Usage before this date is ignored everywhere on the dashboard (cycle metrics, previous cycle, pool rankings, and chart).
  - `timezone`: IANA timezone name (e.g. `America/Toronto`). Defaults to `FAMILY_TIMEZONE` env variable, or `America/Toronto`. Validated using standard library `zoneinfo`.
- **Dashboard Display**:
  - Current cycle interval `[start, next_start)` shown as `本周期 MM/DD – MM/DD · 剩余 X 天`.
  - Per-member cards show: current cycle tokens / cost, previous cycle tokens / % change, and days remaining until cycle reset.
  - "本周期谁用掉了额度池" ranks member usage within the current cycle.

---

## Database Backup

SQLite supports online non-blocking backups via the `.backup` command:

### Manual Backup

```bash
sqlite3 /opt/family-usage/data/family.db ".backup '/opt/family-usage/data/family-backup-$(date +%Y%m%d%H%M%S).db'"
```

### Automated Daily Cron Job

Add the following entry to root crontab (`crontab -e`):

```cron
# Daily backup of Kanjo family usage database at 03:00 UTC
0 3 * * * mkdir -p /opt/family-usage/backups && /usr/bin/sqlite3 /opt/family-usage/data/family.db ".backup '/opt/family-usage/backups/family-\$(date +\%Y\%m\%d).db'" && find /opt/family-usage/backups -name "family-*.db" -mtime +30 -delete
```

This backs up the database daily and removes backups older than 30 days.
