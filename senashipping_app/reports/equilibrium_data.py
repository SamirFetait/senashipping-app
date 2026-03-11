"""
Shared equilibrium data builder for PDF and Excel reports.
Produces the 4-column layout (Label1, Value1, Label2, Value2) matching the Loading Manual.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from senashipping_app.config.stability_manual_ref import (
    CWP,
    GM_CORRECTION_FACTOR,
    HYDROSTATIC_CURVES_PATH,
    REF_BREADTH_M,
    REF_DESIGN_DRAFT_M,
    REF_LOA_M,
    TRIM_GM_CORRECTION_DISPLACEMENT_RANGE,
)
from senashipping_app.services.hydrostatic_curves import (
    build_curves_from_formulas,
    get_awp_at_draft,
    get_lcb_norm,
    get_lcf_norm,
    get_wl_length,
    load_curves_from_file,
)
from senashipping_app.services.hydrostatics import (
    RHO_SEA,
    get_bm_l_from_curves,
    get_bm_t_from_curves,
    get_kb_for_draft,
)

if TYPE_CHECKING:
    from senashipping_app.models import Ship
    from senashipping_app.services.stability_service import ConditionResults


def _fmt(value: object, fmt: str) -> str:
    """Safely format numeric values, falling back to string/blank."""
    if value is None:
        return ""
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return str(value)


def build_equilibrium_data(
    ship: "Ship",
    results: "ConditionResults",
    gm_eff: float | None,
) -> list[tuple[str, str, str, str]]:
    """
    Build equilibrium data rows for the 4-column table (Label1, Value1, Label2, Value2).
    Matches the layout from the Loading Manual EQUILIBRIUM DATA page.
    """
    L = float(getattr(ship, "length_overall_m", 0.0) or 0.0) or REF_LOA_M
    B = float(getattr(ship, "breadth_m", 0.0) or 0.0) or REF_BREADTH_M
    design_draft = max(0.0, float(getattr(ship, "design_draft_m", 0.0) or 0.0)) or REF_DESIGN_DRAFT_M

    disp = float(getattr(results, "displacement_t", 0.0) or 0.0)
    draft_m = float(getattr(results, "draft_m", 0.0) or 0.0)
    trim_m = float(getattr(results, "trim_m", 0.0) or 0.0)
    draft_aft = float(getattr(results, "draft_aft_m", 0.0) or 0.0)
    draft_fwd = float(getattr(results, "draft_fwd_m", 0.0) or 0.0)
    heel = float(getattr(results, "heel_deg", 0.0) or 0.0)
    kg_m = float(getattr(results, "kg_m", 0.0) or 0.0)
    km_m = float(getattr(results, "km_m", 0.0) or 0.0)
    gm_raw = float(getattr(results, "gm_m", 0.0) or 0.0)
    gm_eff_actual = float(gm_eff) if gm_eff is not None else gm_raw
    gm_corr = gm_eff_actual
    if GM_CORRECTION_FACTOR is not None and gm_corr > 0:
        disp = float(getattr(results, "displacement_t", 0.0) or 0.0)
        lo, hi = TRIM_GM_CORRECTION_DISPLACEMENT_RANGE
        if lo <= disp <= hi:
            gm_corr *= GM_CORRECTION_FACTOR
    # KG fluid = KG + GG' (virtual KG after FSM). Use actual gm_eff for fsc, not corrected.
    fsc = max(0.0, gm_raw - gm_eff_actual) if gm_eff is not None else 0.0
    kg_fluid = kg_m + fsc

    # Use vessel hydrostatics when available (has separate LCB/LCF); else formula-based.
    # For Excel trim sheets, use the trim from the condition so the equilibrium table matches.
    trim_for_curves = float(getattr(results, "trim_for_hydrostatics_m", 0.0) or 0.0)
    if trim_for_curves == 0.0:
        trim_for_curves = trim_m
    curves = None
    if L > 0 and B > 0:
        if HYDROSTATIC_CURVES_PATH:
            from pathlib import Path
            base = Path(__file__).resolve().parents[2]
            curves = load_curves_from_file(HYDROSTATIC_CURVES_PATH, base, trim_m=trim_for_curves)
        if not curves or not curves.is_valid():
            curves = build_curves_from_formulas(L, B, design_draft)
    kb_m = get_kb_for_draft(draft_m, curves) if draft_m > 0 else 0.0
    _wl = get_wl_length(draft_m, curves) if curves and curves.is_valid() else None
    wl_length = float(_wl) if _wl is not None and _wl > 0 else L
    _lcb = get_lcb_norm(draft_m, curves) if curves and curves.is_valid() else None
    lcb_norm = float(_lcb) if _lcb is not None else 0.5
    # LCB/LCF in m from AP; lcb_norm is 0..1 along LOA, so lcb_m = lcb_norm * L
    lcb_m = lcb_norm * L
    _lcf = get_lcf_norm(draft_m, curves) if curves and curves.is_valid() else None
    lcf_m = float(_lcf) * L if _lcf is not None else lcb_m
    # PDF p.11: dm = (dA + dF) / 2 (draft amidships). draft_m from solver = draft at LCF.
    draft_amidships = (draft_aft + draft_fwd) / 2.0 if (draft_aft or draft_fwd) else draft_m
    draft_lcf = draft_m  # Mean draft at LCF (solver output)

    bm_t = get_bm_t_from_curves(disp, draft_m, L, B, RHO_SEA, curves) if disp > 0 else 0.0
    bm_l = get_bm_l_from_curves(disp, draft_m, L, B, RHO_SEA, curves) if disp > 0 else 0.0
    km_l = kb_m + bm_l if bm_l > 0 else 0.0
    gml = km_l - kg_m if km_l > 0 and kg_m > 0 else 0.0

    # Use Awp from curves when available; else formula. TPC/MTC use WL length (Maxsurf).
    _awp = get_awp_at_draft(draft_m, curves) if curves and curves.is_valid() else None
    awp = float(_awp) if _awp is not None and _awp > 0 else (L * B * CWP if L > 0 and B > 0 else 0.0)
    tpc = awp * RHO_SEA / 100.0 if awp > 0 else 0.0
    mtc = disp * bm_l / (wl_length * 100.0) if wl_length > 0 and bm_l > 0 and disp > 0 else 0.0

    cb = disp / (L * B * draft_m * RHO_SEA) if L > 0 and B > 0 and draft_m > 0 and RHO_SEA > 0 else 0.0
    cm = 0.89  # Typical max sectional area coefficient
    cp = cb / cm if cm > 0 else 0.0
    cwp = CWP

    rm_1deg = gm_corr * disp * math.sin(math.radians(1.0)) if gm_corr > 0 and disp > 0 else 0.0
    trim_angle_deg = math.degrees(math.atan(trim_m / L)) if L > 0 else 0.0
    # Holtrop-style: S = L × (1.7×T + B×Cb) — better match to Maxsurf than L×(2T+B)×0.9
    if wl_length > 0 and B > 0 and draft_m > 0:
        cb_eff = cb if cb > 0 else 0.58  # typical for merchant hulls when Cb not available
        wetted_area = wl_length * (1.7 * draft_m + B * cb_eff)
    else:
        wetted_area = 0.0

    return [
        ("", "", "", ""),
        ("Draft Amidships m", _fmt(draft_amidships, ".3f"), "LCB from zero pt. (+ve fwd) m", _fmt(lcb_m, ".3f")),
        ("Displacement t", _fmt(disp, ".0f"), "LCF from zero pt. (+ve fwd) m", _fmt(lcf_m, ".3f")),
        ("Heel deg", _fmt(heel, ".1f"), "KB m", _fmt(kb_m, ".3f")),
        ("Draft at FP m", _fmt(draft_fwd, ".3f"), "KG fluid m", _fmt(kg_fluid, ".3f")),
        ("Draft at AP m", _fmt(draft_aft, ".3f"), "BMt m", _fmt(bm_t, ".3f")),
        ("Draft at LCF m", _fmt(draft_lcf, ".3f"), "BML m", _fmt(bm_l, ".3f")),
        ("Trim (+ve by stern) m", _fmt(trim_m, ".3f"), "GMt corrected m", _fmt(gm_corr, ".3f")),
        ("WL Length m", _fmt(wl_length, ".3f"), "GML m", _fmt(gml, ".3f")),
        ("Beam max extents on WL m", _fmt(B, ".3f"), "KMt m", _fmt(km_m, ".3f")),
        ("Wetted Area m²", _fmt(wetted_area, ".3f"), "KML m", _fmt(km_l, ".3f")),
        ("Waterpl. Area m²", _fmt(awp, ".3f"), "Immersion (TPC) tonne/cm", _fmt(tpc, ".3f")),
        ("Prismatic coeff. (Cp)", _fmt(cp, ".3f"), "MTc tonne.m", _fmt(mtc, ".3f")),
        ("Block coeff. (Cb)", _fmt(cb, ".3f"), "RM at 1deg = GMt.Disp.sin(1) \n tonne.m", _fmt(rm_1deg, ".3f")),
        ("Max Sect. area coeff. (Cm)", _fmt(cm, ".3f"), "Max deck inclination deg", _fmt(trim_angle_deg, ".4f")),
        ("Waterpl. area coeff. (Cwp)", _fmt(cwp, ".3f"), "Trim angle (+ve by stern) deg", _fmt(trim_angle_deg, ".4f")),
    ]
