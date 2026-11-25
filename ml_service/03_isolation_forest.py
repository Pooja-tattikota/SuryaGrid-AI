import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score

print("=== Isolation Forest v3 - Anomaly Detection ===\n")
np.random.seed(42)
PANEL_KW = 5.0
FEATURES = ["load_ratio", "voltage", "solar_ratio", "irr"]

# 1. Last 30 days of REAL hourly sunlight drives the simulated meter
hist = pd.read_csv("data/hourly_history_v2.csv", parse_dates=["time"]).dropna()
df = hist.tail(24 * 30).reset_index(drop=True)[["time", "solar"]]
df = df.rename(columns={"time": "timestamp"})
n = len(df)
df["hour"] = df["timestamp"].dt.hour

base_load = np.clip(2.5 + 1.8 * np.sin((df["hour"].values - 7) * np.pi / 12), 1.2, 5.5)
df["load_kw"] = np.clip(base_load + np.random.normal(0, 0.25, n), 0.3, 8.0)
df["voltage"] = 230 + np.random.normal(0, 3.5, n)
df["irr"] = df["solar"] / 1000
df["solar_kw"] = df["irr"] * PANEL_KW * 0.8
df["true_anomaly"] = 0

# 2. Inject known faults
df.loc[200:220, "load_kw"] *= 0.35                       # theft
df.loc[450:455, "voltage"] = 275                         # voltage spike
sun_rows = df.index[(df.index >= 590) & (df["solar_kw"] > 2.0)][:8]
df.loc[sun_rows, "solar_kw"] = 0                         # inverter fault in daylight
for idx in (list(range(200, 221)), list(range(450, 456)), list(sun_rows)):
    df.loc[idx, "true_anomaly"] = 1

# 3. Features: load vs normal for that hour, solar vs available sunlight
normal_mask = df["true_anomaly"] == 0
profile = df.groupby("hour")["load_kw"].median().to_dict()
df["load_ratio"] = df["load_kw"] / df["hour"].map(profile)
df["solar_ratio"] = df["solar_kw"] / (df["irr"] * PANEL_KW * 0.8 + 1e-3)

# 4. Train on the mixed history (unsupervised, as on a real meter log)
model = IsolationForest(n_estimators=300, contamination=0.05, random_state=42, n_jobs=-1)
model.fit(df[FEATURES])
df["anomaly"] = model.predict(df[FEATURES])
df["anomaly_score"] = model.decision_function(df[FEATURES])

flag = (df["anomaly"] == -1).astype(int)
print(f"Isolation Forest alone: detected {flag.sum()} of {n} hours")
print(f"  Precision: {precision_score(df['true_anomaly'], flag):.2f}")
print(f"  Recall   : {recall_score(df['true_anomaly'], flag):.2f}")

hybrid = ((df["anomaly"] == -1) | (df["voltage"] > 250) | (df["voltage"] < 210)).astype(int)
print(f"Isolation Forest + voltage safety rule: detected {hybrid.sum()} of {n} hours")
print(f"  Precision: {precision_score(df['true_anomaly'], hybrid):.2f}")
print(f"  Recall   : {recall_score(df['true_anomaly'], hybrid):.2f}")
# 5. Save
Path("models").mkdir(exist_ok=True)
joblib.dump(model, "models/isolation_forest.joblib")
joblib.dump(profile, "models/load_profile.joblib")
df.to_csv("data/meter_data_with_anomalies.csv", index=False)
print("\nModel saved -> models/isolation_forest.joblib")
print("Load profile saved -> models/load_profile.joblib")

# 6. Plot
bad = df["anomaly"] == -1
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
for ax, col, color, lab in zip(axes, ["load_kw", "voltage", "solar_kw"],
                               ["steelblue", "green", "orange"],
                               ["Load (kW)", "Voltage (V)", "Solar (kW)"]):
    ax.plot(df["timestamp"], df[col], color=color, label=lab)
    ax.scatter(df.loc[bad, "timestamp"], df.loc[bad, col], color="red", s=40, label="Anomaly", zorder=5)
    ax.set_ylabel(lab)
    ax.legend()
axes[0].set_title("Isolation Forest - Anomaly Detection (SuryaGrid AI)")
plt.tight_layout()
plt.savefig("plots/isolation_forest_anomalies.png", dpi=150)
print("Plot saved  -> plots/isolation_forest_anomalies.png")