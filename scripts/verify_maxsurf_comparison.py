#!/usr/bin/env python3
"""
Spot-check equilibrium values against Maxsurf / Loading Manual reference.

Compares app output with expected values from a known condition.
Edit the EXPECTED dict below with values from your Maxsurf/PDF for a specific
loading condition, then run:

    python scripts/verify_maxsurf_comparison.py

Run from the project root. Uses the load_case_13 fixture by default.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from senashipping_app.services.stability_service import compute_condition
from senashipping_app.reports.equilibrium_data import build_equilibrium_data

# Import fixture builder from verify_equilibrium (add scripts to path)
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from verify_equilibrium import _load_fixture, _build_from_fixture

# Expected values from Maxsurf/PDF for this condition (edit to match your reference)
EXPECTED = {
    "displacement_t": 9606.6,
    "draft_amidships": 7.048,
    "trim_m": 1.332,
    "draft_fwd": 6.382,
    "draft_aft": 7.714,
    "gm_corrected": 1.021,
    "wl_length": 117.064,
    "lcb_m": 52.438,
    "lcf_m": 48.362,
    "kb_m": 4.009,
    "bmt_m": 4.391,
    "bml_m": 147.323,
    "tpc": 17.780,
    "mtc": 127.279,
}


def main() -> int:
    fixture = _load_fixture()
    ship, tanks, pens, condition, cog_override, fsm, pen_loadings, pen_mass = _build_from_fixture(fixture)
    results = compute_condition(
        ship, tanks, condition,
        tank_cog_override=cog_override,
        pens=pens,
        pen_loadings=pen_loadings,
        pen_mass_per_head=pen_mass,
    )
    eq_rows = build_equilibrium_data(ship, results, results.gm_m)
    eq_dict = {}
    for r1, v1, r2, v2 in eq_rows:
        if r1:
            try:
                eq_dict[r1] = float(v1) if v1 else None
            except (TypeError, ValueError):
                eq_dict[r1] = v1
        if r2:
            try:
                eq_dict[r2] = float(v2) if v2 else None
            except (TypeError, ValueError):
                eq_dict[r2] = v2

    label_map = {
        "displacement_t": "Displacement t",
        "draft_amidships": "Draft Amidships m",
        "trim_m": "Trim (+ve by stern) m",
        "draft_fwd": "Draft at FP m",
        "draft_aft": "Draft at AP m",
        "gm_corrected": "GMt corrected m",
        "wl_length": "WL Length m",
        "lcb_m": "LCB from zero pt. (+ve fwd) m",
        "lcf_m": "LCF from zero pt. (+ve fwd) m",
        "kb_m": "KB m",
        "bmt_m": "BMt m",
        "bml_m": "BML m",
        "tpc": "Immersion (TPC) tonne/cm",
        "mtc": "MTc tonne.m",
    }

    print("Maxsurf comparison (edit EXPECTED in script to match your reference)")
    print("=" * 70)
    print(f"{'Parameter':<35} {'App':>12} {'Expected':>12} {'Diff':>10}")
    print("-" * 70)
    for key, label in label_map.items():
        exp = EXPECTED.get(key)
        if exp is None:
            continue
        app_val = eq_dict.get(label)
        if app_val is None and hasattr(results, key):
            app_val = getattr(results, key, None)
        if app_val is None:
            continue
        try:
            app_f = float(app_val)
            diff = app_f - exp
            print(f"{label:<35} {app_f:>12.3f} {exp:>12.3f} {diff:>+10.3f}")
        except (TypeError, ValueError):
            print(f"{label:<35} {app_val!r:>12} {exp!r:>12}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
