import requests
import pandas as pd
from pathlib import Path

# Location: Sangareddy
LAT = 17.6
LON = 78.0

# Date range (10 years of real data)
START = "20140101"
END = "20241231"          # you can change this later if needed

# NASA POWER API URL (daily solar irradiance)
url = (
    f"https://power.larc.nasa.gov/api/temporal/daily/point"
    f"?parameters=ALLSKY_SFC_SW_DWN"
    f"&community=RE"
    f"&longitude={LON}"
    f"&latitude={LAT}"
    f"&start={START}"
    f"&end={END}"
    f"&format=CSV"
)

print("Downloading real solar data from NASA POWER...")
print("This may take 10–20 seconds...\n")

response = requests.get(url)

if response.status_code != 200:
    print("Error downloading data. Status code:", response.status_code)
    print(response.text[:500])
    exit()

# Save the raw response
raw_path = Path("data/sangareddy_solar_raw.csv")
raw_path.write_text(response.text)
print(f"Raw data saved → {raw_path}")

# NASA CSV has header lines before the actual data.
# We need to find where the real columns start.
lines = response.text.splitlines()

# Find the line that starts with "YEAR,MO,DY,..."
header_idx = None
for i, line in enumerate(lines):
    if line.startswith("YEAR,MO,DY"):
        header_idx = i
        break

if header_idx is None:
    print("Could not find header in the CSV. Check the raw file.")
    exit()

# Read only from the header onwards
from io import StringIO
clean_csv = "\n".join(lines[header_idx:])
df = pd.read_csv(StringIO(clean_csv))

# Create a proper date column
df["date"] = pd.to_datetime(df[["YEAR", "MO", "DY"]].astype(str).agg("-".join, axis=1))

# Keep only useful columns and rename
df = df[["date", "ALLSKY_SFC_SW_DWN"]].copy()
df.rename(columns={"ALLSKY_SFC_SW_DWN": "solar_irradiance"}, inplace=True)

# Remove any missing values (-999 is NASA's missing flag)
df = df[df["solar_irradiance"] != -999].dropna()

# Save clean version
clean_path = Path("data/sangareddy_solar.csv")
df.to_csv(clean_path, index=False)

print(f"Clean data saved → {clean_path}")
print(f"Total days: {len(df)}")
print(f"Date range: {df['date'].min().date()} → {df['date'].max().date()}")
print("\nFirst 5 rows:")
print(df.head())
print("\nDone! Historical solar data is ready.")