"""
Stability and loading calculations.

Uses hydrostatic and longitudinal strength modules for improved results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import Ship, Tank, LoadingCondition, LivestockPen

from .hydrostatics import (
    RHO_SEA,
    DEFAULT_CB,
    compute_kg_from_tanks,
    compute_gm,
    solve_draft_from_displacement,
    get_kb_for_draft,
    get_bm_t_from_curves,
    get_bm_l_from_curves,
)
from .hydrostatic_curves import build_curves_from_formulas, HydrostaticCurves
from ..config.stability_manual_ref import (
    REF_LOA_M,
    REF_BREADTH_M,
    REF_DEPTH_M,
    REF_DESIGN_DRAFT_M,
    REF_LIGHTSHIP_DISPLACEMENT_T,
    REF_LIGHTSHIP_KG_M,
    REF_LIGHTSHIP_LCG_NORM,
    REF_LIGHTSHIP_TCG_M,
)
from .longitudinal_strength import compute_strength, StrengthResult
from .ancillary_calculations import compute_ancillary, AncillaryResults


@dataclass(slots=True)
class ConditionResults:
    displacement_t: float
    draft_m: float
    trim_m: float
    gm_m: float
    kg_m: float = 0.0
    km_m: float = 0.0
    draft_aft_m: float = 0.0
    draft_fwd_m: float = 0.0
    heel_deg: float = 0.0
    strength: StrengthResult = field(default_factory=lambda: StrengthResult(0.0, 0.0, 0.0))
    ancillary: AncillaryResults | None = None  # Phase 3: prop, visibility, air draft, GZ
    validation: object = None  # ValidationResult from validation.validate_condition
    criteria: object = None  # CriteriaEvaluation from criteria_rules.evaluate_all_criteria
    snapshot: object = None  # CalculationSnapshot from traceability.create_snapshot


def _pen_mass_and_moments(
    pens: List[LivestockPen],
    pen_loadings: Dict[int, int],
    mass_per_head_t: float,
    vcg_from_deck_m: float = 0.0,
) -> tuple[float, float, float, float]:
    """Return (total_mass, vcg_moment, lcg_moment_norm, tcg_moment).
    Cargo VCG = pen.vcg_m (deck) + vcg_from_deck_m (CoG above deck from cargo type).
    """
    total = 0.0
    vcg_mom = 0.0
    lcg_mom = 0.0
    tcg_mom = 0.0
    cargo_vcg_offset = vcg_from_deck_m
    for pen in pens:
        heads = pen_loadings.get(pen.id or -1, 0)
        if heads <= 0:
            continue
        mass = heads * mass_per_head_t
        total += mass
        vcg_mom += mass * (pen.vcg_m + cargo_vcg_offset)
        lcg_mom += mass * pen.lcg_m  # will divide by L for norm
        tcg_mom += mass * pen.tcg_m
    return total, vcg_mom, lcg_mom, tcg_mom


def compute_condition(
    ship: Ship,
    tanks: List[Tank],
    condition: LoadingCondition,
    cargo_density_t_per_m3: float = 1.0,
    pens: List[LivestockPen] | None = None,
    pen_loadings: Dict[int, int] | None = None,
    mass_per_head_t: float = 0.5,
    vcg_from_deck_m: float = 0.0,
    tank_cog_override: Optional[Dict[int, Tuple[float, float, float]]] = None,
) -> ConditionResults:
    """
    Compute displacement, draft, trim, GM, and basic strength for a condition.

    Uses ship dimensions for hydrostatic estimates when available.
    Optionally includes livestock pen weights (Phase 2).
    If tank_cog_override is set (tank_id -> (vcg_m, lcg_m, tcg_m)), those CoG values
    are used for tank moments instead of tank.kg_m / longitudinal_pos / tcg_m.
    """
    volumes: Dict[int, float] = condition.tank_volumes_m3
    loadings: Dict[int, int] = pen_loadings or getattr(condition, "pen_loadings", None) or {}
    pens_list = pens or []

    # Use ship dimensions from DB when available, otherwise fall back to
    # the Loading Manual reference values from stability_manual_ref.
    L = getattr(ship, "length_overall_m", 0.0) or REF_LOA_M
    L = max(1e-6, L)

    # Lightship (empty ship) mass and CoG – always included so displacement/KG/LCG/heel are correct
    lightship_mass_t = max(0.0, getattr(ship, "lightship_displacement_t", 0.0)) or REF_LIGHTSHIP_DISPLACEMENT_T
    total_mass_t = lightship_mass_t
    total_lcg_moment = lightship_mass_t * REF_LIGHTSHIP_LCG_NORM
    total_vcg_moment = lightship_mass_t * REF_LIGHTSHIP_KG_M
    total_tcg_moment = lightship_mass_t * REF_LIGHTSHIP_TCG_M

    override = tank_cog_override or {}
    for tank in tanks:
        vol = volumes.get(tank.id or -1, 0.0)
        mass = vol * cargo_density_t_per_m3
        total_mass_t += mass
        tid = tank.id or -1
        if tid in override:
            vcg_m, lcg_m, tcg_m = override[tid]
            total_lcg_moment += mass * (lcg_m / L)
            total_vcg_moment += mass * vcg_m
            total_tcg_moment += mass * tcg_m
        else:
            # longitudinal_pos is 0–1; if stored as metres (e.g. when ship length was 0), convert
            pos = tank.longitudinal_pos
            if pos > 1.5:
                pos = pos / L
            pos = max(0.0, min(1.0, pos))
            total_lcg_moment += mass * pos
            total_vcg_moment += mass * tank.kg_m  # VCG = KG for tanks
            total_tcg_moment += mass * tank.tcg_m

    pen_mass, pen_vcg, pen_lcg, pen_tcg = _pen_mass_and_moments(
        pens_list, loadings, mass_per_head_t, vcg_from_deck_m
    )
    total_mass_t += pen_mass
    total_lcg_moment += pen_lcg / L  # pen_lcg in m, convert to 0-1 norm
    total_vcg_moment += pen_vcg
    total_tcg_moment += pen_tcg

    # Total displacement = lightship + tanks + pens (already in total_mass_t)
    displacement_t = total_mass_t

    B = getattr(ship, "breadth_m", 0.0) or REF_BREADTH_M
    B = max(1e-6, B)
    design_draft = max(0.0, getattr(ship, "design_draft_m", 0.0)) or REF_DESIGN_DRAFT_M

    # Hydrostatic curves: formula-based when no table loaded (Path B)
    curves: HydrostaticCurves | None = build_curves_from_formulas(
        L, B, design_draft, cb=DEFAULT_CB, rho=RHO_SEA
    )

    # Draft and trim from iterative solver (lightship + tanks + pens).
    # We clamp LCG to [0,1] to avoid pathological inputs (e.g. tank positions saved in metres).
    lcg_norm = total_lcg_moment / total_mass_t
    lcg_norm = max(0.001, min(0.999, float(lcg_norm)))
    draft_m, trim_m = solve_draft_from_displacement(
        displacement_t, L, B, lcg_norm, RHO_SEA, DEFAULT_CB, curves
    )

    # KG = total VCG moment / total mass (lightship + tanks + pens)
    kg_m = total_vcg_moment / total_mass_t

    # KB, BM, KM, GM (from curves when available)
    kb_m = get_kb_for_draft(draft_m, curves)
    bm_t = get_bm_t_from_curves(displacement_t, draft_m, L, B, RHO_SEA, curves)
    km_m = kb_m + bm_t
    gm_m = compute_gm(km_m, kg_m)

    # Longitudinal strength (lightship + tanks + pens)
    strength = compute_strength(
        displacement_t, L, tanks, volumes, cargo_density_t_per_m3,
        pens=pens_list,
        pen_loadings=loadings,
        mass_per_head=mass_per_head_t,
        tank_cog_override=override,
        lightship_mass_t=lightship_mass_t,
        lightship_lcg_norm=REF_LIGHTSHIP_LCG_NORM,
    )

    # Draft at marks (trim +ve = stern down); clamp trim/drafts so they stay physical.
    # Realistic trim for this size ship is a few metres at most; using a very small
    # limit avoids extreme bow-down cases that were driving aft draft to 0.
    max_trim_m = max(1.0, min(L * 0.03, design_draft * 0.5))
    trim_m = max(-max_trim_m, min(max_trim_m, trim_m))
    draft_aft_m = draft_m + trim_m / 2.0
    draft_fwd_m = draft_m - trim_m / 2.0
    draft_min = 0.0
    draft_max = max(design_draft * 1.10, design_draft + 1.0)
    draft_aft_m = max(draft_min, min(draft_max, draft_aft_m))
    draft_fwd_m = max(draft_min, min(draft_max, draft_fwd_m))
    # Keep mean draft and trim consistent with clamped marks
    draft_m = (draft_aft_m + draft_fwd_m) / 2.0
    trim_m = draft_aft_m - draft_fwd_m

    # Heel from TCG (lightship + tanks + pens)
    tcg_m = total_tcg_moment / total_mass_t
    import math
    heel_deg = math.degrees(math.atan(tcg_m / gm_m)) if gm_m > 1e-9 else 0.0

    ancillary = compute_ancillary(
        ship, draft_m, draft_aft_m, draft_fwd_m, trim_m, gm_m, heel_deg
    )

    return ConditionResults(
        displacement_t=displacement_t,
        draft_m=draft_m,
        draft_aft_m=draft_aft_m,
        draft_fwd_m=draft_fwd_m,
        trim_m=trim_m,
        gm_m=gm_m,
        kg_m=kg_m,
        km_m=km_m,
        heel_deg=heel_deg,
        strength=strength,
        ancillary=ancillary,
    )
