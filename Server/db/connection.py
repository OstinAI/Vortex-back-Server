# -*- coding: utf-8 -*-
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from db.models import Base
import os

def get_database_url():
    # 1. Пробуем взять данные из переменных окружения Google Cloud
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASS", "123456")
    db_name = os.getenv("DB_NAME", "vortex")
    instance_connection = os.getenv("INSTANCE_CONNECTION_NAME")

    if instance_connection:
        # ✅ МЕХАНИКА ДЛЯ GOOGLE CLOUD RUN
        # Подключаемся через Unix-сокет, который пробрасывает Google Cloud SQL Proxy
        return f"postgresql+psycopg2://{db_user}:{db_pass}@/{db_name}?host=/cloudsql/{instance_connection}"
    
    # 🏠 МЕХАНИКА ДЛЯ ЛОКАЛЬНОГО ЗАПУСКА (ваш текущий вариант)
    return f"postgresql+psycopg2://{db_user}:{db_pass}@127.0.0.1:5432/{db_name}"

DATABASE_URL = get_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    echo=False,
    future=True
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False)
)

def init_db():
    # Эта команда создаст таблицы, если их еще нет в Cloud SQL
    Base.metadata.create_all(bind=engine)

def get_session():
    return SessionLocal()
