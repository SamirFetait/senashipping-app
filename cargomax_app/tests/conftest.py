"""Pytest configuration and fixtures."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on path when running tests
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from senashipping_app.repositories.database import init_database
from senashipping_app.models import Ship, Tank, TankType, Voyage, LoadingCondition


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database and return its path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # Windows may hold file; ignore cleanup failure


@pytest.fixture
def db_session(temp_db):
    """Provide a database session with initialized schema."""
    from sqlalchemy import create_engine
    from senashipping_app.repositories.database import Base
    from senashipping_app.repositories.ship_repository import ShipORM
    from senashipping_app.repositories.tank_repository import TankORM
    from senashipping_app.repositories.voyage_repository import VoyageORM, LoadingConditionORM

    engine = create_engine(f"sqlite:///{temp_db}", future=True)
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def sample_ship():
    """Create a sample Ship domain object."""
    return Ship(
        id=None,
        name="Test Vessel",
        imo_number="1234567",
        flag="LR",
        length_overall_m=150.0,
        breadth_m=25.0,
        depth_m=15.0,
        design_draft_m=10.0,
    )


@pytest.fixture
def sample_tanks():
    """Create sample Tank domain objects."""
    return [
        Tank(
            id=1,
            ship_id=1,
            name="Tank 1",
            tank_type=TankType.CARGO,
            capacity_m3=500.0,
            longitudinal_pos=0.3,
            kg_m=5.0,
        ),
        Tank(
            id=2,
            ship_id=1,
            name="Tank 2",
            tank_type=TankType.CARGO,
            capacity_m3=500.0,
            longitudinal_pos=0.7,
            kg_m=5.0,
        ),
    ]


@pytest.fixture
def sample_condition():
    """Create a sample LoadingCondition with tank volumes."""
    return LoadingCondition(
        id=None,
        voyage_id=1,
        name="Departure",
        tank_volumes_m3={1: 250.0, 2: 250.0},
    )
