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

# Load environment configuration from family.env if present
ENV_FILE="${DEPLOY_DIR}/family.env"
if [ ! -f "${ENV_FILE}" ] && [ -f "${BASE_DIR}/family.env" ]; then
  ENV_FILE="${BASE_DIR}/family.env"
fi

if [ -f "${ENV_FILE}" ]; then
  echo "✓ Sourcing configuration from ${ENV_FILE}"
  set -a
  # shellcheck source=/dev/null
  . "${ENV_FILE}"
  set +a
else
  echo "Note: ${ENV_FILE} not found; proceeding with environment defaults"
fi

TAILSCALE_IP="${TAILSCALE_IP:-100.115.238.6}"
PUBLISH_TAILSCALE="${PUBLISH_TAILSCALE:-0}"

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
echo "Working directory:    ${BASE_DIR}"
echo "Tailscale IP:         ${TAILSCALE_IP}"
echo "Publish Tailscale:    ${PUBLISH_TAILSCALE}"
echo "Tunnel ID:            ${TUNNEL_ID}"

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
# Neither port is published on a public interface.
# Port 8788 is NOT published to host (accessible only by cloudflared over family-net)
# Port 8787 is published to Tailscale IP ONLY if PUBLISH_TAILSCALE=1
PORT_PUBLISH_ARGS=()
if [ "${PUBLISH_TAILSCALE}" = "1" ]; then
  PORT_PUBLISH_ARGS+=("-p" "${TAILSCALE_IP}:8787:8787")
  echo "Publishing dashboard port on Tailscale IP ${TAILSCALE_IP}:8787 (opt-in)"
else
  echo "Dashboard port 8787 is not published to host (accessible via cloudflared on family-net)"
fi

ENV_ARGS=()
if [ -f "${ENV_FILE}" ]; then
  ENV_ARGS+=("--env-file" "${ENV_FILE}")
fi
if [ -n "${FIREBASE_PROJECT_ID:-}" ]; then
  ENV_ARGS+=("-e" "FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}")
fi
if [ -n "${FIREBASE_WEB_CONFIG_JSON:-}" ]; then
  ENV_ARGS+=("-e" "FIREBASE_WEB_CONFIG_JSON=${FIREBASE_WEB_CONFIG_JSON}")
fi
if [ -n "${FAMILY_ADMIN_EMAILS:-}" ]; then
  ENV_ARGS+=("-e" "FAMILY_ADMIN_EMAILS=${FAMILY_ADMIN_EMAILS}")
fi
if [ -n "${FAMILY_PUBLIC_ORIGIN:-}" ]; then
  ENV_ARGS+=("-e" "FAMILY_PUBLIC_ORIGIN=${FAMILY_PUBLIC_ORIGIN}")
fi

echo "Starting container family-app..."
docker rm -f family-app 2>/dev/null || true
docker run -d \
  --name family-app \
  --network family-net \
  --restart unless-stopped \
  -v "${DATA_DIR}:/data" \
  "${PORT_PUBLISH_ARGS[@]}" \
  "${ENV_ARGS[@]}" \
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
