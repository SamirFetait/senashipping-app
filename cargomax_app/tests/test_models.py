"""Tests for domain models."""

from __future__ import annotations

import pytest

from senashipping_app.models import Ship, Tank, TankType, Voyage, LoadingCondition


class TestShip:
    def test_ship_defaults(self):
        s = Ship()
        assert s.id is None
        assert s.name == ""
        assert s.length_overall_m == 0.0

    def test_ship_with_values(self):
        s = Ship(
            id=1,
            name="MV Test",
            imo_number="1234567",
            length_overall_m=100.0,
        )
        assert s.id == 1
        assert s.name == "MV Test"
        assert s.length_overall_m == 100.0


class TestTank:
    def test_tank_type_enum(self):
        assert TankType.CARGO != TankType.BALLAST
        assert TankType.FUEL.name == "FUEL"

    def test_tank_defaults(self):
        t = Tank()
        assert t.tank_type == TankType.CARGO
        assert t.capacity_m3 == 0.0
        assert t.longitudinal_pos == 0.5


class TestLoadingCondition:
    def test_condition_volumes(self):
        c = LoadingCondition(
            name="Arrival",
            tank_volumes_m3={1: 100.0, 2: 200.0},
        )
        assert c.tank_volumes_m3[1] == 100.0
        assert c.tank_volumes_m3[2] == 200.0

    def test_condition_empty_volumes(self):
        c = LoadingCondition()
        assert c.tank_volumes_m3 == {}


class TestVoyage:
    def test_voyage_defaults(self):
        v = Voyage()
        assert v.id is None
        assert v.name == ""
        assert v.conditions == []
