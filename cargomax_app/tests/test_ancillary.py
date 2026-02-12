"""Tests for Phase 3 ancillary calculations."""

import pytest

from senashipping_app.models import Ship
from senashipping_app.services.ancillary_calculations import (
    compute_ancillary,
    compute_prop_immersion_pct,
    compute_visibility_m,
    compute_air_draft_m,
)


def test_prop_immersion() -> None:
    # Draft aft 6m, prop center 0.5m, diam 3m => immersion 5.5m => 183% capped to 100
    pct = compute_prop_immersion_pct(6.0, 100.0, 10.0, 0.5, 3.0)
    assert 90 <= pct <= 100
    # Low draft
    pct2 = compute_prop_immersion_pct(0.5, 100.0, 10.0, 0.5, 3.0)
    assert pct2 == 0.0


def test_air_draft() -> None:
    air = compute_air_draft_m(10.0, 6.0, 18.0)
    assert air == 12.0  # 18 - 6
    air2 = compute_air_draft_m(10.0, 20.0)  # draft > mast, uses default
    assert air2 >= 0


def test_compute_ancillary() -> None:
    ship = Ship(length_overall_m=100.0, breadth_m=20.0, depth_m=10.0)
    anc = compute_ancillary(
        ship,
        draft_m=6.0,
        draft_aft_m=6.5,
        draft_fwd_m=5.5,
        trim_m=1.0,
        gm_m=0.5,
        heel_deg=1.0,
    )
    assert anc.prop_immersion_pct >= 0
    assert anc.visibility_m >= 0
    assert anc.air_draft_m >= 0
    assert anc.gz_criteria_ok is True
