"""
simulate_meters.py
------------------
Publishes realistic solar meter readings every 5 seconds for 3 villages.

Time is simulated at 60x speed by default (a full 24-hour day in ~24 minutes).
Set SPEED=1 in .env for real-time simulation.

Usage:
    python simulator/simulate_meters.py
    # or inside Docker Compose (service: simulator)

Environment variables (from .env):
    MQTT_HOST   default: localhost (mosquitto inside Compose)
    MQTT_PORT   default: 1883
    SPEED       default: 60  (simulated minutes per real second)
    INTERVAL    default: 5   (seconds between publishes)
"""

import json
import logging
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Load .env from project root (two levels up when running from simulator/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIM] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
SPEED    = float(os.getenv("SPEED", "60"))      # simulated-min per real-second
INTERVAL = float(os.getenv("INTERVAL", "5"))    # seconds between publish bursts

VILLAGES     = ["village_01", "village_02", "village_03"]
BATTERY_KWH  = 10.0   # kWh capacity per village battery

# ---------------------------------------------------------------------------
# Physics helpers
# ---------------------------------------------------------------------------

def solar_kw(h: float) -> float:
    """Return solar output in kW for simulated hour h (0–24)."""
    if h < 6 or h > 19:
        return 0.0
    if h <= 12:
        base = math.sin(math.pi / 2 * (h - 6) / 6)
    else:
        base = math.cos(math.pi / 2 * (h - 12) / 7)
    return max(0.0, 4.2 * base + random.uniform(-0.1, 0.1))


def load_kw(h: float) -> float:
    """Return load demand in kW for simulated hour h (0–24)."""
    base = 2.5
    if 6 <= h < 9:
        base += 0.5 * math.sin(math.pi * (h - 6) / 3)
    if 18 <= h < 22:
        base += 0.5 * math.sin(math.pi * (h - 18) / 4)
    return min(3.5, max(1.8, base + random.uniform(-0.15, 0.15)))


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------

_running = True


def _build_client() -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, rc, props):
        if rc == 0:
            log.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
        else:
            log.error("MQTT connect failed, rc=%s", rc)

    c.on_connect = on_connect

    for attempt in range(1, 6):
        try:
            c.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            return c
        except Exception as exc:
            wait = 2 ** attempt
            log.warning("MQTT connect attempt %d failed (%s). Retrying in %ds…", attempt, exc, wait)
            time.sleep(wait)

    log.error("Could not connect to MQTT broker after 5 attempts. Exiting.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

def _shutdown(sig, frame):
    global _running
    log.info("Shutdown signal received. Stopping simulator…")
    _running = False


signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

def main():
    client = _build_client()
    client.loop_start()

    battery     = {v: 60.0 for v in VILLAGES}   # start at 60 % charge
    sim_minutes = 6 * 60                          # start simulation at 06:00

    log.info(
        "Simulator started — %d villages, interval=%gs, speed=%gx",
        len(VILLAGES), INTERVAL, SPEED,
    )

    while _running:
        h = (sim_minutes / 60) % 24

        for v in VILLAGES:
            s = max(0.0, solar_kw(h) * random.uniform(0.9, 1.1))
            l = load_kw(h)

            # Update battery state
            dt_hours   = INTERVAL * SPEED / 3600
            delta_pct  = (s - l) * dt_hours / BATTERY_KWH * 100
            battery[v] = min(100.0, max(10.0, battery[v] + delta_pct))

            payload = {
                "time":        datetime.now(timezone.utc).isoformat(),
                "village_id":  v,
                "solar_kw":    round(s, 2),
                "load_kw":     round(l, 2),
                "battery_pct": round(battery[v], 1),
                "voltage":     round(random.uniform(228, 236), 1),
            }

            topic = f"surya/meters/{v}"
            client.publish(topic, json.dumps(payload))

        log.info(
            "sim %05.2fh → published %d readings  "
            "(%s bat=%.0f%%  %s bat=%.0f%%  %s bat=%.0f%%)",
            h, len(VILLAGES),
            VILLAGES[0], battery[VILLAGES[0]],
            VILLAGES[1], battery[VILLAGES[1]],
            VILLAGES[2], battery[VILLAGES[2]],
        )

        sim_minutes += INTERVAL * SPEED / 60
        time.sleep(INTERVAL)

    client.loop_stop()
    client.disconnect()
    log.info("Simulator stopped cleanly.")


if __name__ == "__main__":
    main()