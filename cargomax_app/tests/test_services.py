"""Tests for services (stability, hydrostatics, ship, condition)."""

from __future__ import annotations

import pytest

from senashipping_app.models import Ship, Tank, TankType, LoadingCondition
from senashipping_app.services.stability_service import compute_condition, ConditionResults
from senashipping_app.services.hydrostatics import (
    displacement_to_draft,
    draft_to_displacement,
    compute_trim,
    compute_kb,
    compute_bm_t,
)
from senashipping_app.services.longitudinal_strength import compute_strength
from senashipping_app.services.ship_service import ShipService, ShipValidationError
from senashipping_app.repositories.ship_repository import ShipRepository


class TestHydrostatics:
    def test_displacement_to_draft(self):
        d = displacement_to_draft(10000.0, 150.0, 25.0)
        assert d > 0
        assert d < 30.0

    def test_draft_to_displacement_roundtrip(self):
        disp = 8000.0
        draft = displacement_to_draft(disp, 150.0, 25.0)
        disp2 = draft_to_displacement(draft, 150.0, 25.0)
        assert abs(disp - disp2) < 10.0

    def test_compute_kb(self):
        kb = compute_kb(10.0)
        assert 4.0 < kb < 6.0

    def test_compute_bm_t(self):
        bm = compute_bm_t(10000.0, 150.0, 25.0)
        assert bm > 0


class TestStabilityService:
    def test_compute_condition_empty(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0)
        tanks = []
        cond = LoadingCondition(tank_volumes_m3={})
        res = compute_condition(ship, tanks, cond)
        assert res.displacement_t == 0.0
        assert res.draft_m == 0.0
        assert res.gm_m >= 0.0

    def test_compute_condition_with_load(self, sample_tanks, sample_condition):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0)
        res = compute_condition(ship, sample_tanks, sample_condition, cargo_density_t_per_m3=1.0)
        assert res.displacement_t == 500.0  # 250 + 250
        assert res.draft_m > 0
        assert res.gm_m > 0
        assert hasattr(res, "strength")


class TestLongitudinalStrength:
    def test_compute_strength_empty(self):
        res = compute_strength(10000.0, 150.0, [], {})
        assert res.still_water_bm_approx_tm == 0.0

    def test_compute_strength_with_tanks(self, sample_tanks):
        volumes = {1: 250.0, 2: 250.0}
        res = compute_strength(500.0, 150.0, sample_tanks, volumes)
        assert res.still_water_bm_approx_tm >= 0.0


class TestShipService:
    def test_save_ship_validation_empty_name(self, db_session, sample_ship):
        svc = ShipService(db_session)
        sample_ship.name = ""
        with pytest.raises(ShipValidationError):
            svc.save_ship(sample_ship)

    def test_save_ship_validation_zero_length(self, db_session, sample_ship):
        svc = ShipService(db_session)
        sample_ship.length_overall_m = 0.0
        with pytest.raises(ShipValidationError):
            svc.save_ship(sample_ship)
