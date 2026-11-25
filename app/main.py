"""
main.py
-------
SuryaGrid AI — FastAPI backend

Endpoints
  GET  /                   health ping
  GET  /health             detailed status
  GET  /solar/current      latest reading per village
  GET  /forecast/24hr      hourly solar & load forecast for next 24 h
  GET  /alerts/latest      most recent alerts (filterable)
  POST /alerts/create      create a manual alert

The MQTT subscriber is started automatically inside a background thread
when the application starts (FastAPI lifespan).
"""

import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

import mqtt_subscriber
from database import engine, get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [API] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — start MQTT subscriber on boot, stop on shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting MQTT subscriber…")
    try:
        mqtt_subscriber.start()
        log.info("MQTT subscriber is live.")
    except Exception as exc:
        log.error("Could not start MQTT subscriber: %s", exc)
    yield
    log.info("Stopping MQTT subscriber…")
    mqtt_subscriber.stop()


app = FastAPI(
    title="SuryaGrid AI API",
    version="1.0.0",
    description="Backend API for the SuryaGrid AI rural solar monitoring platform.",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

VALID_ALERT_TYPES = Literal["theft", "fault", "equipment_failure", "low_battery"]


class AlertIn(BaseModel):
    village_id: str
    alert_type: VALID_ALERT_TYPES
    message: Optional[str] = None

    @field_validator("village_id")
    @classmethod
    def village_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("village_id must not be empty")
        return v.strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
def home():
    return {"message": "SuryaGrid AI backend is running", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    """Check API + database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"
    return {
        "api": "ok",
        "database": db_status,
        "mqtt_subscriber": "running" if mqtt_subscriber._thread and mqtt_subscriber._thread.is_alive() else "stopped",
    }


@app.get("/solar/current", tags=["Solar"])
def solar_current():
    """Return the most recent meter reading for every village."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (village_id)
                   time, village_id, solar_kw, load_kw, battery_pct, voltage
            FROM   meter_readings
            ORDER  BY village_id, time DESC
        """)).mappings().all()
    return [dict(r) for r in rows]


@app.get("/forecast/24hr", tags=["Solar"])
def forecast_24hr():
    """
    Return an hourly solar & load forecast for the next 24 hours.

    Forecast method: for each village and each hour-of-day (0–23), compute
    the average solar_kw and load_kw from the last 7 days of readings, then
    project those averages onto the next 24 hours starting from now.

    Uses TimescaleDB time_bucket() for efficient aggregation.
    Falls back to an empty list if there are fewer than 10 readings in the DB.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH hourly_avg AS (
                SELECT
                    village_id,
                    EXTRACT(HOUR FROM time AT TIME ZONE 'UTC')::int AS hour_of_day,
                    ROUND(AVG(solar_kw)::numeric, 2)  AS predicted_solar_kw,
                    ROUND(AVG(load_kw)::numeric, 2)   AS predicted_load_kw,
                    COUNT(*)                           AS sample_count
                FROM meter_readings
                WHERE time >= NOW() - INTERVAL '7 days'
                GROUP BY village_id, hour_of_day
            )
            SELECT
                village_id,
                hour_of_day,
                predicted_solar_kw,
                predicted_load_kw,
                sample_count,
                (NOW()::date + (hour_of_day || ' hours')::interval) AS forecast_time
            FROM hourly_avg
            ORDER BY village_id, hour_of_day
        """)).mappings().all()

    return [dict(r) for r in rows]


@app.get("/alerts/latest", tags=["Alerts"])
def alerts_latest(
    village_id: Optional[str] = Query(default=None, description="Filter by village ID"),
    limit: int = Query(default=10, ge=1, le=100, description="Number of alerts to return"),
):
    """Return the most recent alerts, optionally filtered by village."""
    sql = "SELECT id, time, village_id, alert_type, message FROM alerts"
    params: dict = {}

    if village_id:
        sql += " WHERE village_id = :village_id"
        params["village_id"] = village_id

    sql += " ORDER BY time DESC LIMIT :limit"
    params["limit"] = limit

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    return [dict(r) for r in rows]


@app.post("/alerts/create", status_code=201, tags=["Alerts"])
def alerts_create(a: AlertIn):
    """
    Create a manual alert.

    alert_type must be one of: theft | fault | equipment_failure | low_battery
    """
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO alerts (village_id, alert_type, message)
                VALUES (:village_id, :alert_type, :message)
                RETURNING id, time
            """),
            a.model_dump(),
        )
        row = result.mappings().one()

    return {
        "status": "created",
        "id": row["id"],
        "time": row["time"],
        "village_id": a.village_id,
        "alert_type": a.alert_type,
    }