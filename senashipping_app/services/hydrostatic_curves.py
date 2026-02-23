"""
Hydrostatic curves: table-based or formula-generated.

Holds draft → displacement, KB, LCB, Awp, I_T, I_L for interpolation.
Used by the iterative draft solver and stability pipeline when curves are available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Default seawater density t/m³
RHO_SEA = 1.025
EPS = 1e-9


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if abs(b) < EPS:
        return default
    return a / b


def _interpolate(x: float, x_list: List[float], y_list: List[float]) -> float:
    """Linear interpolation. Clamp to range if x outside."""
    if not x_list or not y_list or len(x_list) != len(y_list):
        return 0.0
    if x <= x_list[0]:
        return y_list[0]
    if x >= x_list[-1]:
        return y_list[-1]
    for i in range(len(x_list) - 1):
        if x_list[i] <= x <= x_list[i + 1]:
            t = (x - x_list[i]) / (x_list[i + 1] - x_list[i]) if x_list[i + 1] != x_list[i] else 0.0
            return y_list[i] + t * (y_list[i + 1] - y_list[i])
    return y_list[-1]


def _interpolate_inverse(y: float, x_list: List[float], y_list: List[float]) -> float:
    """Find x such that y(x) ≈ y (inverse interpolation)."""
    if not x_list or not y_list or len(x_list) != len(y_list):
        return 0.0
    if y <= y_list[0]:
        return x_list[0]
    if y >= y_list[-1]:
        return x_list[-1]
    for i in range(len(y_list) - 1):
        if min(y_list[i], y_list[i + 1]) <= y <= max(y_list[i], y_list[i + 1]):
            t = (y - y_list[i]) / (y_list[i + 1] - y_list[i]) if y_list[i + 1] != y_list[i] else 0.0
            return x_list[i] + t * (x_list[i + 1] - x_list[i])
    return x_list[-1]


@dataclass
class HydrostaticCurves:
    """
    Hydrostatic data as curves: draft (m) vs displacement, KB, LCB, etc.
    All lists are keyed by the same draft values (draft_m).
    """
    draft_m: List[float] = field(default_factory=list)
    displacement_t: List[float] = field(default_factory=list)
    kb_m: List[float] = field(default_factory=list)
    lcb_norm: List[float] = field(default_factory=list)  # 0..1, 0.5 = amidships
    awp_m2: List[float] = field(default_factory=list)
    i_t_m4: List[float] = field(default_factory=list)   # transverse waterplane inertia
    i_l_m4: List[float] = field(default_factory=list)   # longitudinal waterplane inertia

    def is_valid(self) -> bool:
        """True if we have at least draft and displacement for interpolation."""
        return (
            len(self.draft_m) >= 2
            and len(self.displacement_t) == len(self.draft_m)
            and all(d >= 0 for d in self.draft_m)
        )


def interpolate_draft_from_displacement(
    displacement_t: float,
    curves: HydrostaticCurves,
) -> float:
    """
    Step 2 — Draft solver: find draft such that Displacement(draft) = total weight.
    Solves iteratively via inverse interpolation on the displacement curve so the ship floats correctly.
    Returns mean draft (m); 0 if curves invalid.
    """
    if not curves.is_valid() or displacement_t <= 0:
        return 0.0
    return _interpolate_inverse(
        displacement_t,
        curves.displacement_t,
        curves.draft_m,
    )


def get_kb(draft_m: float, curves: HydrostaticCurves) -> Optional[float]:
    """Get KB (m) at given draft from curves. Returns None if not available."""
    if not curves.kb_m or len(curves.kb_m) != len(curves.draft_m):
        return None
    return _interpolate(draft_m, curves.draft_m, curves.kb_m)


def get_lcb_norm(draft_m: float, curves: HydrostaticCurves) -> Optional[float]:
    """Get LCB (0..1) at given draft from curves. Returns None if not available."""
    if not curves.lcb_norm or len(curves.lcb_norm) != len(curves.draft_m):
        return None
    return _interpolate(draft_m, curves.draft_m, curves.lcb_norm)


def get_i_t_i_l(draft_m: float, curves: HydrostaticCurves) -> Optional[Tuple[float, float]]:
    """Get (I_T, I_L) in m⁴ at given draft. Returns None if not available."""
    if not curves.i_t_m4 or len(curves.i_t_m4) != len(curves.draft_m):
        return None
    if not curves.i_l_m4 or len(curves.i_l_m4) != len(curves.draft_m):
        return None
    i_t = _interpolate(draft_m, curves.draft_m, curves.i_t_m4)
    i_l = _interpolate(draft_m, curves.draft_m, curves.i_l_m4)
    return (i_t, i_l)


def build_curves_from_formulas(
    length_m: float,
    breadth_m: float,
    design_draft_m: float,
    cb: float = 0.78,
    rho: float = RHO_SEA,
    num_points: int = 25,
) -> HydrostaticCurves:
    """
    Generate hydrostatic curves from principal dimensions and formulas (Path B).
    Uses draft_to_displacement, KB = f(Cb,T), LCB ≈ constant, I_T/I_L rectangular WP.
    """
    if length_m <= 0 or breadth_m <= 0 or design_draft_m <= 0 or num_points < 2:
        return HydrostaticCurves()
    draft_list: List[float] = []
    disp_list: List[float] = []
    kb_list: List[float] = []
    lcb_list: List[float] = []
    i_t_list: List[float] = []
    i_l_list: List[float] = []
    for i in range(num_points):
        t = design_draft_m * (i / (num_points - 1))
        draft_list.append(t)
        vol_m3 = length_m * breadth_m * t * cb
        disp_list.append(vol_m3 * rho)
        # KB: Morrish-style KB/T = 0.535 - 0.055*Cb for typical forms (approx)
        kb_t_ratio = 0.535 - 0.055 * cb
        kb_list.append(kb_t_ratio * t)
        lcb_list.append(0.5)  # amidships
        i_t = length_m * (breadth_m ** 3) / 12
        i_l = breadth_m * (length_m ** 3) / 12
        i_t_list.append(i_t)
        i_l_list.append(i_l)
    return HydrostaticCurves(
        draft_m=draft_list,
        displacement_t=disp_list,
        kb_m=kb_list,
        lcb_norm=lcb_list,
        i_t_m4=i_t_list,
        i_l_m4=i_l_list,
    )


@dataclass
class SectionalAreaCurve:
    """
    Sectional area curve at one or more drafts.
    station_x_norm: longitudinal position 0..1 (0 = AP, 1 = FP).
    areas_at_draft_m: list of (draft_m, areas_m2) with areas_m2 length = len(station_x_norm).
    Or use single draft: areas_m2 only, one draft implied.
    """
    station_x_norm: List[float] = field(default_factory=list)
    areas_m2: List[float] = field(default_factory=list)  # at design draft
    draft_m: float = 0.0  # draft at which areas_m2 are given (optional)

    def is_valid(self) -> bool:
        return (
            len(self.station_x_norm) >= 2
            and len(self.areas_m2) == len(self.station_x_norm)
            and all(a >= 0 for a in self.areas_m2)
        )


def _trapezoidal_integrate(x_list: List[float], y_list: List[float]) -> float:
    """Trapezoidal rule along x. x_list and y_list same length."""
    n = len(x_list)
    if n != len(y_list) or n < 2:
        return 0.0
    total = 0.0
    for i in range(n - 1):
        h = x_list[i + 1] - x_list[i]
        total += (y_list[i] + y_list[i + 1]) / 2.0 * h
    return total


def displacement_and_lcb_from_sectional_areas(
    length_m: float,
    section_curve: SectionalAreaCurve,
    rho: float = RHO_SEA,
) -> Tuple[float, float]:
    """
    Compute displacement (t) and LCB (0..1 norm) from sectional area curve.
    Uses Simpson integration along length. Returns (0, 0.5) if invalid.
    """
    if not section_curve.is_valid() or length_m <= 0:
        return 0.0, 0.5
    xs = section_curve.station_x_norm
    areas = section_curve.areas_m2
    n = len(xs)
    if n < 2:
        return 0.0, 0.5
    vol_norm = _trapezoidal_integrate(xs, areas)
    vol = vol_norm * length_m
    displacement_t = vol * rho
    moment_list = [xs[i] * areas[i] for i in range(n)]
    moment_norm = _trapezoidal_integrate(xs, moment_list)
    lcb_norm = _safe_div(moment_norm, vol_norm, 0.5)
    return displacement_t, lcb_norm


def load_sectional_area_from_dict(data: dict) -> Optional[SectionalAreaCurve]:
    """
    Build SectionalAreaCurve from dict (e.g. JSON).
    Expected keys: "stations" or "station_x_norm" (0..1), "areas_m2" or "areas_at_draft".
    """
    stations = list(data.get("station_x_norm", data.get("stations", [])))
    areas = list(data.get("areas_m2", data.get("areas_at_draft", [])))
    if len(stations) < 2 or len(areas) != len(stations):
        return None
    return SectionalAreaCurve(
        station_x_norm=stations,
        areas_m2=areas,
        draft_m=float(data.get("draft_m", 0.0)),
    )


def load_curves_from_dict(data: dict) -> HydrostaticCurves:
    """
    Build HydrostaticCurves from a dict (e.g. JSON loaded).
    Expected keys: draft_m, displacement_t, and optionally kb_m, lcb_norm, awp_m2, i_t_m4, i_l_m4.
    """
    draft = list(data.get("draft_m", []))
    disp = list(data.get("displacement_t", []))
    if not draft or not disp or len(draft) != len(disp):
        return HydrostaticCurves()
    curves = HydrostaticCurves(draft_m=draft, displacement_t=disp)
    if "kb_m" in data and len(data["kb_m"]) == len(draft):
        curves.kb_m = list(data["kb_m"])
    if "lcb_norm" in data and len(data["lcb_norm"]) == len(draft):
        curves.lcb_norm = list(data["lcb_norm"])
    if "awp_m2" in data and len(data["awp_m2"]) == len(draft):
        curves.awp_m2 = list(data["awp_m2"])
    if "i_t_m4" in data and len(data["i_t_m4"]) == len(draft):
        curves.i_t_m4 = list(data["i_t_m4"])
    if "i_l_m4" in data and len(data["i_l_m4"]) == len(draft):
        curves.i_l_m4 = list(data["i_l_m4"])
    return curves
