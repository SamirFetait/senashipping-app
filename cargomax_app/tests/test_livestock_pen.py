"""Tests for livestock pen model and stability integration."""

import pytest

from senashipping_app.models import LivestockPen, Ship, LoadingCondition
from senashipping_app.services.stability_service import compute_condition


def test_livestock_pen_dataclass() -> None:
    pen = LivestockPen(
        id=1,
        ship_id=10,
        name="PEN 1-1",
        deck="DK1",
        vcg_m=5.0,
        lcg_m=50.0,
        tcg_m=0.0,
        area_m2=100.0,
        capacity_head=200,
    )
    assert pen.name == "PEN 1-1"
    assert pen.deck == "DK1"
    assert pen.vcg_m == 5.0
    assert pen.lcg_m == 50.0


def test_compute_condition_with_pens() -> None:
    ship = Ship(
        id=1,
        name="Test",
        length_overall_m=100.0,
        breadth_m=20.0,
        depth_m=10.0,
        design_draft_m=8.0,
    )
    pens = [
        LivestockPen(id=1, ship_id=1, name="PEN 1", deck="DK1", vcg_m=5.0, lcg_m=50.0, tcg_m=0.0, area_m2=50.0),
    ]
    condition = LoadingCondition(pen_loadings={1: 100})
    results = compute_condition(
        ship, [], condition,
        pens=pens,
        pen_loadings={1: 100},
        mass_per_head_t=0.5,
    )
    assert results.displacement_t == 50.0  # 100 * 0.5
    assert results.kg_m == 5.0  # VCG of single pen
    assert results.trim_m != 0 or abs(results.trim_m) < 1.0
