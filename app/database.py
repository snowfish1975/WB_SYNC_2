import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Render иногда отдаёт postgres://, SQLAlchemy требует postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def _create_engine(url: str):
    """Создание engine; pg-специфичные параметры пула применяются только для PostgreSQL
    (SQLite, например в тестах, их не принимает)."""
    from sqlalchemy import engine as sa_engine

    if url.startswith("postgresql"):
        return create_engine(
            url, pool_pre_ping=True, pool_recycle=300,
            pool_size=10, max_overflow=5, pool_timeout=30,
        )
    return create_engine(url)


engine = _create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
