import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

# Keep your existing DATABASE_URL in .env. The fallback is only a default.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://surya:surya123@localhost:5433/surya_grid",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()