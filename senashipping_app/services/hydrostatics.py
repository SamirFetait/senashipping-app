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

# Seawater density t/m³ (manual p.9: 1.025)
RHO_SEA = 1.025

# Floating-point tolerance for safe divisions
EPS = 1e-9


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Avoid zero divisions."""
    if abs(b) < EPS:
        return default
    return a / b

# Typical block coefficient for cargo/tanker
DEFAULT_CB = 0.78


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
