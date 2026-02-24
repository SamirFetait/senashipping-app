"""
Hydrostatic calculations.

Uses ship principal dimensions and simplified formulas when full
hydrostatic tables are not available. Draft/trim formulas align with
vessel Loading Manual (assets/stability.pdf): t = Disp*(LCB-LCG)/MT1*100,
GM = KM - KG - GG'. Includes numerical safeguards against division-by-zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from ..models import Ship, Tank

from .hydrostatic_curves import (
    HydrostaticCurves,
    interpolate_draft_from_displacement as _curve_draft_from_disp,
    get_kb as _curve_kb,
    get_lcb_norm as _curve_lcb,
    get_i_t_i_l as _curve_i_t_i_l,
)

# Seawater density t/m³ (manual p.9: 1.025)
RHO_SEA = 1.025

# Floating-point tolerance for safe divisions
EPS = 1e-9


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Avoid zero divisions."""
    if abs(b) < EPS:
        return default
    return a / b

# Typical block coefficient for this vessel (OSAMA BEY).
# From stability manual hydrostatics at design draft:
#   Draft T = 7.60 m, Disp ≈ 10451 t, LBP = 110.04 m, B = 19.40 m, ρ = 1.025 t/m³
#   Cb = Disp / (ρ * LBP * B * T) ≈ 0.63
DEFAULT_CB = 0.63


@dataclass(slots=True)
class HydrostaticInput:
    """Input data for hydrostatic calculations."""
    length_m: float
    breadth_m: float
    displacement_t: float
    lcg_norm: float  # 0..1, 0.5 = amidships
    total_mass_t: float


@dataclass(slots=True)
class HydrostaticResult:
    """Result of hydrostatic calculation."""
    draft_m: float
    trim_by_stern_m: float  # positive = stern down
    lcb_norm: float
    kb_m: float
    bm_l_m: float  # longitudinal BM
    bm_t_m: float  # transverse BM
    mtc_tm_per_m: float  # moment to change trim 1 m


def displacement_to_draft(
    displacement_t: float,
    length_m: float,
    breadth_m: float,
    cb: float = DEFAULT_CB,
    rho: float = RHO_SEA,
) -> float:
    """
    Estimate mean draft from displacement using box approximation.

    disp = L * B * T * Cb * rho  =>  T = disp / (L * B * Cb * rho)
    """
    if length_m <= 0 or breadth_m <= 0 or cb <= 0 or rho <= 0:
        return 0.0
    if displacement_t < 0:
        return 0.0
    denom = length_m * breadth_m * cb * rho
    return _safe_div(displacement_t, denom, 0.0)


def draft_to_displacement(
    draft_m: float,
    length_m: float,
    breadth_m: float,
    cb: float = DEFAULT_CB,
    rho: float = RHO_SEA,
) -> float:
    """Estimate displacement from mean draft."""
    if length_m <= 0 or breadth_m <= 0 or cb <= 0:
        return 0.0
    vol_m3 = length_m * breadth_m * draft_m * cb
    return vol_m3 * rho


def compute_trim(
    displacement_t: float,
    lcg_norm: float,
    length_m: float,
    breadth_m: float,
    draft_m: float,
    lcb_norm: float = 0.5,
) -> float:
    """
    Approximate trim (m, positive = stern down) from LCG vs LCB.

    trim ≈ (LCG - LCB) * disp / MTC
    MTC uses longitudinal BM (I_L = B*L³/12), not transverse.
    """
    if displacement_t <= 0 or length_m <= 0:
        return 0.0
    # Longitudinal BM for trim: I_L = B*L³/12, BM_L = I_L/V
    bm_l = compute_bm_l(displacement_t, length_m, breadth_m, RHO_SEA)
    if bm_l <= 0:
        return 0.0
    # MTC in tm/m (moment to change trim 1 m)
    mtc = displacement_t * bm_l / (length_m * 100)
    if mtc <= 0:
        return 0.0
    lcg_m = lcg_norm * length_m
    lcb_m = lcb_norm * length_m
    trim_m = (lcg_m - lcb_m) * displacement_t / mtc
    return trim_m


def compute_kb(draft_m: float) -> float:
    """Approximate KB (center of buoyancy above keel)."""
    return 0.53 * draft_m  # typical for ship forms


def compute_bm_t(
    displacement_t: float,
    length_m: float,
    breadth_m: float,
    rho: float = RHO_SEA,
) -> float:
    """Transverse BM = I_T / V. I_T = L * B³/12 for rectangular WP."""
    if displacement_t <= 0:
        return 0.0
    v = displacement_t / rho
    i_t = length_m * (breadth_m ** 3) / 12
    return i_t / v


def compute_bm_l(
    displacement_t: float,
    length_m: float,
    breadth_m: float,
    rho: float = RHO_SEA,
) -> float:
    """Longitudinal BM = I_L / V."""
    if displacement_t <= 0:
        return 0.0
    v = displacement_t / rho
    i_l = breadth_m * (length_m ** 3) / 12
    return i_l / v


def compute_kg_from_tanks(
    tanks: List[Tank],
    volumes: dict,
    cargo_density: float,
) -> float:
    """Compute vertical center of gravity from tank loadings."""
    total_moment = 0.0
    total_mass = 0.0
    for tank in tanks:
        vol = max(0.0, volumes.get(tank.id or -1, 0.0))
        mass = vol * cargo_density
        total_mass += mass
        total_moment += mass * tank.kg_m
    return _safe_div(total_moment, total_mass, 0.0)


def compute_gm(km_m: float, kg_m: float) -> float:
    """GM = KM - KG."""
    return max(0.0, km_m - kg_m)


def solve_draft_from_displacement(
    displacement_t: float,
    length_m: float,
    breadth_m: float,
    lcg_norm: float,
    rho: float = RHO_SEA,
    cb: float = DEFAULT_CB,
    curves: HydrostaticCurves | None = None,
) -> tuple[float, float]:
    """
    Step 2 — Draft solver: solve Displacement(draft) = total weight (via curve or formula).
    Step 3 — Trim solver: longitudinal balance so trim is realistic (LCG vs LCB, MTC).
    Returns (draft_m, trim_m). When curves is None, uses formula and LCB=0.5.
    """
    if displacement_t <= 0 or length_m <= 0 or breadth_m <= 0:
        return 0.0, 0.0
    if curves is None or not curves.is_valid():
        draft_m = displacement_to_draft(displacement_t, length_m, breadth_m, cb, rho)
        trim_m = compute_trim(displacement_t, lcg_norm, length_m, breadth_m, draft_m, lcb_norm=0.5)
        return draft_m, trim_m
    draft_m = _curve_draft_from_disp(displacement_t, curves)
    if draft_m <= 0:
        draft_m = displacement_to_draft(displacement_t, length_m, breadth_m, cb, rho)
    lcb_norm = _curve_lcb(draft_m, curves)
    if lcb_norm is None:
        lcb_norm = 0.5
    i_t_i_l = _curve_i_t_i_l(draft_m, curves)
    if i_t_i_l is not None:
        i_t, i_l = i_t_i_l
        v = displacement_t / rho
        if v > EPS and i_l > 0:
            bm_l = i_l / v
            mtc = displacement_t * bm_l / (length_m * 100)
            if mtc > EPS:
                lcg_m = lcg_norm * length_m
                lcb_m = lcb_norm * length_m
                trim_m = (lcg_m - lcb_m) * displacement_t / mtc
                return draft_m, trim_m
    trim_m = compute_trim(displacement_t, lcg_norm, length_m, breadth_m, draft_m, lcb_norm=lcb_norm)
    return draft_m, trim_m


def get_kb_for_draft(draft_m: float, curves: HydrostaticCurves | None = None) -> float:
    """KB (m) at given draft: from curves if available, else formula."""
    if curves is not None and curves.is_valid():
        kb = _curve_kb(draft_m, curves)
        if kb is not None:
            return kb
    return compute_kb(draft_m)


def get_bm_t_from_curves(
    displacement_t: float,
    draft_m: float,
    length_m: float,
    breadth_m: float,
    rho: float,
    curves: HydrostaticCurves | None = None,
) -> float:
    """Transverse BM: from curves I_T/V if available, else formula."""
    if curves is not None and curves.is_valid():
        i_t_i_l = _curve_i_t_i_l(draft_m, curves)
        if i_t_i_l is not None:
            i_t, _ = i_t_i_l
            v = displacement_t / rho
            if v > EPS:
                return i_t / v
    return compute_bm_t(displacement_t, length_m, breadth_m, rho)


def get_bm_l_from_curves(
    displacement_t: float,
    draft_m: float,
    length_m: float,
    breadth_m: float,
    rho: float,
    curves: HydrostaticCurves | None = None,
) -> float:
    """Longitudinal BM: from curves I_L/V if available, else formula."""
    if curves is not None and curves.is_valid():
        i_t_i_l = _curve_i_t_i_l(draft_m, curves)
        if i_t_i_l is not None:
            _, i_l = i_t_i_l
            v = displacement_t / rho
            if v > EPS:
                return i_l / v
    return compute_bm_l(displacement_t, length_m, breadth_m, rho)
