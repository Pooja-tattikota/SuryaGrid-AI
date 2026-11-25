import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import random
from datetime import datetime, timedelta

# ─── PAGE CONFIG ───────────────────────────────────────────────
st.set_page_config(page_title="SuryaGrid AI", page_icon="⚡", layout="wide")

# ─── HEADER ────────────────────────────────────────────────────
st.title("⚡ SuryaGrid AI — Village Energy Dashboard")
st.caption("Sangareddy District, Telangana · Live Monitoring")

# ─── SIDEBAR CONTROLS ──────────────────────────────────────────
st.sidebar.header("🎛️ Controls")

village = st.sidebar.selectbox(
    "Select Village",
    [f"Village {i}" for i in range(1, 86)],
    index=0
)

time_range = st.sidebar.radio(
    "Time Range",
    ["Last 4 hours", "Last 12 hours", "Last 24 hours"],
    index=0
)

refresh = st.sidebar.button("🔄 Refresh Data")

st.sidebar.divider()
st.sidebar.markdown("**About SuryaGrid AI**")
st.sidebar.caption("AI-powered solar microgrid monitoring for 85 gram panchayats in Sangareddy, Telangana.")

# ─── DATA GENERATOR ────────────────────────────────────────────
def generate_data(village_name, hours):
    random.seed(sum(ord(c) for c in village_name))  # each village gets different but consistent data
    now = datetime.now()
    points = hours * 12  # one reading every 5 minutes
    times = [now - timedelta(minutes=5*i) for i in range(points)][::-1]
    solar = [
        max(0, 4.2 * max(0, (t.hour - 6) / 6) * max(0, (18 - t.hour) / 6) + random.uniform(-0.2, 0.2))
        for t in times
    ]
    load = [2.5 + random.uniform(-0.3, 0.5) for _ in times]
    battery = []
    level = 60.0
    for s, l in zip(solar, load):
        level += (s - l) * 2
        level = min(100, max(10, level))
        battery.append(level)
    return pd.DataFrame({"time": times, "solar_kw": solar, "load_kw": load, "battery_pct": battery})

# ─── LOAD DATA ─────────────────────────────────────────────────
hours_map = {"Last 4 hours": 4, "Last 12 hours": 12, "Last 24 hours": 24}
df = generate_data(village, hours_map[time_range])

# ─── STATUS BANNER ─────────────────────────────────────────────
battery_now = df["battery_pct"].iloc[-1]
solar_now   = df["solar_kw"].iloc[-1]
load_now    = df["load_kw"].iloc[-1]

if battery_now < 30:
    st.error(f"🔴 ALERT — {village}: Battery critically low ({battery_now:.0f}%). Diesel backup may be needed.")
elif load_now > solar_now * 1.5:
    st.warning(f"🟡 WARNING — {village}: Load is much higher than solar generation. Battery draining faster than usual.")
else:
    st.success(f"🟢 ALL GOOD — {village} is running normally. Solar is meeting demand.")

st.divider()

# ─── METRIC TILES ──────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("☀️ Solar Output",  f"{solar_now:.2f} kW",   delta=f"{solar_now - df['solar_kw'].iloc[-2]:.2f} kW")
col2.metric("🏘️ Current Load",  f"{load_now:.2f} kW",    delta=f"{load_now - df['load_kw'].iloc[-2]:.2f} kW")
col3.metric("🔋 Battery",       f"{battery_now:.0f}%",   delta=f"{battery_now - df['battery_pct'].iloc[-2]:.0f}%")
col4.metric("🚨 Active Alerts", "2")

st.divider()

# ─── SOLAR VS LOAD CHART ───────────────────────────────────────
st.subheader(f"☀️ Solar Generation vs Load — {village}")
fig = go.Figure()
fig.add_trace(go.Scatter(x=df["time"], y=df["solar_kw"], name="Solar (kW)", line=dict(color="#00C9A7", width=2), fill="tozeroy", fillcolor="rgba(0,201,167,0.1)"))
fig.add_trace(go.Scatter(x=df["time"], y=df["load_kw"],  name="Load (kW)",  line=dict(color="#F97316", width=2)))
fig.update_layout(template="plotly_dark", height=350, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
st.plotly_chart(fig, width="stretch")

st.divider()

# ─── BATTERY GAUGE + ALERTS ────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("🔋 Battery Level")
    gauge = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=battery_now,
        delta={"reference": df["battery_pct"].iloc[-6]},  # compare to 30 mins ago
        gauge={
            "axis": {"range": [0, 100]},
            "bar":  {"color": "#00C9A7", "thickness": 0.3},
            "steps": [
                {"range": [0,  30], "color": "#1a0a0a"},
                {"range": [30, 60], "color": "#1a1000"},
                {"range": [60,100], "color": "#0a1a10"}
            ],
            "threshold": {"line": {"color": "white", "width": 3}, "thickness": 0.8, "value": 30}
        },
        number={"suffix": "%", "font": {"size": 48}}
    ))
    gauge.update_layout(template="plotly_dark", height=280, margin=dict(l=30, r=30, t=30, b=10))
    st.plotly_chart(gauge, width="stretch")

with col_b:
    st.subheader("🚨 Alerts — In Farmer's Words")
    
    # Dynamic alert based on actual data
    if solar_now < 1.0:
        st.warning("🌥️ Not much sun right now — battery is doing the work. This is normal in evening hours.")
    else:
        st.info(f"☀️ Good solar day! Panels are generating {solar_now:.1f} kW. Surplus is charging the battery.")

    if battery_now < 40:
        st.error("⚠️ Battery is getting low. Try to reduce use of pump and mill until sunrise tomorrow.")
    elif battery_now > 80:
        st.success("✅ Battery is well charged. Safe to run the water pump and grain mill.")

    st.divider()
    st.markdown("**Past Alerts Today**")
    st.error("⚠️ Village 12 — Voltage spike detected (08:42 AM)")
    st.warning("🔍 Village 7 — Possible meter tampering (07:15 AM)")
    st.success("✅ Village 3 — Transformer check passed (06:00 AM)")

st.divider()

# ─── BATTERY TREND CHART ───────────────────────────────────────
st.subheader("🔋 Battery Level Over Time")
fig2 = go.Figure()
fig2.add_trace(go.Scatter(
    x=df["time"], y=df["battery_pct"],
    name="Battery %",
    line=dict(color="#facc15", width=2),
    fill="tozeroy", fillcolor="rgba(250,204,21,0.1)"
))
fig2.add_hline(y=30, line_dash="dash", line_color="red",   annotation_text="Critical level (30%)")
fig2.add_hline(y=80, line_dash="dash", line_color="green", annotation_text="Full charge (80%)")
fig2.update_layout(template="plotly_dark", height=250, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig2, width="stretch")

# ─── FOOTER ────────────────────────────────────────────────────
st.caption("SuryaGrid AI · Team Phantom · AAROHAN 2.0 · Data updates every 5 minutes")