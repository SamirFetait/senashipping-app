"""
Stability and loading calculations.

Uses hydrostatic and longitudinal strength modules for improved results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..models import Ship, Tank, LoadingCondition, LivestockPen

from .hydrostatics import (
    RHO_SEA,
    displacement_to_draft,
    compute_trim,
    compute_kb,
    compute_bm_t,
    compute_kg_from_tanks,
    compute_gm,
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
) -> ConditionResults:
    """
    Compute displacement, draft, trim, GM, and basic strength for a condition.

    Uses ship dimensions for hydrostatic estimates when available.
    Optionally includes livestock pen weights (Phase 2).
    """
    volumes: Dict[int, float] = condition.tank_volumes_m3
    loadings: Dict[int, int] = pen_loadings or getattr(condition, "pen_loadings", None) or {}
    pens_list = pens or []

    total_mass_t = 0.0
    total_lcg_moment = 0.0
    total_vcg_moment = 0.0
    total_tcg_moment = 0.0

    for tank in tanks:
        vol = volumes.get(tank.id or -1, 0.0)
        mass = vol * cargo_density_t_per_m3
        total_mass_t += mass
        total_lcg_moment += mass * tank.longitudinal_pos
        total_vcg_moment += mass * tank.kg_m  # VCG = KG for tanks
        total_tcg_moment += mass * tank.tcg_m

    pen_mass, pen_vcg, pen_lcg, pen_tcg = _pen_mass_and_moments(
        pens_list, loadings, mass_per_head_t, vcg_from_deck_m
    )
    total_mass_t += pen_mass
    L = max(1e-6, ship.length_overall_m)
    total_lcg_moment += pen_lcg / L  # pen_lcg in m, convert to 0-1 norm
    total_vcg_moment += pen_vcg
    total_tcg_moment += pen_tcg

    displacement_t = total_mass_t

    B = max(1e-6, ship.breadth_m)

    # Draft from displacement
    draft_m = displacement_to_draft(displacement_t, L, B)

    # Trim from LCG (normalized 0-1)
    if total_mass_t > 0:
        lcg_norm = total_lcg_moment / total_mass_t
    else:
        lcg_norm = 0.5
    trim_m = compute_trim(displacement_t, lcg_norm, L, B, draft_m)

    # KG = total VCG moment / total mass (tanks + pens)
    kg_m = total_vcg_moment / total_mass_t if total_mass_t > 1e-9 else 0.0

    # KB, BM, KM, GM
    kb_m = compute_kb(draft_m)
    bm_t = compute_bm_t(displacement_t, L, B)
    km_m = kb_m + bm_t
    gm_m = compute_gm(km_m, kg_m)

    # Longitudinal strength (tanks + pens)
    strength = compute_strength(
        displacement_t, L, tanks, volumes, cargo_density_t_per_m3,
        pens=pens_list,
        pen_loadings=loadings,
        mass_per_head=mass_per_head_t,
    )

    # Draft at marks (trim +ve = stern down)
    draft_aft_m = draft_m + trim_m / 2.0
    draft_fwd_m = draft_m - trim_m / 2.0

    # Heel from TCG (tanks + pens already in total_tcg_moment)
    tcg_m = total_tcg_moment / total_mass_t if total_mass_t > 1e-9 else 0.0
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
