# database.py
#
# ──────────────────────────────────────────────────────────────────────
# SQLAlchemy setup for the EV Portal backend.
# Provides:
#  • Engine bound to a local SQLite DB (./ev_portal.db)
#  • Session factory (SessionLocal) for request-scoped sessions
#  • init_db() to create all tables from models.Base
#  • get_db() generator for FastAPI dependency injection
# Notes:
#  • check_same_thread=False is required for SQLite when sharing
#    connections across threads (e.g., FastAPI’s worker model).
#  • SQLAlchemy 2.0 “future” flags enabled for forward compatibility.
# ─────────────────────────────────────────────────────────────────────

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

# SQLite URL (creates ev_portal.db in your backend folder)
DATABASE_URL = "sqlite:///./ev_portal.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()