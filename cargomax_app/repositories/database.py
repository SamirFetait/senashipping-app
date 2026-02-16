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
    from .cargo_type_repository import CargoTypeORM  # noqa: F401

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

    # Migration: add deck table columns to livestock_pens if missing
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE livestock_pens ADD COLUMN pen_no INTEGER"
            ))
            conn.commit()
    except Exception:
        pass
    for col in ("area_a_m2", "area_b_m2", "area_c_m2", "area_d_m2",
                "tcg_a_m", "tcg_b_m", "tcg_c_m", "tcg_d_m"):
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"ALTER TABLE livestock_pens ADD COLUMN {col} REAL"
                ))
                conn.commit()
        except Exception:
            pass  # Column already exists

    # Migration: tank outline and deck for DXF-derived tanks
    for col, typ in (("outline_json", "TEXT"), ("deck_name", "VARCHAR(32)")):
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"ALTER TABLE tanks ADD COLUMN {col} {typ}"
                ))
                conn.commit()
        except Exception:
            pass

    # Migration: tank category (Storing) for loading condition tab matching
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE tanks ADD COLUMN category VARCHAR(64) DEFAULT 'Misc. Tanks'"
            ))
            conn.commit()
    except Exception:
        pass

    # Migration: tank description and density fields for detailed tank management
    for col, typ, default in (
        ("description", "VARCHAR(255)", "''"),
        ("density_t_per_m3", "REAL", "1.0"),
    ):
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"ALTER TABLE tanks ADD COLUMN {col} {typ} DEFAULT {default}"
                ))
                conn.commit()
        except Exception:
            pass  # Column already exists

    # Migration: cargo_types calculation fields (Edit Cargo dialog)
    for col, typ in (
        ("method", "VARCHAR(64)"),
        ("cargo_subtype", "VARCHAR(128)"),
        ("avg_weight_per_head_kg", "REAL"),
        ("vcg_from_deck_m", "REAL"),
        ("deck_area_per_head_m2", "REAL"),
        ("dung_weight_pct_per_day", "REAL"),
    ):
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"ALTER TABLE cargo_types ADD COLUMN {col} {typ}"
                ))
                conn.commit()
        except Exception:
            pass

    global SessionLocal
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    return SessionLocal

