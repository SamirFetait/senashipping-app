#!/usr/bin/env python3
"""
Full equilibrium data verification against Loading Manual PDF (cattle 300kg).
Compares every value from app output vs PDF reference.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from senashipping_app.models import Ship, Tank, TankType, LoadingCondition, LivestockPen
from senashipping_app.services.stability_service import compute_condition
from senashipping_app.services.validation import validate_condition
from senashipping_app.reports.equilibrium_data import build_equilibrium_data
from senashipping_app.config.stability_manual_ref import (
    REF_LOA_M,
    REF_LIGHTSHIP_DISPLACEMENT_T,
)

# PDF reference values from cattle 300kg.pdf EQUILIBRIUM DATA (user's screenshot)
PDF_REF = {
    "Draft Amidships m": 6.903,
    "Displacement t": 9603,
    "Heel deg": 0.2,
    "Draft at FP m": 5.602,
    "Draft at AP m": 8.204,
    "Draft at LCF m": 7.114,
    "Trim (+ve by stern) m": 2.602,
    "WL Length m": 118.020,
    "Beam max extents on WL m": 19.400,
    "Wetted Area m²": 3571.861,
    "Waterpl. Area m²": 1774.431,
    "Prismatic coeff. (Cp)": 0.646,
    "Block coeff. (Cb)": 0.575,
    "Max Sect. area coeff. (Cm)": 0.890,
    "Waterpl. area coeff. (Cwp)": 0.775,
    "LCB from zero pt. (+ve fwd) m": 54.155,
    "LCF from zero pt. (+ve fwd) m": 49.441,
    "KB m": 3.971,
    "KG fluid m": 7.356,
    "BMt m": 4.701,
    "BML m": 171.119,
    "GMt corrected m": 1.151,
    "GML m": 167.769,
    "KMt m": 8.641,
    "KML m": 175.090,
    "Immersion (TPC) tonne/cm": 18.188,
    "MTc tonne.m": 139.241,
    "RM at 1deg = GMt.Disp.sin(1) tonne.m": 92.955,
    "Max deck inclination deg": 1.2631,
    "Trim angle (+ve by stern) deg": 1.2631,
}

FIXTURE_PATH = PROJECT_ROOT / "senashipping_app" / "tests" / "fixtures" / "load_case_13_items.json"


def _load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_from_fixture(fixture):
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
        capacity = volume / (fill_pct / 100) if 5 < fill_pct < 95 else volume + 0.01
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
        if t.get("fsm_mt") and 5 < fill_pct < 95:
            tank_fsm_mt[tid] = float(t["fsm_mt"])

    pens = []
    pen_loadings = {}
    pen_mass_per_head = {}
    for i, p in enumerate(fixture["pens"]):
        pid = 100 + i + 1
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
        pen_mass_per_head[pid] = float(p["mass_t"])

    condition = LoadingCondition(
        id=1,
        voyage_id=1,
        name="Load Case NO.13",
        tank_volumes_m3=tank_volumes,
        pen_loadings=pen_loadings,
    )
    return ship, tanks, pens, condition, tank_cog_override, tank_fsm_mt, pen_loadings, pen_mass_per_head


def main():
    fixture = _load_fixture()
    ship, tanks, pens, condition, cog, fsm, _, pen_mass = _build_from_fixture(fixture)

    res = compute_condition(
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
        ship, res, tanks, condition.tank_volumes_m3, 1.0, fsm
    )
    eq_data = build_equilibrium_data(ship, res, validation.gm_effective)

    eq_dict = {}
    for row in eq_data:
        label1, val1, label2, val2 = row
        if label1:
            eq_dict[label1.strip()] = val1.strip() if val1 else ""
        if label2:
            eq_dict[label2.strip()] = val2.strip() if val2 else ""

    def get_float(key):
        s = eq_dict.get(key, "")
        try:
            return float(s) if s else None
        except ValueError:
            return None

    print("EQUILIBRIUM DATA – Full verification vs PDF (cattle 300kg)")
    print("=" * 90)
    print(f"{'Parameter':<42} {'App':>12} {'PDF':>12} {'Diff':>10} {'Status':>8}")
    print("-" * 90)

    ok_count = 0
    tol_draft = 0.15
    tol_small = 0.01
    tol_med = 0.1
    tol_large = 1.0
    tol_pct = 0.02  # 2% for coefficients

    for key, pdf_val in PDF_REF.items():
        app_val = get_float(key)
        if app_val is None:
            status = "N/A"
        else:
            diff = app_val - pdf_val
            if "deg" in key and "inclination" in key or "Trim angle" in key:
                tol = 0.05
            elif "Draft" in key or "Trim" in key:
                tol = tol_draft
            elif "Displacement" in key:
                tol = 10
            elif "BML" in key or "GML" in key or "KML" in key:
                tol = 1.0
            elif "MTc" in key or "TPC" in key:
                tol = 1.0
            elif "LCB" in key or "LCF" in key:
                tol = 0.5
            elif "KB" in key or "KG" in key or "BMt" in key or "KMt" in key or "GMt" in key:
                tol = 0.05
            elif "RM at" in key:
                tol = 5.0
            elif "Area" in key or "Wetted" in key:
                tol = tol_large
            elif "coeff" in key:
                tol = max(0.01, abs(pdf_val) * tol_pct)
            else:
                tol = tol_med

            status = "OK" if abs(diff) <= tol else "CHECK"
            if status == "OK":
                ok_count += 1

        diff_str = f"{app_val - pdf_val:+.3f}" if app_val is not None else "—"
        app_str = f"{app_val:.3f}" if app_val is not None else "—"
        print(f"{key:<42} {app_str:>12} {pdf_val:>12.3f} {diff_str:>10} {status:>8}")

    print("=" * 90)
    print(f"Match: {ok_count}/{len(PDF_REF)} parameters within tolerance")


if __name__ == "__main__":
    main()
