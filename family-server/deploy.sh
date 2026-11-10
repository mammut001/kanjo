#!/usr/bin/env bash
set -euo pipefail

# Kanjo family usage deployment script
# Designed to run idempotently on the VPS at /opt/family-usage

DEPLOY_DIR="/opt/family-usage"
if [ -d "${DEPLOY_DIR}" ]; then
  cd "${DEPLOY_DIR}"
fi

BASE_DIR="$(pwd)"
DATA_DIR="${DEPLOY_DIR}/data"
if [ ! -d "${DEPLOY_DIR}" ]; then
  DATA_DIR="${BASE_DIR}/data"
fi

CLOUDFLARED_DIR="${DEPLOY_DIR}/cloudflared"
if [ ! -d "${DEPLOY_DIR}" ]; then
  CLOUDFLARED_DIR="${BASE_DIR}/cloudflared"
fi

TAILSCALE_IP="${TAILSCALE_IP:-100.115.238.6}"

# Determine TUNNEL_ID from env or credentials file
if [ -z "${TUNNEL_ID:-}" ]; then
  CRED_FILE=$(ls -1 "${CLOUDFLARED_DIR}"/*.json 2>/dev/null | head -n 1 || true)
  if [ -n "${CRED_FILE}" ]; then
    TUNNEL_ID=$(basename "${CRED_FILE}" .json)
    echo "Detected TUNNEL_ID from credentials file: ${TUNNEL_ID}"
  else
    echo "Error: TUNNEL_ID environment variable is required (or credentials JSON in cloudflared/)" >&2
    exit 1
  fi
fi

echo "=== Deploying Kanjo Family Usage Server ==="
echo "Working directory:  ${BASE_DIR}"
echo "Tailscale IP:       ${TAILSCALE_IP}"
echo "Tunnel ID:          ${TUNNEL_ID}"

# 1. Render cloudflared/config.yml from template
if [ -f "cloudflared/config.yml.template" ]; then
  sed "s/TUNNEL_ID/${TUNNEL_ID}/g" cloudflared/config.yml.template > cloudflared/config.yml
  echo "✓ Rendered cloudflared/config.yml"
else
  echo "Error: cloudflared/config.yml.template not found" >&2
  exit 1
fi

# 2. Ensure docker network exists
if ! docker network inspect family-net >/dev/null 2>&1; then
  docker network create family-net
  echo "✓ Created docker network family-net"
else
  echo "✓ Docker network family-net exists"
fi

# 3. Ensure data directory exists
mkdir -p "${DATA_DIR}"

# 4. Build application container image
echo "Building application image family-usage-app..."
docker build -t family-usage-app .
echo "✓ Built image family-usage-app"

# 5. Run/replace family-app container
# Port 8788 is NOT published to host (accessible only by cloudflared over family-net)
# Port 8787 is published ONLY to the Tailscale IP
echo "Starting container family-app..."
docker rm -f family-app 2>/dev/null || true
docker run -d \
  --name family-app \
  --network family-net \
  --restart unless-stopped \
  -v "${DATA_DIR}:/data" \
  -p "${TAILSCALE_IP}:8787:8787" \
  family-usage-app
echo "✓ Container family-app is running"

# 6. Run/replace family-cloudflared container
echo "Starting container family-cloudflared..."
docker rm -f family-cloudflared 2>/dev/null || true
docker run -d \
  --name family-cloudflared \
  --network family-net \
  --restart unless-stopped \
  -v "${CLOUDFLARED_DIR}:/home/nonroot/.cloudflared:ro" \
  -v "${CLOUDFLARED_DIR}/config.yml:/etc/cloudflared/config.yml:ro" \
  cloudflare/cloudflared:2026.10.7 \
  tunnel --no-autoupdate --config /etc/cloudflared/config.yml run
echo "✓ Container family-cloudflared is running"

echo "=== Deployment complete successfully ==="
