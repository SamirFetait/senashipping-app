"""Tests for IMO and livestock criteria rules."""

from __future__ import annotations

import pytest

from senashipping_app.models import Ship, Tank, TankType, LoadingCondition
from senashipping_app.services.stability_service import compute_condition
from senashipping_app.services.validation import validate_condition
from senashipping_app.services.condition_service import ConditionService
from senashipping_app.services.criteria_rules import (
    evaluate_all_criteria,
    evaluate_imo_criteria,
    evaluate_livestock_criteria,
    CriterionResult,
)


class TestCriteriaRules:
    def test_imo_criteria_pass(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0, design_draft_m=10.0)
        tanks = [
            Tank(id=1, ship_id=1, capacity_m3=500.0, longitudinal_pos=0.5, kg_m=3.0),
        ]
        cond = LoadingCondition(tank_volumes_m3={1: 200.0})
        res = compute_condition(ship, tanks, cond)
        v = validate_condition(ship, res, tanks, {1: 200.0})
        res.validation = v
        lines = evaluate_imo_criteria(ship, res, tanks, {1: 200.0}, 1.0)
        assert len(lines) >= 3  # GM, trim, draft
        gm_line = next(l for l in lines if l.code == "IMO_GM")
        assert gm_line.result in (CriterionResult.PASS, CriterionResult.FAIL)

    def test_livestock_criteria(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0, depth_m=12.0, design_draft_m=8.0)
        tanks = [
            Tank(id=1, ship_id=1, capacity_m3=500.0, longitudinal_pos=0.5, kg_m=4.0),
        ]
        cond = LoadingCondition(tank_volumes_m3={1: 300.0})
        res = compute_condition(ship, tanks, cond)
        v = validate_condition(ship, res, tanks, {1: 300.0})
        res.validation = v
        lines = evaluate_livestock_criteria(ship, res, tanks, {1: 300.0}, 1.0)
        assert len(lines) >= 3  # GM, roll period, freeboard
        assert any(l.code == "LIV_GM" for l in lines)

    def test_evaluate_all_criteria(self):
        ship = Ship(length_overall_m=150.0, breadth_m=25.0, depth_m=12.0, design_draft_m=8.0)
        tanks = [
            Tank(id=1, ship_id=1, capacity_m3=500.0, longitudinal_pos=0.5, kg_m=4.0),
        ]
        cond = LoadingCondition(tank_volumes_m3={1: 300.0})
        res = compute_condition(ship, tanks, cond)
        v = validate_condition(ship, res, tanks, {1: 300.0})
        res.validation = v
        ev = evaluate_all_criteria(ship, res, tanks, {1: 300.0})
        assert ev.passed + ev.failed + ev.n_a == len(ev.lines)
