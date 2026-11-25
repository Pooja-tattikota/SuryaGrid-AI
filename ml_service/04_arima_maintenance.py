import pandas as pd
import numpy as np
from statsmodels.tsa.arima.model import ARIMA
import joblib
import matplotlib.pyplot as plt
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

print("=== ARIMA - Predictive Maintenance (Voltage Forecast) ===\n")

# 1. Load meter data
df = pd.read_csv("data/meter_data_with_anomalies.csv", parse_dates=["timestamp"])
df = df.sort_values("timestamp").reset_index(drop=True)

normal = df[df["anomaly"] == 1].copy()
voltage_series = normal["voltage"].values
print(f"Using {len(voltage_series)} normal voltage readings for training")

# 2. Fit ARIMA
model = ARIMA(voltage_series, order=(5, 1, 0))
print("Fitting ARIMA model...")
result = model.fit()

# 3. Forecast next 72 hours
forecast_steps = 72
forecast_result = result.get_forecast(steps=forecast_steps)
forecast = np.asarray(forecast_result.predicted_mean)
conf_int = np.asarray(forecast_result.conf_int(alpha=0.05))

last_time = df["timestamp"].iloc[-1]
future_times = pd.date_range(start=last_time + pd.Timedelta(hours=1), periods=forecast_steps, freq="h")

forecast_df = pd.DataFrame({
    "timestamp": future_times,
    "forecast_voltage": forecast,
    "lower_95": conf_int[:, 0],
    "upper_95": conf_int[:, 1],
})

# 4. Maintenance rule
SAFE_LOW, SAFE_HIGH = 210, 250
risk_mask = (forecast_df["forecast_voltage"] < SAFE_LOW) | (forecast_df["forecast_voltage"] > SAFE_HIGH)
risk_hours = forecast_df[risk_mask]

if len(risk_hours) > 0:
    print(f"\nMAINTENANCE ALERT: {len(risk_hours)} hours predicted outside safe range (210-250 V)")
    print(risk_hours[["timestamp", "forecast_voltage"]].head())
else:
    print("\nVoltage forecast stays within safe range (210-250 V) for next 72 hours")

# 5. Save
Path("models").mkdir(exist_ok=True)
joblib.dump(result, "models/arima_voltage.joblib")
forecast_df.to_csv("data/arima_voltage_forecast.csv", index=False)
print("\nModel saved    -> models/arima_voltage.joblib")
print("Forecast saved -> data/arima_voltage_forecast.csv")

# 6. Plot
plt.figure(figsize=(14, 6))
recent = df.tail(24 * 5)
plt.plot(recent["timestamp"], recent["voltage"], label="Actual Voltage", color="steelblue")
plt.plot(forecast_df["timestamp"], forecast_df["forecast_voltage"], label="72-hour Forecast", color="darkorange", linewidth=2)
plt.fill_between(forecast_df["timestamp"], forecast_df["lower_95"], forecast_df["upper_95"],
                 color="orange", alpha=0.2, label="95% Confidence")
plt.axhline(230, color="gray", linestyle="--", alpha=0.7, label="Nominal 230V")
plt.axhline(SAFE_LOW, color="red", linestyle=":", alpha=0.8)
plt.axhline(SAFE_HIGH, color="red", linestyle=":", alpha=0.8)
plt.title("ARIMA Voltage Forecast - Predictive Maintenance (SuryaGrid AI)")
plt.ylabel("Voltage (V)")
plt.xlabel("Time")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("plots/arima_voltage_forecast.png", dpi=150)
print("Plot saved     -> plots/arima_voltage_forecast.png")
print("\nDone! ARIMA predictive maintenance is ready.")