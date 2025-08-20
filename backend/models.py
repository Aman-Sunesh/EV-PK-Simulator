# models.py
#
# ──────────────────────────────────────────────────────────────────────────────
# EV–PK Simulator — SQLAlchemy ORM Models
#
# Tables
#  • studies
#      - Curated/benchmark study metadata and the raw CSV payload.
#      - Columns: id, doi, species, route, dose, csv_blob
#  • user_uploads
#      - Per-user ad-hoc uploads normalized to JSON.
#      - Columns: id, filename, data (JSON)
#  • pk_model_results
#      - Fitted model results keyed to a specific upload.
#      - Columns: id, upload_id (FK-like), model_type, parameters (JSON)
#
# Notes
#  • Keep this module schema-only (no business logic).
#  • JSON columns work across backends; on SQLite they’re stored as TEXT.
#  • Migrations (alembic) should evolve this schema; do not mutate in-place.
# ──────────────────────────────────────────────────────────────────────────────

import numpy as np
from sqlalchemy import Column, Integer, String, LargeBinary, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Study(Base):
    __tablename__ = 'studies'
    id = Column(Integer, primary_key=True, index=True)
    doi = Column(String, unique=True, index=True)
    species = Column(String)
    route = Column(String)
    dose = Column(String)
    csv_blob = Column(LargeBinary)

class UserUpload(Base):
    __tablename__ = 'user_uploads'
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    data = Column(JSON)

class PKModelResult(Base):
    __tablename__ = 'pk_model_results'
    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(Integer)
    model_type = Column(String)
    parameters = Column(JSON)