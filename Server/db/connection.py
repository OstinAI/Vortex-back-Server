# -*- coding: utf-8 -*-
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from db.models import Base
import os

DATABASE_URL = "postgresql+psycopg2://postgres:123456@127.0.0.1:5432/vortex"
# DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False)
)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_session():
    return SessionLocal()