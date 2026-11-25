#!/usr/bin/env bash
# ============================================================
# SuryaGrid AI — AWS Lightsail Setup Script
# ============================================================
# Run this script on a fresh Ubuntu 22.04 Lightsail instance:
#   chmod +x lightsail-setup.sh && sudo ./lightsail-setup.sh
# ============================================================

set -euo pipefail

REPO_URL="https://github.com/YOUR_GITHUB_USERNAME/SuryaGrid-AI.git"  # <-- update this
APP_DIR="/opt/surya_grid"

echo "==> [1/6] Updating system packages"
apt-get update -y && apt-get upgrade -y

echo "==> [2/6] Installing Docker Engine"
apt-get install -y ca-certificates curl gnupg lsb-release

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
   https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker

echo "==> [3/6] Installing git"
apt-get install -y git

echo "==> [4/6] Cloning repository"
if [ -d "$APP_DIR" ]; then
    echo "Directory $APP_DIR already exists — pulling latest changes"
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

echo "==> [5/6] Copying production .env"
# If a production .env was uploaded separately, copy it now.
# Otherwise the defaults from the repo will be used.
if [ -f /tmp/surya_prod.env ]; then
    cp /tmp/surya_prod.env "$APP_DIR/.env"
    echo "    Production .env applied from /tmp/surya_prod.env"
else
    echo "    WARNING: No production .env found at /tmp/surya_prod.env"
    echo "    Using default .env from repository. Update DB passwords before go-live!"
fi

echo "==> [6/6] Starting Docker Compose stack"
cd "$APP_DIR"
docker compose pull
docker compose up -d --build

echo ""
echo "======================================================"
echo "  SuryaGrid AI is running!"
echo "  API endpoint:  http://$(curl -s ifconfig.me):8000"
echo "  Health check:  http://$(curl -s ifconfig.me):8000/health"
echo "======================================================"
echo ""
echo "Useful commands:"
echo "  docker compose ps              # service status"
echo "  docker compose logs -f api     # API logs"
echo "  docker compose logs -f simulator # simulator logs"
echo "  docker compose down            # stop all services"
