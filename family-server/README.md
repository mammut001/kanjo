# Kanjo Family Usage Server

Self-hosted report receiver and private Tailnet dashboard for Google AI Ultra / AI family usage tracking.

## Architecture

- **Public report endpoint (`usage.paytonpei.top`)**:
  - Accessible via Cloudflare Tunnel (`family-cloudflared`).
  - Forwards `POST /api/report` and `GET /healthz` to `http://family-app:8788`.
  - All other paths return 404 from Cloudflare.
  - Port 8788 is NOT published to the host network.
- **Private dashboard (`100.115.238.6:8787`)**:
  - Published strictly on the VPS Tailscale IP (`100.115.238.6:8787`).
  - Not exposed to the public Internet.
  - Server-rendered HTML with inline CSS and hand-written SVG charts (works offline on the tailnet).
- **Storage**:
  - SQLite database stored at `/opt/family-usage/data/family.db` (inside container: `/data/family.db`).
  - Members, SHA-256 hashed bearer tokens, and daily historical reports (90-day retention).

---

## Deployment Steps

### 1. Prerequisites on VPS (`/opt/family-usage`)

- Docker running on Ubuntu 26.04 (no docker-compose needed).
- Cloudflare Tunnel credentials JSON placed in `/opt/family-usage/cloudflared/<TUNNEL_ID>.json`.
- Tailscale running on the host with IP `100.115.238.6`.

### 2. Run Deployment Script

```bash
cd /opt/family-usage
export TUNNEL_ID="0bfee670-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # or auto-detected from cloudflared/*.json
export TAILSCALE_IP="100.115.238.6"                     # optional, default is 100.115.238.6

./deploy.sh
```

The script is fully idempotent. It:
1. Renders `cloudflared/config.yml` from `cloudflared/config.yml.template`.
2. Creates Docker network `family-net` if missing.
3. Builds the `family-usage-app` image (`python:3.14-slim`, runs as non-root user).
4. Restarts `family-app` mounting `/opt/family-usage/data:/data` and publishing only `100.115.238.6:8787:8787`.
5. Restarts `family-cloudflared` container connected to `family-net`.

### 3. Verify Deployment

```bash
# Public health check via Cloudflare Tunnel
curl -i https://usage.paytonpei.top/healthz
# Expected: HTTP/2 200 {"status":"ok"}

# Verify public ingress blocks unauthorized paths
curl -i https://usage.paytonpei.top/
# Expected: HTTP 404

# Private dashboard via Tailscale
curl -i http://100.115.238.6:8787/
# Expected: HTTP 200 with HTML dashboard
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
