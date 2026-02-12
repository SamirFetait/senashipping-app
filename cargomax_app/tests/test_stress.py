"""Stress and corrupted-data tests."""

from __future__ import annotations

import pytest

from senashipping_app.models import Ship, Tank, TankType, Voyage, LoadingCondition
from senashipping_app.repositories.ship_repository import ShipRepository
from senashipping_app.repositories.voyage_repository import VoyageRepository, ConditionRepository
from senashipping_app.services.voyage_service import VoyageService


class TestCorruptedData:
    def test_condition_repo_parse_malformed_json(self, db_session):
        """ConditionRepository handles malformed tank_volumes_json gracefully."""
        ship_repo = ShipRepository(db_session)
        ship = ship_repo.create(Ship(name="T", length_overall_m=100, breadth_m=20))
        voyage_repo = VoyageRepository(db_session)
        voyage = voyage_repo.create(Voyage(ship_id=ship.id, name="V1"))
        cond_repo = ConditionRepository(db_session)
        cond = LoadingCondition(voyage_id=voyage.id, name="C1", tank_volumes_m3={1: 50.0})
        cond_repo.create(cond)
        # Manually corrupt JSON in DB (bypass ORM)
        from senashipping_app.repositories.voyage_repository import LoadingConditionORM
        obj = db_session.get(LoadingConditionORM, cond.id)
        obj.tank_volumes_json = "not valid json"
        db_session.commit()
        # Reload should not crash
        loaded = cond_repo.get(cond.id)
        assert loaded.tank_volumes_m3 == {}
