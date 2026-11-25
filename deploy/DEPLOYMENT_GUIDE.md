# SuryaGrid AI — AWS Lightsail Deployment Guide

## Overview

| Item | Value |
|---|---|
| Target platform | AWS Lightsail (Ubuntu 22.04 LTS) |
| Recommended plan | $12/month — 2 vCPU, 2 GB RAM, 60 GB SSD |
| Services deployed | TimescaleDB · Mosquitto · FastAPI API · Simulator |
| Deployment method | Docker Compose via `lightsail-setup.sh` |

---

## Step 1 — Create a Lightsail Instance

1. Log into the [AWS Lightsail console](https://lightsail.aws.amazon.com/).
2. Click **Create instance**.
3. Choose:
   - **Platform**: Linux/Unix
   - **Blueprint**: Ubuntu 22.04 LTS
   - **Plan**: $12/month (2 vCPU, 2 GB RAM) — minimum recommended
   - **Instance name**: `surya-grid-backend`
4. Click **Create instance** and wait ~1 minute for it to start.

---

## Step 2 — Open Firewall Ports

In the Lightsail console → your instance → **Networking** tab:

| Port | Protocol | Purpose |
|---|---|---|
| 22 | TCP | SSH (already open) |
| 8000 | TCP | FastAPI REST API |
| 1883 | TCP | MQTT broker (only if external clients need it) |

> [!WARNING]
> Do **not** expose port **5433** (TimescaleDB) to the public internet.
> The database is accessed only internally by the API container.

---

## Step 3 — Upload Production .env

Before running the setup script, create a secure `.env` for production. Change the DB password!

```bash
# On your local machine — create production env file
cat > surya_prod.env << 'EOF'
DB_HOST=timescaledb
DB_PORT=5432
DB_NAME=surya_grid
DB_USER=surya
DB_PASSWORD=CHANGE_THIS_STRONG_PASSWORD

DATABASE_URL=postgresql+psycopg2://surya:CHANGE_THIS_STRONG_PASSWORD@timescaledb:5432/surya_grid

MQTT_HOST=mosquitto
MQTT_PORT=1883
SPEED=60
INTERVAL=5
EOF

# Copy to Lightsail instance (replace IP_ADDRESS)
scp -i ~/LightsailDefaultKey.pem surya_prod.env ubuntu@IP_ADDRESS:/tmp/surya_prod.env
```

> [!IMPORTANT]
> Never commit production passwords to Git. The setup script copies `/tmp/surya_prod.env`
> from the instance's temp directory and deletes it from there.

---

## Step 4 — SSH into the Instance

```bash
# Download your Lightsail key from the console → Account → SSH keys
chmod 400 ~/LightsailDefaultKey.pem
ssh -i ~/LightsailDefaultKey.pem ubuntu@YOUR_INSTANCE_IP
```

---

## Step 5 — Run the Setup Script

```bash
# On the Lightsail instance:

# Option A: Download and run directly from GitHub
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/SuryaGrid-AI/main/deploy/lightsail-setup.sh \
    | sudo bash

# Option B: If you've already cloned the repo
sudo bash /opt/surya_grid/deploy/lightsail-setup.sh
```

The script will:
1. Update Ubuntu packages
2. Install Docker Engine (official Docker repo)
3. Clone your repository to `/opt/surya_grid`
4. Apply the production `.env`
5. Run `docker compose up -d --build`
6. Print your public API URL

---

## Step 6 — Verify Deployment

```bash
# Check all 4 services are healthy
docker compose -f /opt/surya_grid/docker-compose.yml ps

# Expected output:
# NAME                   STATUS
# suryagrid-db           Up (healthy)
# suryagrid-mqtt         Up (healthy)
# suryagrid-api          Up (healthy)
# suryagrid-simulator    Up

# Test the API (replace IP with your Lightsail IP)
curl http://YOUR_INSTANCE_IP:8000/health
curl http://YOUR_INSTANCE_IP:8000/solar/current
curl http://YOUR_INSTANCE_IP:8000/forecast/24hr
curl http://YOUR_INSTANCE_IP:8000/alerts/latest
```

---

## Step 7 — (Optional) Point a Domain Name

1. In Lightsail → **Networking** → **Static IPs** → attach a static IP to your instance.
2. In your DNS provider, add an **A record**: `api.surya-grid.com → YOUR_STATIC_IP`.
3. Install Nginx as a reverse proxy (optional, for HTTPS):

```bash
sudo apt install nginx certbot python3-certbot-nginx -y
# Configure /etc/nginx/sites-available/surya as a proxy to localhost:8000
# Then: sudo certbot --nginx -d api.surya-grid.com
```

---

## Maintenance

```bash
# View live logs from all services
docker compose -f /opt/surya_grid/docker-compose.yml logs -f

# View logs for a specific service
docker compose -f /opt/surya_grid/docker-compose.yml logs -f api

# Redeploy after a code change (pull + rebuild)
cd /opt/surya_grid
git pull
docker compose up -d --build

# Stop all services
docker compose down

# Backup TimescaleDB
docker exec suryagrid-db pg_dump -U surya surya_grid > backup_$(date +%Y%m%d).sql
```

---

## Architecture on Lightsail

```
Internet
    │
    │ :8000 (TCP)
    ▼
┌─────────────────────────────────────────────┐
│          Lightsail Instance (Ubuntu 22.04)   │
│                                              │
│  ┌─────────────┐    surya_net bridge         │
│  │  suryagrid  │ ◄──────────────────────────┤
│  │    -api     │                            │
│  │  (FastAPI + │                            │
│  │  MQTT sub)  │                            │
│  └──────┬──────┘                            │
│         │ SQL      │ MQTT                   │
│  ┌──────▼──────┐  ┌▼──────────────────┐     │
│  │  suryagrid  │  │   suryagrid-mqtt  │     │
│  │    -db      │  │   (Mosquitto)     │     │
│  │(TimescaleDB)│  └────────▲──────────┘     │
│  └─────────────┘           │ MQTT publish   │
│                     ┌──────┴──────────┐     │
│                     │suryagrid-simulat│     │
│                     │or (meter sim)   │     │
│                     └─────────────────┘     │
└─────────────────────────────────────────────┘
```
