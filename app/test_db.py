from sqlalchemy import inspect
from database import engine
from models import MeterReading, Alert

inspector = inspect(engine)

print("Database connection successful!")

print("\nMeter Reading columns:")
for column in inspector.get_columns("meter_readings"):
    print(column["name"])

print("\nAlert columns:")
for column in inspector.get_columns("alerts"):
    print(column["name"])

print("\nModels loaded successfully!")
