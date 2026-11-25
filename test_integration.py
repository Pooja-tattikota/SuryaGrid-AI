#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_integration.py
-------------------
End-to-end integration test for the SuryaGrid AI backend.

Verifies the complete data flow:
  Simulator -> MQTT -> mqtt_subscriber -> TimescaleDB -> FastAPI

Prerequisites (all must be running):
  1. TimescaleDB container  (port 5433)
  2. Mosquitto container    (port 1883)
  3. FastAPI server         (port 8000)   -- started automatically by this script
     OR already running:  uvicorn main:app --reload  (from app/)

Run from the project root:
    python test_integration.py

Returns exit code 0 on all PASS, 1 on any FAIL.
"""

import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import requests

API_BASE     = "http://localhost:8000"
MQTT_HOST    = "localhost"
MQTT_PORT    = 1883
TEST_VILLAGE = "test_village_99"

PASS_LABEL = "[PASS]"
FAIL_LABEL = "[FAIL]"
SKIP_LABEL = "[SKIP]"

failures = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global failures
    label  = PASS_LABEL if condition else FAIL_LABEL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {label} {name}{suffix}")
    if not condition:
        failures += 1
    return condition


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# 1. API Health
# ---------------------------------------------------------------------------
section("1 - API Health Check")
try:
    r = requests.get(f"{API_BASE}/health", timeout=5)
    check("HTTP 200 from /health",          r.status_code == 200)
    check("api == ok",                      r.json().get("api") == "ok",        str(r.json()))
    check("database == ok",                 r.json().get("database") == "ok",   str(r.json()))
    check("mqtt_subscriber == running",
          "running" in r.json().get("mqtt_subscriber", ""),                     str(r.json()))
except Exception as exc:
    check("API reachable at http://localhost:8000", False, str(exc))
    print("\n  [!] FastAPI is not running. Start it with:")
    print("       cd app && uvicorn main:app --reload")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. MQTT -> DB Integration
# ---------------------------------------------------------------------------
section("2 - MQTT -> Database Integration")

published = False
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
    client.loop_start()

    payload = {
        "time":        datetime.now(timezone.utc).isoformat(),
        "village_id":  TEST_VILLAGE,
        "solar_kw":    3.14,
        "load_kw":     2.00,
        "battery_pct": 75.0,
        "voltage":     231.5,
    }
    result = client.publish(
        f"surya/meters/{TEST_VILLAGE}", json.dumps(payload)
    )
    published = result.rc == 0
    check("MQTT publish succeeded", published, f"rc={result.rc}")
    client.loop_stop()
    client.disconnect()
except Exception as exc:
    check("MQTT broker reachable at localhost:1883", False, str(exc))

if published:
    print("  Waiting 3 s for subscriber to INSERT into DB...")
    time.sleep(3)

    try:
        r = requests.get(f"{API_BASE}/solar/current", timeout=5)
        check("GET /solar/current HTTP 200", r.status_code == 200)
        villages = {row["village_id"]: row for row in r.json()}
        check(
            f"Test reading for '{TEST_VILLAGE}' found in DB",
            TEST_VILLAGE in villages,
            f"villages returned: {list(villages.keys())}",
        )
        if TEST_VILLAGE in villages:
            row = villages[TEST_VILLAGE]
            check("solar_kw matches",    abs(row["solar_kw"]    - 3.14) < 0.01, str(row))
            check("battery_pct matches", abs(row["battery_pct"] - 75.0) < 0.1,  str(row))
    except Exception as exc:
        check("GET /solar/current reachable", False, str(exc))

# ---------------------------------------------------------------------------
# 3. Forecast API
# ---------------------------------------------------------------------------
section("3 - Forecast API  GET /forecast/24hr")
try:
    r = requests.get(f"{API_BASE}/forecast/24hr", timeout=10)
    check("HTTP 200", r.status_code == 200)
    data = r.json()
    check("Returns a list", isinstance(data, list))
    if data:
        row = data[0]
        check("Has village_id",          "village_id"         in row, str(row))
        check("Has hour_of_day",         "hour_of_day"        in row, str(row))
        check("Has predicted_solar_kw",  "predicted_solar_kw" in row, str(row))
        check("Has predicted_load_kw",   "predicted_load_kw"  in row, str(row))
    else:
        print(f"  {SKIP_LABEL} Forecast empty -- simulator needs a few minutes of data first.")
except Exception as exc:
    check("GET /forecast/24hr reachable", False, str(exc))

# ---------------------------------------------------------------------------
# 4. Alerts -- POST /alerts/create
# ---------------------------------------------------------------------------
section("4 - Alerts API  POST /alerts/create")
created_id = None
try:
    r = requests.post(
        f"{API_BASE}/alerts/create",
        json={
            "village_id":  TEST_VILLAGE,
            "alert_type":  "fault",
            "message":     "Integration test fault alert",
        },
        timeout=5,
    )
    check("HTTP 201 on creation", r.status_code == 201, f"got {r.status_code}: {r.text}")
    if r.status_code == 201:
        body = r.json()
        check("Returns id",         "id"         in body, str(body))
        check("Returns time",       "time"        in body, str(body))
        check("Returns village_id", "village_id"  in body, str(body))
        check("status == created",  body.get("status") == "created", str(body))
        created_id = body.get("id")

    # Invalid alert_type must be rejected
    r_bad = requests.post(
        f"{API_BASE}/alerts/create",
        json={"village_id": TEST_VILLAGE, "alert_type": "invalid_type"},
        timeout=5,
    )
    check("HTTP 422 on bad alert_type", r_bad.status_code == 422,
          f"got {r_bad.status_code}")
except Exception as exc:
    check("POST /alerts/create reachable", False, str(exc))

# ---------------------------------------------------------------------------
# 5. Alerts -- GET /alerts/latest
# ---------------------------------------------------------------------------
section("5 - Alerts API  GET /alerts/latest")
try:
    r = requests.get(
        f"{API_BASE}/alerts/latest",
        params={"village_id": TEST_VILLAGE, "limit": 5},
        timeout=5,
    )
    check("HTTP 200", r.status_code == 200)
    data = r.json()
    check("Returns a list", isinstance(data, list))
    if created_id:
        ids = [row.get("id") for row in data]
        check(f"Alert id={created_id} appears in results", created_id in ids, str(ids))
except Exception as exc:
    check("GET /alerts/latest reachable", False, str(exc))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section("Summary")
if failures == 0:
    print("\n  ALL TESTS PASSED\n")
else:
    print(f"\n  {failures} TEST(S) FAILED\n")

sys.exit(0 if failures == 0 else 1)
