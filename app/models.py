
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from database import engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MeterReading(Base):
    __tablename__ = "meter_readings"

    time = Column(DateTime(timezone=True), primary_key=True)
    village_id = Column(String(100), primary_key=True)
    solar_kw = Column(Float)
    load_kw = Column(Float)
    battery_pct = Column(Float)
    voltage = Column(Float)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    time = Column(DateTime(timezone=True), server_default=func.now())
    village_id = Column(String(100))
    alert_type = Column(String(100))
    message = Column(String)
