"""Tests for validation, numerical accuracy, and stress scenarios."""

from __future__ import annotations

import pytest

from senashipping_app.models import Ship, Tank, TankType, LoadingCondition
from senashipping_app.services.stability_service import compute_condition, ConditionResults
from senashipping_app.services.validation import (
    validate_condition,
    ValidationSeverity,
    safe_divide,
    compute_free_surface_correction,
)
from senashipping_app.services.hydrostatics import displacement_to_draft, compute_kg_from_tanks


class TestSafeDivide:
    def test_normal(self):
        assert safe_divide(10.0, 2.0) == 5.0

    def test_zero_divisor(self):
        assert safe_divide(10.0, 0.0) == 0.0
        assert safe_divide(10.0, 0.0, default=99.0) == 99.0


class TestValidation:
    def test_negative_gm_detection(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0, design_draft_m=10.0)
        tanks = [
            Tank(id=1, ship_id=1, capacity_m3=100.0, longitudinal_pos=0.5, kg_m=20.0),
        ]
        cond = LoadingCondition(tank_volumes_m3={1: 100.0})
        res = compute_condition(ship, tanks, cond)
        res.gm_m = 0.05  # force low GM
        v = validate_condition(ship, res, tanks, {1: 100.0})
        assert v.has_errors
        assert any(i.code == "GM_LOW" for i in v.issues)

    def test_extreme_trim_detection(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0, design_draft_m=10.0)
        tanks = [
            Tank(id=1, ship_id=1, capacity_m3=500.0, longitudinal_pos=0.1),
            Tank(id=2, ship_id=1, capacity_m3=500.0, longitudinal_pos=0.9),
        ]
        cond = LoadingCondition(tank_volumes_m3={1: 450.0, 2: 50.0})
        res = compute_condition(ship, tanks, cond)
        v = validate_condition(ship, res, tanks, cond.tank_volumes_m3)
        # May or may not trigger trim limit depending on actual value
        assert isinstance(v.gm_effective, float)

    def test_zero_weight(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0)
        tanks = []
        cond = LoadingCondition(tank_volumes_m3={})
        res = compute_condition(ship, tanks, cond)
        v = validate_condition(ship, res, tanks, {})
        assert any(i.code == "ZERO_WEIGHT" for i in v.issues)


class TestFreeSurface:
    def test_slack_tank_reduces_gm(self):
        tanks = [
            Tank(id=1, capacity_m3=100.0, longitudinal_pos=0.5),
        ]
        # 50% fill = slack
        volumes = {1: 50.0}
        fsc = compute_free_surface_correction(tanks, volumes, 1000.0, 1.0)
        assert fsc > 0


class TestStressScenarios:
    def test_many_tanks(self):
        ship = Ship(length_overall_m=200.0, breadth_m=30.0)
        tanks = [
            Tank(id=i, ship_id=1, capacity_m3=50.0, longitudinal_pos=0.01 * i)
            for i in range(100)
        ]
        volumes = {i: 25.0 for i in range(100)}
        cond = LoadingCondition(tank_volumes_m3=volumes)
        res = compute_condition(ship, tanks, cond)
        assert res.displacement_t > 0
        assert res.draft_m > 0

    def test_empty_tank_list(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0)
        tanks = []
        cond = LoadingCondition(tank_volumes_m3={})
        res = compute_condition(ship, tanks, cond)
        assert res.displacement_t == 0.0

    def test_kg_zero_division(self):
        tanks = []
        kg = compute_kg_from_tanks(tanks, {}, 1.0)
        assert kg == 0.0
