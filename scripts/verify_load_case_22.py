#!/usr/bin/env python3
"""
Verify app results for Load Case NO.22 against Maxsurf (Loading Manual pages 327-330).

Usage:
    python scripts/verify_load_case_22.py

Run from the project root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from senashipping_app.models import Ship, Tank, TankType, LoadingCondition, LivestockPen
from senashipping_app.services.stability_service import compute_condition
from senashipping_app.services.validation import validate_condition
from senashipping_app.reports.equilibrium_data import build_equilibrium_data
from senashipping_app.config.stability_manual_ref import (
    REF_LOA_M,
    REF_LIGHTSHIP_DISPLACEMENT_T,
)

FIXTURE_PATH = PROJECT_ROOT / "senashipping_app" / "tests" / "fixtures" / "load_case_22_items.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_from_fixture(fixture: dict):
    """Build ship, tanks, pens, condition from fixture."""
    ship = Ship(
        id=1,
        name="OSAMA BEY",
        length_overall_m=REF_LOA_M,
        breadth_m=19.40,
        depth_m=9.45,
        design_draft_m=7.60,
        lightship_draft_m=4.188,
        lightship_displacement_t=REF_LIGHTSHIP_DISPLACEMENT_T,
    )
    tanks = []
    tank_volumes = {}
    tank_cog_override = {}
    tank_fsm_mt = {}
    for i, t in enumerate(fixture["tanks"]):
        tid = i + 1
        mass = float(t["mass_t"])
        fill_pct = float(t.get("fill_pct", 100))
        volume = mass
        if 5 < fill_pct < 95:
            capacity = volume / (fill_pct / 100.0)
        else:
            capacity = volume + 0.01
        tank = Tank(
            id=tid,
            ship_id=1,
            name=t["name"],
            tank_type=TankType.CARGO,
            capacity_m3=capacity,
            longitudinal_pos=float(t["lcg_m"]) / REF_LOA_M,
            kg_m=float(t["vcg_m"]),
            tcg_m=float(t["tcg_m"]),
        )
        tanks.append(tank)
        tank_volumes[tid] = volume
        tank_cog_override[tid] = (float(t["vcg_m"]), float(t["lcg_m"]), float(t["tcg_m"]))
        fsm = t.get("fsm_mt", 0)
        if fsm and 5 < fill_pct < 95:
            tank_fsm_mt[tid] = float(fsm)
    pens = []
    pen_loadings = {}
    pen_mass_per_head = {}
    for i, p in enumerate(fixture["pens"]):
        pid = 100 + i + 1
        mass = float(p["mass_t"])
        pen = LivestockPen(
            id=pid,
            ship_id=1,
            name=p["name"],
            deck="DK1",
            vcg_m=float(p["vcg_m"]),
            lcg_m=float(p["lcg_m"]),
            tcg_m=float(p["tcg_m"]),
            area_m2=10.0,
            capacity_head=1,
        )
        pens.append(pen)
        pen_loadings[pid] = 1
        pen_mass_per_head[pid] = mass
    condition = LoadingCondition(
        id=1,
        voyage_id=1,
        name="Load Case NO.22",
        tank_volumes_m3=tank_volumes,
        pen_loadings=pen_loadings,
    )
    return ship, tanks, pens, condition, tank_cog_override, tank_fsm_mt, pen_loadings, pen_mass_per_head


def main() -> None:
    fixture = _load_fixture()
    ship, tanks, pens, condition, cog, fsm, _, pen_mass = _build_from_fixture(fixture)

    results = compute_condition(
        ship,
        tanks,
        condition,
        cargo_density_t_per_m3=1.0,
        pens=pens,
        pen_loadings=condition.pen_loadings,
        tank_cog_override=cog,
        pen_mass_per_head=pen_mass,
    )

    validation = validate_condition(
        ship,
        results,
        tanks,
        condition.tank_volumes_m3,
        1.0,
        fsm,
    )
    gm_eff = validation.gm_effective
    eq_data = build_equilibrium_data(ship, results, gm_eff)

    eq_dict = {}
    for row in eq_data:
        label1, val1, label2, val2 = row
        if label1:
            eq_dict[label1.strip()] = val1.strip() if val1 else ""
        if label2:
            eq_dict[label2.strip()] = val2.strip() if val2 else ""

    def _get_float(key: str) -> float:
        s = eq_dict.get(key, "")
        return float(s) if s else 0.0

    params = [
        ("Displacement t", _get_float("Displacement t"), fixture.get("expected_total_mass_t", 9712.66)),
        ("Draft Amidships m", _get_float("Draft Amidships m"), fixture.get("expected_draft_m", 7.113)),
        ("Trim (+ve by stern) m", _get_float("Trim (+ve by stern) m"), fixture.get("expected_trim_m", 1.239)),
        ("Draft at FP m", _get_float("Draft at FP m"), fixture.get("expected_draft_fwd_m", 6.493)),
        ("Draft at AP m", _get_float("Draft at AP m"), fixture.get("expected_draft_aft_m", 7.732)),
        ("KG fluid m", _get_float("KG fluid m"), fixture.get("expected_kg_fluid_m", 7.427)),
        ("GMt corrected m", _get_float("GMt corrected m"), fixture.get("expected_gm_eff_m", 0.973)),
        ("WL Length m", _get_float("WL Length m"), fixture.get("expected_wl_length_m", 117.064)),
        ("LCB from zero pt. (+ve fwd) m", _get_float("LCB from zero pt. (+ve fwd) m"), fixture.get("expected_lcb_m", 52.438)),
        ("LCF from zero pt. (+ve fwd) m", _get_float("LCF from zero pt. (+ve fwd) m"), fixture.get("expected_lcf_m", 48.362)),
        ("KB m", _get_float("KB m"), fixture.get("expected_kb_m", 4.009)),
        ("BMt m", _get_float("BMt m"), fixture.get("expected_bmt_m", 4.391)),
        ("BML m", _get_float("BML m"), fixture.get("expected_bml_m", 147.323)),
        ("Immersion (TPC) tonne/cm", _get_float("Immersion (TPC) tonne/cm"), fixture.get("expected_tpc", 17.780)),
        ("MTc tonne.m", _get_float("MTc tonne.m"), fixture.get("expected_mtc", 127.279)),
    ]

    print("Load Case NO.22 – App vs Maxsurf (Loading Manual p.330)")
    print("=" * 70)
    print(f"{'Parameter':<35} {'App':>12} {'Maxsurf':>12} {'Diff':>10}")
    print("-" * 70)
    for name, app_val, expected in params:
        diff = app_val - expected
        print(f"{name:<35} {app_val:>12.3f} {expected:>12.3f} {diff:>+10.3f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
