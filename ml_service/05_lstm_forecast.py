import numpy as np
import pandas as pd
import requests
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import date, timedelta
from sklearn.metrics import mean_absolute_error, mean_squared_error
from tensorflow.keras.models import Model
from tensorflow.keras.layers import LSTM, Dense, Input, Concatenate, Flatten, Multiply, Rescaling
from tensorflow.keras.callbacks import EarlyStopping

LAT, LON = 17.6, 78.0
LOOKBACK, HORIZON, SCALE = 168, 24, 1000.0

for d in ("data", "models", "plots"):
    Path(d).mkdir(exist_ok=True)

print("=== LSTM v3 - Clear-sky x cloud factor (7 days -> next 24h) ===\n")


def clear_sky(times):
    """Haurwitz clear-sky GHI (W/m2) for Sangareddy. Open-Meteo values are
    the mean of the preceding hour, so use the hour midpoint."""
    t = pd.DatetimeIndex(times)
    doy = t.dayofyear.values
    hour_mid = t.hour.values - 0.5
    solar_time = hour_mid - 5.5 + LON / 15.0
    omega = np.radians(15.0 * (solar_time - 12.0))
    dec = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365.0)
    lat = np.radians(LAT)
    cosz = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(omega)
    cosz_safe = np.maximum(cosz, 1e-3)
    cs = 1098.0 * cosz_safe * np.exp(-0.059 / cosz_safe)
    return np.where(cosz > 0.0, cs, 0.0)


def add_features(df):
    h = df["time"].dt.hour
    df["hsin"] = np.sin(2 * np.pi * h / 24)
    df["hcos"] = np.cos(2 * np.pi * h / 24)
    df["sol"] = df["solar"] / SCALE
    df["cloud"] = df["cloud_cover"] / 100.0
    df["cs"] = clear_sky(df["time"]) / SCALE
    return df


# 1. Real hourly history (reuses the cached file from v2)
hist_path = Path("data/hourly_history_v2.csv")
if hist_path.exists():
    hist = pd.read_csv(hist_path, parse_dates=["time"])
else:
    end = date.today() - timedelta(days=7)
    start = date(end.year - 4, end.month, end.day)
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAT}&longitude={LON}&start_date={start}&end_date={end}"
        "&hourly=shortwave_radiation,cloud_cover&timezone=Asia%2FKolkata"
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    h = r.json()["hourly"]
    hist = pd.DataFrame({
        "time": pd.to_datetime(h["time"]),
        "solar": h["shortwave_radiation"],
        "cloud_cover": h["cloud_cover"],
    })
    hist.to_csv(hist_path, index=False)

hist = add_features(hist.dropna().reset_index(drop=True))
print(f"Hours of history: {len(hist)}")

past_arr = hist[["sol", "cloud", "cs", "hsin", "hcos"]].values
fut_arr = hist[["cloud", "cs", "hsin", "hcos"]].values
cs_arr = hist["cs"].values
sol = hist["sol"].values

# 2. Sequences
Xp, Xf, Xc, y = [], [], [], []
for i in range(len(hist) - LOOKBACK - HORIZON + 1):
    s, e = i + LOOKBACK, i + LOOKBACK + HORIZON
    Xp.append(past_arr[i:s])
    Xf.append(fut_arr[s:e])
    Xc.append(cs_arr[s:e])
    y.append(sol[s:e])
Xp, Xf, Xc, y = map(np.array, (Xp, Xf, Xc, y))

split = int(len(Xp) * 0.8)
tr = slice(0, split)
te = slice(split, None)
print(f"Train samples: {split} | Test samples: {len(Xp) - split}\n")

# 3. Model: output = cloud_factor (0..1.1) x clear-sky curve
past_in = Input(shape=(LOOKBACK, 5))
fut_in = Input(shape=(HORIZON, 4))
cs_in = Input(shape=(HORIZON,))
a = LSTM(64)(past_in)
b = Flatten()(fut_in)
z = Concatenate()([a, b])
z = Dense(128, activation="relu")(z)
z = Dense(HORIZON, activation="sigmoid")(z)
kt = Rescaling(1.1)(z)
out = Multiply()([kt, cs_in])
model = Model([past_in, fut_in, cs_in], out)
model.compile(optimizer="adam", loss="mae")

model.fit(
    [Xp[tr], Xf[tr], Xc[tr]], y[tr],
    validation_split=0.1, epochs=40, batch_size=64,
    callbacks=[EarlyStopping(patience=5, restore_best_weights=True)],
    verbose=2,
)

# 4. Accuracy
pred = model.predict([Xp[te], Xf[te], Xc[te]], verbose=0)
y_te = y[te]
mae = mean_absolute_error(y_te.flatten(), pred.flatten()) * SCALE
rmse = np.sqrt(mean_squared_error(y_te.flatten(), pred.flatten())) * SCALE
base = Xp[te][:, -HORIZON:, 0]
base_mae = mean_absolute_error(y_te.flatten(), base.flatten()) * SCALE
cs_mae = mean_absolute_error(y_te.flatten(), (Xc[te] * 0.75).flatten()) * SCALE

print("\n=== RESULTS ===")
print(f"LSTM MAE        : {mae:.1f} W/m2")
print(f"LSTM RMSE       : {rmse:.1f} W/m2")
print(f"Baseline MAE    : {base_mae:.1f} W/m2 (repeat yesterday)")
print(f"Clear-sky x0.75 : {cs_mae:.1f} W/m2 (no-AI physics guess)")
print(f"Improvement     : {(1 - mae / base_mae) * 100:.1f}% vs baseline")

model.save("models/lstm_forecast.keras")

# 5. Plot (last 3 test days)
idx = np.arange(len(y_te) - 72, len(y_te), 24)
actual = np.concatenate([y_te[i] for i in idx]) * SCALE
predicted = np.concatenate([pred[i] for i in idx]) * SCALE
plt.figure(figsize=(13, 5))
plt.plot(actual, label="Actual", color="steelblue")
plt.plot(predicted, label="LSTM predicted", color="darkorange", linestyle="--")
plt.title(f"LSTM Solar Forecast: Predicted vs Actual (MAE {mae:.0f} W/m2)")
plt.xlabel("Hours")
plt.ylabel("Solar irradiance (W/m2)")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("plots/lstm_predicted_vs_actual.png", dpi=150)
print("Plot saved -> plots/lstm_predicted_vs_actual.png")

# 6. REAL-TIME forecast
live_url = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=shortwave_radiation,cloud_cover&past_days=7&forecast_days=3"
    "&timezone=Asia%2FKolkata"
)
lr = requests.get(live_url, timeout=30)
lr.raise_for_status()
lh = lr.json()["hourly"]
live = pd.DataFrame({
    "time": pd.to_datetime(lh["time"]),
    "solar": lh["shortwave_radiation"],
    "cloud_cover": lh["cloud_cover"],
}).dropna().reset_index(drop=True)
live = add_features(live)

now = pd.Timestamp.now().floor("h")
past_live = live[live["time"] <= now].tail(LOOKBACK)
fut_live = live[live["time"] > now].head(HORIZON)

if len(past_live) == LOOKBACK and len(fut_live) == HORIZON:
    xp = past_live[["sol", "cloud", "cs", "hsin", "hcos"]].values[np.newaxis]
    xf = fut_live[["cloud", "cs", "hsin", "hcos"]].values[np.newaxis]
    xc = fut_live["cs"].values[np.newaxis]
    p = np.clip(model.predict([xp, xf, xc], verbose=0)[0] * SCALE, 0, None)
    live_fc = pd.DataFrame({
        "time": fut_live["time"].values,
        "predicted_solar_wm2": p,
        "cloud_cover_pct": fut_live["cloud_cover"].values,
    })
    live_fc.to_csv("data/lstm_live_forecast.csv", index=False)
    print("\nLive 24-hour forecast saved -> data/lstm_live_forecast.csv")
    print(live_fc.to_string(index=False))
else:
    print("\nNot enough live data, skipped live forecast")

print("\nDone! LSTM v3 is ready.")