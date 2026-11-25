import requests
import pandas as pd
from pathlib import Path
from datetime import datetime

# Sangareddy coordinates
LAT = 17.6
LON = 78.0

def get_live_solar_data():
    """
    Pull current + hourly solar radiation from Open-Meteo (free, no API key)
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&hourly=shortwave_radiation,direct_radiation,diffuse_radiation,temperature_2m"
        "&current=shortwave_radiation,temperature_2m"
        "&timezone=Asia%2FKolkata"
        "&forecast_days=3"
    )

    print("Fetching live solar + weather data from Open-Meteo...")
    response = requests.get(url, timeout=15)

    if response.status_code != 200:
        print("Error:", response.status_code)
        print(response.text[:300])
        return None

    data = response.json()

    # Current values
    current = data.get("current", {})
    print("\n=== CURRENT CONDITIONS (Sangareddy) ===")
    print(f"Time                : {current.get('time')}")
    print(f"Solar irradiance    : {current.get('shortwave_radiation')} W/m²")
    print(f"Temperature         : {current.get('temperature_2m')} °C")

    # Hourly data
    hourly = data["hourly"]
    df = pd.DataFrame({
        "time": hourly["time"],
        "shortwave_radiation": hourly["shortwave_radiation"],
        "direct_radiation": hourly["direct_radiation"],
        "diffuse_radiation": hourly["diffuse_radiation"],
        "temperature_2m": hourly["temperature_2m"]
    })

    df["time"] = pd.to_datetime(df["time"])

    # Save latest live data
    save_path = Path("data/live_solar_data.csv")
    df.to_csv(save_path, index=False)
    print(f"\nLive hourly data saved → {save_path}")
    print(f"Total hours fetched  : {len(df)}")
    print(f"From {df['time'].min()} → {df['time'].max()}")

    print("\nNext 6 hours preview:")
    print(df.head(6).to_string(index=False))

    return df


if __name__ == "__main__":
    get_live_solar_data()