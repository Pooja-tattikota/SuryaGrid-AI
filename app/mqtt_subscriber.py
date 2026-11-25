"""
mqtt_subscriber.py
------------------
Subscribes to surya/meters/# and writes every reading into TimescaleDB.
Also creates a low_battery alert automatically when battery_pct < 20 %.

Can be run standalone:
    python app/mqtt_subscriber.py

Or imported and controlled programmatically:
    from mqtt_subscriber import start, stop
    start()   # launches background thread
    stop()    # clean disconnect
"""

import json
import logging
import os
import threading
import time

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from sqlalchemy import text

from database import engine

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MQTT] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC = "surya/meters/#"

LOW_BATTERY_THRESHOLD = 20.0   # percent

INSERT_READING = text("""
    INSERT INTO meter_readings (time, village_id, solar_kw, load_kw, battery_pct, voltage)
    VALUES (:time, :village_id, :solar_kw, :load_kw, :battery_pct, :voltage)
    ON CONFLICT DO NOTHING
""")

INSERT_ALERT = text("""
    INSERT INTO alerts (village_id, alert_type, message)
    VALUES (:village_id, :alert_type, :message)
""")

# --- MQTT callbacks ----------------------------------------------------------

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe(TOPIC)
        log.info("Subscribed to topic: %s", TOPIC)
    else:
        log.error("MQTT connection failed, reason code: %s", reason_code)


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except json.JSONDecodeError as exc:
        log.warning("Bad JSON on topic %s: %s", msg.topic, exc)
        return

    # --- Validate required fields -------------------------------------------
    required = {"time", "village_id", "solar_kw", "load_kw", "battery_pct", "voltage"}
    missing = required - data.keys()
    if missing:
        log.warning("Message missing fields %s, skipping: %s", missing, data)
        return

    village_id  = data["village_id"]
    battery_pct = float(data["battery_pct"])

    # --- Write reading to DB -------------------------------------------------
    try:
        with engine.begin() as conn:
            conn.execute(INSERT_READING, data)
        log.info(
            "Stored %-12s  solar=%.2f kW  load=%.2f kW  battery=%.1f %%",
            village_id, data["solar_kw"], data["load_kw"], battery_pct,
        )
    except Exception as exc:
        log.error("Failed to store reading for %s: %s", village_id, exc)
        return   # don't proceed to alert check if DB is down

    # --- Auto-alert: low battery --------------------------------------------
    if battery_pct < LOW_BATTERY_THRESHOLD:
        try:
            with engine.begin() as conn:
                conn.execute(INSERT_ALERT, {
                    "village_id": village_id,
                    "alert_type": "low_battery",
                    "message": (
                        f"Battery at {battery_pct:.1f}% — below "
                        f"{LOW_BATTERY_THRESHOLD}% threshold."
                    ),
                })
            log.warning(
                "⚠  LOW BATTERY alert created for %s (%.1f %%)",
                village_id, battery_pct,
            )
        except Exception as exc:
            log.error("Failed to create low_battery alert for %s: %s", village_id, exc)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    if reason_code != 0:
        log.warning("Unexpected MQTT disconnect (code %s). Will reconnect…", reason_code)


# --- Module-level client (created once) -------------------------------------

_client: mqtt.Client | None = None
_thread: threading.Thread | None = None


def _build_client() -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.on_connect    = on_connect
    c.on_message    = on_message
    c.on_disconnect = on_disconnect
    # Retry connection with back-off
    for attempt in range(1, 6):
        try:
            c.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            return c
        except Exception as exc:
            wait = 2 ** attempt
            log.warning("MQTT connect attempt %d failed (%s). Retrying in %ds…", attempt, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Could not connect to MQTT broker at {MQTT_HOST}:{MQTT_PORT} after 5 attempts.")


def start() -> None:
    """Start the MQTT subscriber in a background daemon thread."""
    global _client, _thread
    if _thread and _thread.is_alive():
        log.info("MQTT subscriber already running.")
        return
    _client = _build_client()
    _thread = threading.Thread(target=_client.loop_forever, daemon=True, name="mqtt-subscriber")
    _thread.start()
    log.info("MQTT subscriber thread started.")


def stop() -> None:
    """Gracefully disconnect and stop the subscriber thread."""
    global _client
    if _client:
        _client.disconnect()
        log.info("MQTT subscriber disconnected.")
        _client = None


# --- Standalone entry point -------------------------------------------------

if __name__ == "__main__":
    import signal

    def _shutdown(sig, frame):
        log.info("Shutting down MQTT subscriber…")
        stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    start()
    log.info("Running standalone. Press Ctrl-C to stop.")
    # Keep main thread alive
    while True:
        time.sleep(1)