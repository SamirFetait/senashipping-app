"""
Hydrostatic curves: table-based or formula-generated.

Holds draft → displacement, KB, LCB, Awp, I_T, I_L for interpolation.
Used by the iterative draft solver and stability pipeline when curves are available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from senashipping_app.config.stability_manual_ref import CWP

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
    Hydrostatic data as curves: draft (m) vs displacement, KB, LCB, LCF, etc.
    All lists are keyed by the same draft values (draft_m).
    wl_length_m: waterline length at each draft (from Excel); used for LCB/LCF and display.
    """
    draft_m: List[float] = field(default_factory=list)
    displacement_t: List[float] = field(default_factory=list)
    kb_m: List[float] = field(default_factory=list)
    lcb_norm: List[float] = field(default_factory=list)  # 0..1, 0.5 = amidships
    lcf_norm: List[float] = field(default_factory=list)  # 0..1, LCF for draft at marks
    awp_m2: List[float] = field(default_factory=list)
    i_t_m4: List[float] = field(default_factory=list)   # transverse waterplane inertia
    i_l_m4: List[float] = field(default_factory=list)   # longitudinal waterplane inertia
    wl_length_m: List[float] = field(default_factory=list)  # WL length at each draft (Excel)

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
    # Curve is (draft -> displacement). Find draft such that displacement(draft) = displacement_t.
    # _interpolate_inverse(target_y, x_list, y_list) returns x where y(x)=target_y.
    # So x_list = draft_m, y_list = displacement_t.
    return _interpolate_inverse(
        displacement_t,
        curves.draft_m,
        curves.displacement_t,
    )


def get_displacement_at_draft(draft_m: float, curves: HydrostaticCurves) -> Optional[float]:
    """Displacement (t) at given draft from curves. Returns None if curves invalid."""
    if not curves.is_valid():
        return None
    return _interpolate(draft_m, curves.draft_m, curves.displacement_t)


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


def get_lcf_norm(draft_m: float, curves: HydrostaticCurves) -> Optional[float]:
    """Get LCF (0..1) at given draft from curves. Returns None if not available."""
    if not curves.lcf_norm or len(curves.lcf_norm) != len(curves.draft_m):
        return None
    return _interpolate(draft_m, curves.draft_m, curves.lcf_norm)


def get_i_t_i_l(draft_m: float, curves: HydrostaticCurves) -> Optional[Tuple[float, float]]:
    """Get (I_T, I_L) in m⁴ at given draft. Returns None if not available."""
    if not curves.i_t_m4 or len(curves.i_t_m4) != len(curves.draft_m):
        return None
    if not curves.i_l_m4 or len(curves.i_l_m4) != len(curves.draft_m):
        return None
    i_t = _interpolate(draft_m, curves.draft_m, curves.i_t_m4)
    i_l = _interpolate(draft_m, curves.draft_m, curves.i_l_m4)
    return (i_t, i_l)


def get_wl_length(draft_m: float, curves: HydrostaticCurves) -> Optional[float]:
    """Get waterline length (m) at given draft. Returns None if not available."""
    if not curves.wl_length_m or len(curves.wl_length_m) != len(curves.draft_m):
        return None
    return _interpolate(draft_m, curves.draft_m, curves.wl_length_m)


def get_awp_at_draft(draft_m: float, curves: HydrostaticCurves) -> Optional[float]:
    """Get waterplane area (m²) at given draft. Returns None if not available."""
    if not curves.awp_m2 or len(curves.awp_m2) != len(curves.draft_m):
        return None
    return _interpolate(draft_m, curves.draft_m, curves.awp_m2)


def build_curves_from_formulas(
    length_m: float,
    breadth_m: float,
    design_draft_m: float,
    cb: float = 0.55,
    rho: float = RHO_SEA,
    num_points: int = 25,
) -> HydrostaticCurves:
    """
    Generate hydrostatic curves from principal dimensions and formulas (Path B).
    Uses draft_to_displacement, KB = f(Cb,T), LCB ≈ constant.
    I_T/I_L use waterplane coefficient Cwp from stability booklet: I = Cwp² × L × B³/12.
    """
    if length_m <= 0 or breadth_m <= 0 or design_draft_m <= 0 or num_points < 2:
        return HydrostaticCurves()
    draft_list: List[float] = []
    disp_list: List[float] = []
    kb_list: List[float] = []
    lcb_list: List[float] = []
    i_t_list: List[float] = []
    i_l_list: List[float] = []
    cwp2 = CWP ** 2
    for i in range(num_points):
        t = design_draft_m * (i / (num_points - 1))
        draft_list.append(t)
        vol_m3 = length_m * breadth_m * t * cb
        disp_list.append(vol_m3 * rho)
        # KB: Morrish-style KB/T = 0.535 - 0.055*Cb for typical forms (approx)
        kb_t_ratio = 0.535 - 0.055 * cb
        kb_list.append(kb_t_ratio * t)
        lcb_list.append(0.5)  # amidships
        # I_T, I_L: Osama Bey waterplane coefficient from stability booklet
        i_t = cwp2 * length_m * (breadth_m ** 3) / 12
        i_l = cwp2 * breadth_m * (length_m ** 3) / 12
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
    Expected keys: draft_m, displacement_t, and optionally kb_m, lcb_norm, lcf_norm,
    awp_m2, i_t_m4, i_l_m4.
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
    if "lcf_norm" in data and len(data["lcf_norm"]) == len(draft):
        curves.lcf_norm = list(data["lcf_norm"])
    if "awp_m2" in data and len(data["awp_m2"]) == len(draft):
        curves.awp_m2 = list(data["awp_m2"])
    if "i_t_m4" in data and len(data["i_t_m4"]) == len(draft):
        curves.i_t_m4 = list(data["i_t_m4"])
    if "i_l_m4" in data and len(data["i_l_m4"]) == len(draft):
        curves.i_l_m4 = list(data["i_l_m4"])
    if "wl_length_m" in data and len(data["wl_length_m"]) == len(draft):
        curves.wl_length_m = list(data["wl_length_m"])
    return curves


def _normalize_excel_column(name: str) -> str:
    """Normalize Excel column header for flexible matching."""
    return str(name).replace("\n", " ").strip().lower()


def _load_one_sheet_from_excel(p: "Path", sheet_name: str) -> HydrostaticCurves:
    """Load a single trim sheet from Excel into HydrostaticCurves."""
    import pandas as pd

    df = pd.read_excel(p, sheet_name=sheet_name)
    if df.empty:
        return HydrostaticCurves()

    col_map: dict[str, str] = {}
    for c in df.columns:
        col_map[_normalize_excel_column(c)] = c

    def _get_col(*candidates: str) -> str | None:
        for c in candidates:
            if c in col_map:
                return col_map[c]
        return None

    draft_col = _get_col("draft")
    disp_col = _get_col("displacement")
    if not draft_col or not disp_col:
        return HydrostaticCurves()

    draft_m = df[draft_col].dropna().astype(float).tolist()
    displacement_t = df[disp_col].dropna().astype(float).tolist()
    if len(draft_m) != len(displacement_t) or len(draft_m) < 2:
        return HydrostaticCurves()

    curves = HydrostaticCurves(draft_m=draft_m, displacement_t=displacement_t)

    kb_col = _get_col("kb")
    if kb_col:
        curves.kb_m = df[kb_col].dropna().astype(float).tolist()
        if len(curves.kb_m) != len(draft_m):
            curves.kb_m = []

    wp_col = _get_col("waterpl.", "waterpl", "waterplane", "awp")
    if wp_col:
        awp = df[wp_col].dropna().astype(float).tolist()
        if len(awp) == len(draft_m):
            curves.awp_m2 = awp

    wl_col = _get_col("wl length", "wl length m", "wl length")
    if wl_col:
        wl = df[wl_col].dropna().astype(float).tolist()
        if len(wl) == len(draft_m):
            curves.wl_length_m = wl

    # LCB/LCF in m from AP; normalize by LOA for solver (matches LCG coordinate system).
    from senashipping_app.config.stability_manual_ref import REF_LOA_M

    lcb_col = _get_col("lcb")
    lcf_col = _get_col("lcf")
    if lcb_col:
        lcb_m = df[lcb_col].dropna().astype(float).tolist()
        if len(lcb_m) == len(draft_m) and REF_LOA_M > 0:
            curves.lcb_norm = [lcb / REF_LOA_M for lcb in lcb_m]
    if lcf_col:
        lcf_m = df[lcf_col].dropna().astype(float).tolist()
        if len(lcf_m) == len(draft_m) and REF_LOA_M > 0:
            curves.lcf_norm = [lcf / REF_LOA_M for lcf in lcf_m]

    bmt_col = _get_col("bmt")
    bml_col = _get_col("bml")
    if bmt_col and bml_col:
        bmt = df[bmt_col].dropna().astype(float).tolist()
        bml = df[bml_col].dropna().astype(float).tolist()
        if len(bmt) == len(draft_m) and len(bml) == len(draft_m):
            rho = RHO_SEA
            curves.i_t_m4 = [
                bm * (d / rho) if d > 0 else 0.0
                for bm, d in zip(bmt, displacement_t)
            ]
            curves.i_l_m4 = [
                bm * (d / rho) if d > 0 else 0.0
                for bm, d in zip(bml, displacement_t)
            ]
    return curves


def _merge_curves_by_trim(
    curves_lo: HydrostaticCurves,
    curves_hi: HydrostaticCurves,
    trim_m: float,
    lower_trim: float,
    upper_trim: float,
) -> HydrostaticCurves:
    """Interpolate between two trim sheets to produce merged curves at trim_m."""
    if not curves_lo.is_valid():
        return curves_hi
    if not curves_hi.is_valid():
        return curves_lo
    if abs(upper_trim - lower_trim) < 1e-9:
        return curves_lo

    t = (trim_m - lower_trim) / (upper_trim - lower_trim)
    t = max(0.0, min(1.0, t))

    # Use draft grid from lower sheet
    draft_m = list(curves_lo.draft_m)
    n = len(draft_m)

    def _interp_list(lo_list: List[float], hi_list: List[float]) -> List[float]:
        if not lo_list or len(lo_list) != n:
            return lo_list or hi_list
        if not hi_list or len(hi_list) != len(curves_hi.draft_m):
            return lo_list
        out: List[float] = []
        for i, d in enumerate(draft_m):
            v_lo = _interpolate(d, curves_lo.draft_m, lo_list)
            v_hi = _interpolate(d, curves_hi.draft_m, hi_list)
            out.append((1.0 - t) * v_lo + t * v_hi)
        return out

    return HydrostaticCurves(
        draft_m=draft_m,
        displacement_t=_interp_list(curves_lo.displacement_t, curves_hi.displacement_t),
        kb_m=_interp_list(curves_lo.kb_m, curves_hi.kb_m) if curves_lo.kb_m else [],
        lcb_norm=_interp_list(curves_lo.lcb_norm, curves_hi.lcb_norm) if curves_lo.lcb_norm else [],
        lcf_norm=_interp_list(curves_lo.lcf_norm, curves_hi.lcf_norm) if curves_lo.lcf_norm else [],
        awp_m2=_interp_list(curves_lo.awp_m2, curves_hi.awp_m2) if curves_lo.awp_m2 else [],
        wl_length_m=_interp_list(curves_lo.wl_length_m, curves_hi.wl_length_m) if curves_lo.wl_length_m else [],
        i_t_m4=_interp_list(curves_lo.i_t_m4, curves_hi.i_t_m4) if curves_lo.i_t_m4 else [],
        i_l_m4=_interp_list(curves_lo.i_l_m4, curves_hi.i_l_m4) if curves_lo.i_l_m4 else [],
    )


def load_curves_from_excel(
    path: str | None,
    trim_m: float = 0.0,
    base_path: Any = None,
) -> HydrostaticCurves:
    """
    Load HydrostaticCurves from an Excel hydrostatics table.

    Expected Excel structure:
    - Sheets named by trim in metres (e.g. "0.00", "-0.50", "1.00")
    - Columns: Draft, Displacement, WL length, Waterpl., LCB, LCF, KB, BMt, BML, TPc, MTc

    trim_m: trim (m); interpolates between bracketing sheets (matches Maxsurf).
    path: relative or absolute. If relative, resolved against base_path.
    Returns empty HydrostaticCurves if path is None, file not found, or invalid.
    """
    if not path:
        return HydrostaticCurves()
    from pathlib import Path

    p = Path(path)
    if not p.is_absolute() and base_path is not None:
        p = Path(base_path) / path
    p = p.resolve()
    if not p.exists():
        return HydrostaticCurves()
    try:
        import pandas as pd

        xl = pd.ExcelFile(p)
        trim_to_sheet: dict[float, str] = {}
        for name in xl.sheet_names:
            try:
                t = float(str(name).strip())
                trim_to_sheet[t] = name
            except ValueError:
                continue
        if not trim_to_sheet:
            return HydrostaticCurves()
        available_trims = sorted(trim_to_sheet.keys())

        trim_val = trim_m
        if trim_val <= available_trims[0]:
            return _load_one_sheet_from_excel(p, trim_to_sheet[available_trims[0]])
        if trim_val >= available_trims[-1]:
            return _load_one_sheet_from_excel(p, trim_to_sheet[available_trims[-1]])

        lower_trim = max(t for t in available_trims if t <= trim_val)
        upper_trim = min(t for t in available_trims if t >= trim_val)
        curves_lo = _load_one_sheet_from_excel(p, trim_to_sheet[lower_trim])
        curves_hi = _load_one_sheet_from_excel(p, trim_to_sheet[upper_trim])
        return _merge_curves_by_trim(
            curves_lo, curves_hi, trim_val, lower_trim, upper_trim
        )
    except Exception:
        return HydrostaticCurves()


def load_curves_from_file(
    path: str | None,
    base_path: Any = None,
    trim_m: float = 0.0,
) -> HydrostaticCurves:
    """
    Load HydrostaticCurves from a JSON or Excel file.
    path: relative or absolute path. If relative, resolved against base_path.
    trim_m: for Excel files, selects the sheet closest to this trim (m). Ignored for JSON.
    Returns empty HydrostaticCurves if path is None, file not found, or invalid.
    """
    if not path:
        return HydrostaticCurves()
    import json
    from pathlib import Path

    p = Path(path)
    if not p.is_absolute() and base_path is not None:
        p = Path(base_path) / path
    p = p.resolve()
    if not p.exists():
        return HydrostaticCurves()
    try:
        if p.suffix.lower() in (".xlsx", ".xls"):
            return load_curves_from_excel(str(p), trim_m=trim_m, base_path=None)
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return load_curves_from_dict(data)
    except Exception:
        return HydrostaticCurves()
