import numpy as np
from sqlalchemy import Column, Integer, String, LargeBinary, JSON
from sqlalchemy.ext.declarative import declarative_base

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