import argparse
import json
import time
from collections import OrderedDict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
from tensorflow.keras.models import load_model

LAT, LON = 17.6, 78.0
LOOKBACK, HORIZON, SCALE = 168, 24, 1000.0
PANEL_KW = 5.0
SAFE_LOW, SAFE_HIGH = 210, 250
FEATURES = ["load_ratio", "voltage", "solar_ratio", "irr"]

parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=300, help="seconds between cycles (300 = 5 min)")
parser.add_argument("--cycles", type=int, default=0, help="stop after N cycles (0 = run forever)")
parser.add_argument("--inject", action="store_true", help="inject demo faults at cycles 3, 5 and 7")
parser.add_argument("--api", default="", help="Pooja's API base URL, e.g. http://localhost:8000")
args = parser.parse_args()

Path("data").mkdir(exist_ok=True)

# ---------- load models ----------
iso = joblib.load("models/isolation_forest.joblib")
arima = joblib.load("models/arima_voltage.joblib")
lstm = load_model("models/lstm_forecast.keras")
profile = joblib.load("models/load_profile.joblib")
meter_hist = pd.read_csv("data/meter_data_with_anomalies.csv")
hist_volt = meter_hist[meter_hist["anomaly"] == 1]["voltage"].values[-200:]
print("Models loaded: Isolation Forest, ARIMA, LSTM\n")


# ---------- helpers ----------
def clear_sky(times):
    t = pd.DatetimeIndex(times)
    doy = t.day_of_year.values
    solar_time = (t.hour.values - 0.5) - 5.5 + LON / 15.0
    omega = np.radians(15.0 * (solar_time - 12.0))
    dec = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365.0)
    lat = np.radians(LAT)
    cosz = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(omega)
    safe = np.maximum(cosz, 1e-3)
    return np.where(cosz > 0.0, 1098.0 * safe * np.exp(-0.059 / safe), 0.0)


def add_features(df):
    h = df["time"].dt.hour
    df["hsin"] = np.sin(2 * np.pi * h / 24)
    df["hcos"] = np.cos(2 * np.pi * h / 24)
    df["sol"] = df["solar"] / SCALE
    df["cloud"] = df["cloud_cover"] / 100.0
    df["cs"] = clear_sky(df["time"]) / SCALE
    return df


def fetch_live_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&current=shortwave_radiation,temperature_2m"
        "&hourly=shortwave_radiation,cloud_cover&past_days=7&forecast_days=3"
        "&timezone=Asia%2FKolkata"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    d = r.json()
    h = d["hourly"]
    df = pd.DataFrame({
        "time": pd.to_datetime(h["time"]),
        "solar": h["shortwave_radiation"],
        "cloud_cover": h["cloud_cover"],
    }).dropna().reset_index(drop=True)
    return d["current"], add_features(df)


def lstm_forecast(live, now):
    past = live[live["time"] <= now].tail(LOOKBACK)
    fut = live[live["time"] > now].head(HORIZON)
    if len(past) < LOOKBACK or len(fut) < HORIZON:
        return None
    xp = past[["sol", "cloud", "cs", "hsin", "hcos"]].values[np.newaxis]
    xf = fut[["cloud", "cs", "hsin", "hcos"]].values[np.newaxis]
    xc = fut["cs"].values[np.newaxis]
    p = np.clip(lstm.predict([xp, xf, xc], verbose=0)[0] * SCALE, 0, None)
    return [{"time": str(t), "solar_wm2": round(float(v), 1)} for t, v in zip(fut["time"], p)]


def read_meter(now, irradiance, cycle):
    """SIMULATED meter reading driven by REAL live sunlight.
    Replace this function with a call to Pooja's meter-readings endpoint."""
    base = float(np.clip(2.5 + 1.8 * np.sin((now.hour - 7) * np.pi / 12), 1.2, 5.5))
    load = max(0.3, base + np.random.normal(0, 0.25))
    voltage = 230 + np.random.normal(0, 3.5)
    solar = irradiance / 1000 * PANEL_KW * 0.8
    if args.inject:
        if cycle == 3:
            voltage = 275.0
        elif cycle == 5:
            load *= 0.2
        elif cycle == 7 and irradiance > 200:
            solar = 0.0
    return {"load_kw": load, "voltage": voltage, "solar_kw": solar, "hour": now.hour}


alerts = []


def raise_alert(kind, severity, message, reading):
    alert = {"time": str(pd.Timestamp.now()), "type": kind, "severity": severity, "message": message}
    alerts.append(alert)
    print(f"  ALERT [{severity}] {kind}: {message}")
    Path("data/alerts.json").write_text(json.dumps(alerts, indent=2, default=float))
    if args.api:
        try:
            requests.post(f"{args.api}/alerts/create", json={**alert, "reading": reading}, timeout=10)
        except Exception as e:
            print("  (could not reach API:", e, ")")


# ---------- main loop ----------
live_hours = OrderedDict()   # hour -> live voltage readings (for ARIMA)
lstm_cache = {"hour": None, "data": None}
cycle = 0

while True:
    cycle += 1
    now = pd.Timestamp.now()
    print(f"--- Cycle {cycle} @ {now:%Y-%m-%d %H:%M:%S} ---")

    # SENSE: real live weather
    try:
        current, live = fetch_live_weather()
        irradiance = float(current["shortwave_radiation"])
        temp = float(current["temperature_2m"])
    except Exception as e:
        print("Weather fetch failed:", e)
        time.sleep(args.interval)
        continue

    reading = read_meter(now, irradiance, cycle)
    live_hours.setdefault(now.floor("h"), []).append(reading["voltage"])
    print(f"  Sun {irradiance:.0f} W/m2 | load {reading['load_kw']:.2f} kW | "
          f"voltage {reading['voltage']:.1f} V | solar {reading['solar_kw']:.2f} kW")

    # DETECT: Isolation Forest
    irr_kw = irradiance / 1000
    row = pd.DataFrame([[
    reading["load_kw"] / profile[now.hour],
    reading["voltage"],
    reading["solar_kw"] / (irr_kw * PANEL_KW * 0.8 + 1e-3),
    irr_kw,
]], columns=FEATURES)
    is_anomaly = (int(iso.predict(row)[0]) == -1
              or reading["voltage"] > SAFE_HIGH or reading["voltage"] < SAFE_LOW)
    score = float(iso.decision_function(row)[0])
    if is_anomaly:
        if reading["voltage"] > SAFE_HIGH or reading["voltage"] < SAFE_LOW:
            kind = "voltage_fault"
        elif reading["solar_kw"] < 0.2 and irradiance > 200:
            kind = "solar_fault"
        elif reading["load_kw"] < 0.5 * profile[now.hour]:
            kind = "possible_theft"
        else:
            kind = "unusual_pattern"
        raise_alert(kind, "high", f"Anomaly score {score:.3f}", reading)

    # FORECAST: LSTM (refreshed once per hour)
    if lstm_cache["hour"] != now.floor("h"):
        lstm_cache["data"] = lstm_forecast(live, now.floor("h"))
        lstm_cache["hour"] = now.floor("h")
        print("  LSTM 24h solar forecast refreshed")

    # MAINTAIN: ARIMA on hourly voltage history + live hours
    volt_series = np.concatenate([hist_volt, [np.mean(v) for v in live_hours.values()]])
    arima_info = {"status": "unknown"}
    try:
        fc = np.asarray(arima.apply(volt_series, refit=False).forecast(steps=72))
        out = (fc < SAFE_LOW) | (fc > SAFE_HIGH)
        arima_info = {
            "status": "maintenance_needed" if out.any() else "ok",
            "forecast_min_v": round(float(fc.min()), 1),
            "forecast_max_v": round(float(fc.max()), 1),
        }
        if out.any():
            raise_alert("predictive_maintenance", "medium",
                        f"Voltage forecast leaves {SAFE_LOW}-{SAFE_HIGH} V within 72h", reading)
    except Exception as e:
        print("  ARIMA update skipped:", e)

    # INFORM: status file for the dashboard
    status = {
        "updated": str(now),
        "data_mode": "live weather (Open-Meteo) + simulated meter",
        "weather": {"solar_wm2": irradiance, "temp_c": temp},
        "meter": {k: round(float(v), 2) for k, v in reading.items()},
        "anomaly": {"detected": is_anomaly, "score": round(score, 3)},
        "arima": arima_info,
        "solar_forecast_24h": lstm_cache["data"],
        "alerts_total": len(alerts),
    }
    Path("data/edge_status.json").write_text(json.dumps(status, indent=2, default=float))
    print("  Status saved -> data/edge_status.json")

    if args.cycles and cycle >= args.cycles:
        break
    time.sleep(args.interval)

print("\nService finished.")