"""Tests for repositories."""

from __future__ import annotations

import pytest

from senashipping_app.models import Ship, Tank, TankType, Voyage, LoadingCondition
from senashipping_app.repositories.ship_repository import ShipRepository
from senashipping_app.repositories.tank_repository import TankRepository
from senashipping_app.repositories.voyage_repository import VoyageRepository, ConditionRepository


class TestShipRepository:
    def test_create_and_get(self, db_session, sample_ship):
        repo = ShipRepository(db_session)
        created = repo.create(sample_ship)
        assert created.id is not None

        fetched = repo.get(created.id)
        assert fetched is not None
        assert fetched.name == sample_ship.name

    def test_list_empty(self, db_session):
        repo = ShipRepository(db_session)
        ships = repo.list()
        assert ships == []


class TestTankRepository:
    def test_create_and_list_for_ship(self, db_session, sample_ship):
        ship_repo = ShipRepository(db_session)
        ship = ship_repo.create(sample_ship)

        tank = Tank(ship_id=ship.id, name="T1", tank_type=TankType.CARGO, capacity_m3=100.0)
        tank_repo = TankRepository(db_session)
        tank_repo.create(tank)

        tanks = tank_repo.list_for_ship(ship.id)
        assert len(tanks) == 1
        assert tanks[0].name == "T1"


class TestVoyageRepository:
    def test_create_voyage(self, db_session, sample_ship):
        ship_repo = ShipRepository(db_session)
        ship = ship_repo.create(sample_ship)

        voyage = Voyage(ship_id=ship.id, name="V1", departure_port="A", arrival_port="B")
        voyage_repo = VoyageRepository(db_session)
        voyage_repo.create(voyage)
        assert voyage.id is not None
