"""
Longitudinal strength (simplified shear force and bending moment).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..models import Tank, LivestockPen

# Seawater density t/m³
RHO_SEA = 1.025


@dataclass(slots=True)
class StrengthResult:
    """Simplified longitudinal strength results."""
    hogging_bm_tm: float  # sagging negative, hogging positive
    shear_force_max_t: float
    still_water_bm_approx_tm: float
    design_bm_tm: float = 0.0  # design limit for % calculation
    design_sf_t: float = 0.0   # design limit for % calculation
    bm_pct_allow: float = 0.0  # (swbm / design_bm) * 100
    sf_pct_allow: float = 0.0  # (sf_max / design_sf) * 100


def compute_strength(
    displacement_t: float,
    length_m: float,
    tanks: List[Tank],
    tank_volumes: Dict[int, float],
    cargo_density: float = 1.0,
    pens: List[LivestockPen] | None = None,
    pen_loadings: Dict[int, int] | None = None,
    mass_per_head: float = 0.5,
    tank_cog_override: Optional[Dict[int, Tuple[float, float, float]]] = None,
) -> StrengthResult:
    """
    Simplified still-water bending moment and shear.

    Assumes uniform buoyancy distribution; compares to actual weight
    distribution from tanks to get approximate BM.
    If tank_cog_override is set (tank_id -> (vcg_m, lcg_m, tcg_m)), LCG from
    override is used for tank moment about amidships.
    """
    if length_m <= 0 or displacement_t <= 0:
        return StrengthResult(
            hogging_bm_tm=0.0,
            shear_force_max_t=0.0,
            still_water_bm_approx_tm=0.0,
        )

    override = tank_cog_override or {}
    # Total weight moment about amidships (stern positive = LCG aft)
    total_mass = 0.0
    moment_sum = 0.0
    for tank in tanks:
        vol = tank_volumes.get(tank.id or -1, 0.0)
        mass = vol * cargo_density
        total_mass += mass
        tid = tank.id or -1
        if tid in override:
            _vcg_m, lcg_m, _tcg_m = override[tid]
            moment_sum += (lcg_m - length_m * 0.5) * mass
        else:
            pos = tank.longitudinal_pos
            moment_sum += (pos - 0.5) * length_m * mass

    loadings = pen_loadings or {}
    for pen in (pens or []):
        heads = loadings.get(pen.id or -1, 0)
        if heads <= 0:
            continue
        mass = heads * mass_per_head
        total_mass += mass
        # lcg_m from AP; moment about amidships = (lcg_m - L/2) * mass
        moment_sum += (pen.lcg_m - length_m * 0.5) * mass

    if total_mass <= 0:
        return StrengthResult(
            hogging_bm_tm=0.0,
            shear_force_max_t=0.0,
            still_water_bm_approx_tm=0.0,
        )

    lcg_from_mid = moment_sum / total_mass

    # Uniform buoyancy => LCB at 0.5L. Difference creates moment.
    # Approximate SWBM: 0.25 * disp * L * (1 - 2*|LCG-0.5|) for box
    lcg_norm = 0.5 + lcg_from_mid / length_m
    lcg_norm = max(0.0, min(1.0, lcg_norm))
    eccent = abs(lcg_norm - 0.5)
    # Simplified: max BM ~ disp * L * eccent * factor
    swbm = displacement_t * length_m * eccent * 0.25

    # Shear: max at ends, simplified
    sf_max = displacement_t * 0.1 * eccent * 2

    # Design limits (simplified: disp * L * factor)
    design_bm = displacement_t * length_m * 0.12
    design_sf = displacement_t * 0.15
    bm_pct = (abs(swbm) / design_bm * 100.0) if design_bm > 0 else 0.0
    sf_pct = (abs(sf_max) / design_sf * 100.0) if design_sf > 0 else 0.0

    return StrengthResult(
        hogging_bm_tm=swbm if lcg_norm < 0.5 else -swbm,
        shear_force_max_t=abs(sf_max),
        still_water_bm_approx_tm=swbm,
        design_bm_tm=design_bm,
        design_sf_t=design_sf,
        bm_pct_allow=bm_pct,
        sf_pct_allow=sf_pct,
    )
