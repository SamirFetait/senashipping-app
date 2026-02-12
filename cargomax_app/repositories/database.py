"""
SQLAlchemy database setup for the senashipping desktop app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    """Base declarative class for ORM models."""

    pass


# Will be assigned a sessionmaker instance by init_database at startup
SessionLocal: sessionmaker | None = None


def get_db() -> Generator:
    """Provide a SQLAlchemy session (for non-Qt callers)."""
    if SessionLocal is None:
        raise RuntimeError("SessionLocal is not initialized")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database(db_path: Path) -> sessionmaker:
    """
    Initialize the SQLite database, create tables, and configure SessionLocal.

    This must be called once at application startup (done in main.py).
    """
    # Import ORM models so their metadata is registered on Base
    from .ship_repository import ShipORM  # noqa: F401
    from .tank_repository import TankORM  # noqa: F401
    from .voyage_repository import VoyageORM, LoadingConditionORM  # noqa: F401
    from .livestock_pen_repository import LivestockPenORM  # noqa: F401

    engine = create_engine(f"sqlite:///{db_path}", future=True, echo=False)
    Base.metadata.create_all(bind=engine)

    # Migration: add pen_loadings_json if missing (existing DBs)
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE loading_conditions ADD COLUMN pen_loadings_json TEXT DEFAULT '{}'"
            ))
            conn.commit()
    except Exception:
        pass  # Column already exists

    global SessionLocal
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    return SessionLocal

