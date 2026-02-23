"""
Hydrostatic curves: table-based or formula-generated.

Holds draft → displacement, KB, LCB, Awp, I_T, I_L for interpolation.
Used by the iterative draft solver and stability pipeline when curves are available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

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


def _polygon_properties_2d(vertices: List[Tuple[float, float]]) -> Tuple[float, float, float, float, float]:
    """Given closed polygon vertices (x,y), return (area, cx, cy, i_xx, i_yy). i_xx = int y^2 dA, i_yy = int x^2 dA (about origin)."""
    n = len(vertices)
    if n < 3:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    area = 0.0
    cx_num = 0.0
    cy_num = 0.0
    i_xx = 0.0
    i_yy = 0.0
    for i in range(n):
        j = (i + 1) % n
        xi, yi = vertices[i][0], vertices[i][1]
        xj, yj = vertices[j][0], vertices[j][1]
        cross = xi * yj - xj * yi
        area += cross
        cx_num += (xi + xj) * cross
        cy_num += (yi + yj) * cross
        i_xx += (yi * yi + yi * yj + yj * yj) * cross
        i_yy += (xi * xi + xi * xj + xj * xj) * cross
    area *= 0.5
    if abs(area) < EPS:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    cx = cx_num / (6.0 * area)
    cy = cy_num / (6.0 * area)
    i_xx = abs(i_xx) / 12.0 - area * (cy ** 2)
    i_yy = abs(i_yy) / 12.0 - area * (cx ** 2)
    return abs(area), cx, cy, max(0.0, i_xx), max(0.0, i_yy)


def _trimesh_section_waterplane(mesh: Any, draft: float) -> Tuple[float, float, float, float, float]:
    """Get waterplane area, centroid (x,y), I_T, I_L at given draft. Returns (area, cx, cy, i_t, i_l)."""
    try:
        section = mesh.section(plane_origin=[0, 0, draft], plane_normal=[0, 0, 1])
        if section is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        planar, _ = section.to_planar()
        if planar is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        total_area = 0.0
        total_cx = 0.0
        total_cy = 0.0
        total_i_t = 0.0
        total_i_l = 0.0
        entities = getattr(planar, "entities", [])
        for entity in entities:
            try:
                pts = entity.discrete(planar) if hasattr(entity, "discrete") else None
            except Exception:
                pts = None
            if pts is None:
                continue
            try:
                if hasattr(pts, "__iter__") and len(pts) >= 3:
                    if hasattr(pts, "shape"):
                        verts = [(float(pts[i][0]), float(pts[i][1])) for i in range(pts.shape[0])]
                    else:
                        verts = [(float(p[0]), float(p[1])) for p in pts]
                else:
                    continue
            except (TypeError, IndexError):
                continue
            if len(verts) < 3:
                continue
            a, cx, cy, i_xx, i_yy = _polygon_properties_2d(verts)
            total_area += a
            if a > EPS:
                total_cx += cx * a
                total_cy += cy * a
                total_i_t += i_xx
                total_i_l += i_yy
        if total_area < EPS:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        return total_area, total_cx / total_area, total_cy / total_area, total_i_t, total_i_l
    except Exception:
        return 0.0, 0.0, 0.0, 0.0, 0.0


def build_curves_from_hull_stl_trimesh(
    stl_path: str,
    design_draft_m: float,
    rho: float = RHO_SEA,
    num_points: int = 25,
) -> Optional[HydrostaticCurves]:
    """
    Generate hydrostatic curves from a hull STL using trimesh (pure Python, no Rust).

    Requires: pip install trimesh. STL units: metres. X = longitudinal, Z = vertical (keel up).
    Integrates waterplane areas over draft to get displacement, KB, LCB; uses waterplane I_T, I_L at each draft.
    """
    try:
        import trimesh
    except ImportError:
        return None
    try:
        mesh = trimesh.load(stl_path, force="mesh")
        if mesh is None or not hasattr(mesh, "bounds"):
            return None
        bounds = mesh.bounds  # (min_pt, max_pt)
        x_min, x_max = float(bounds[0][0]), float(bounds[1][0])
        z_min, z_max = float(bounds[0][2]), float(bounds[1][2])
        length_m = max(1e-6, x_max - x_min)
        max_draft = min(design_draft_m, max(0.01, z_max - z_min))
        if max_draft <= 0:
            max_draft = design_draft_m
        drafts = [max_draft * i / max(num_points - 1, 1) for i in range(num_points)]
        areas: List[float] = []
        cxs: List[float] = []
        cys: List[float] = []
        i_ts: List[float] = []
        i_ls: List[float] = []
        for t in drafts:
            a, cx, cy, i_t, i_l = _trimesh_section_waterplane(mesh, z_min + t)
            areas.append(a)
            cxs.append(cx)
            cys.append(cy)
            i_ts.append(i_t)
            i_ls.append(i_l)
        vol_at_draft: List[float] = []
        moment_z: List[float] = []
        moment_x: List[float] = []
        for i in range(num_points):
            if i == 0:
                vol_at_draft.append(0.0)
                moment_z.append(0.0)
                moment_x.append(0.0)
            else:
                dz = drafts[i] - drafts[i - 1]
                v = 0.5 * (areas[i] + areas[i - 1]) * dz
                mz = 0.5 * ((drafts[i] + z_min) * areas[i] + (drafts[i - 1] + z_min) * areas[i - 1]) * dz
                mx = 0.5 * (cxs[i] * areas[i] + cxs[i - 1] * areas[i - 1]) * dz
                vol_at_draft.append(vol_at_draft[-1] + v)
                moment_z.append(moment_z[-1] + mz)
                moment_x.append(moment_x[-1] + mx)
        draft_list: List[float] = []
        disp_list: List[float] = []
        kb_list: List[float] = []
        lcb_list: List[float] = []
        i_t_list: List[float] = []
        i_l_list: List[float] = []
        for i in range(num_points):
            draft_list.append(drafts[i])
            v = vol_at_draft[i]
            disp_list.append(rho * v)
            if v > EPS:
                kb_list.append(moment_z[i] / v)
                lcb_m = moment_x[i] / v
                lcb_norm = (lcb_m - x_min) / length_m if length_m > 0 else 0.5
                lcb_list.append(max(0.0, min(1.0, lcb_norm)))
            else:
                kb_list.append(0.0)
                lcb_list.append(0.5)
            i_t_list.append(i_ts[i])
            i_l_list.append(i_ls[i])
        return HydrostaticCurves(
            draft_m=draft_list,
            displacement_t=disp_list,
            kb_m=kb_list,
            lcb_norm=lcb_list,
            i_t_m4=i_t_list,
            i_l_m4=i_l_list,
        )
    except Exception:
        return None


def build_curves_from_hull_stl(
    stl_path: str,
    design_draft_m: float,
    rho: float = RHO_SEA,
    num_points: int = 25,
    nominal_vcg_frac: float = 0.5,
) -> Optional[HydrostaticCurves]:
    """
    Generate hydrostatic curves from a hull STL file.

    Tries NavalToolbox first (pip install navaltoolbox; requires Rust on some systems).
    Falls back to trimesh (pip install trimesh; pure Python, no Rust).
    STL units: metres. X = longitudinal (AP to FP), Z = vertical (keel up).
    """
    # Try NavalToolbox first (may fail if Rust not available)
    try:
        from navaltoolbox import Hull, Vessel, HydrostaticsCalculator
    except ImportError:
        pass
    else:
        try:
            return _build_curves_from_hull_stl_navaltoolbox(
                stl_path, design_draft_m, rho, num_points, nominal_vcg_frac
            )
        except Exception:
            pass
    # Fallback: trimesh (pure Python)
    return build_curves_from_hull_stl_trimesh(stl_path, design_draft_m, rho, num_points)


def _build_curves_from_hull_stl_navaltoolbox(
    stl_path: str,
    design_draft_m: float,
    rho: float,
    num_points: int,
    nominal_vcg_frac: float,
) -> Optional[HydrostaticCurves]:
    """NavalToolbox-based STL curve generation (requires Rust to install)."""
    try:
        from navaltoolbox import Hull, Vessel, HydrostaticsCalculator
    except ImportError:
        return None
    try:
        hull = Hull(stl_path)
        vessel = Vessel(hull)
        calc = HydrostaticsCalculator(vessel, water_density=rho * 1000.0)  # kg/m³
        bounds = hull.get_bounds()
        # bounds may be (x_min, x_max, y_min, y_max, z_min, z_max) or dict/list
        try:
            if hasattr(bounds, "__len__") and len(bounds) >= 6:
                x_min, x_max = float(bounds[0]), float(bounds[1])
                z_min, z_max = float(bounds[4]), float(bounds[5])
            else:
                x_min, x_max = 0.0, 1.0
                z_min, z_max = 0.0, design_draft_m
        except (TypeError, IndexError):
            x_min, x_max = 0.0, 1.0
            z_min, z_max = 0.0, design_draft_m
        length_m = max(1e-6, x_max - x_min)
        max_draft = min(design_draft_m, max(0.01, z_max - z_min))
        if max_draft <= 0:
            max_draft = design_draft_m
        draft_list: List[float] = []
        disp_list: List[float] = []
        kb_list: List[float] = []
        lcb_list: List[float] = []
        i_t_list: List[float] = []
        i_l_list: List[float] = []
        for i in range(num_points):
            t = max_draft * (i / max(num_points - 1, 1))
            draft_list.append(t)
            vcg = nominal_vcg_frac * max_draft
            state = calc.from_draft(draft=t, vcg=vcg)
            vol = getattr(state, "volume", 0.0) or 0.0
            disp_t = (getattr(state, "displacement", 0.0) or 0.0) / 1000.0
            disp_list.append(disp_t)
            cob = getattr(state, "cob", (length_m * 0.5, 0.0, t * 0.5))
            if isinstance(cob, (list, tuple)) and len(cob) >= 3:
                lcb_x = float(cob[0])
                kb_list.append(float(cob[2]))
                lcb_norm = (lcb_x - x_min) / length_m if length_m > 0 else 0.5
                lcb_norm = max(0.0, min(1.0, lcb_norm))
                lcb_list.append(lcb_norm)
            else:
                kb_list.append(t * 0.53)
                lcb_list.append(0.5)
            # I_T = BM_t * V; KM = KB + BM_t, GM = KM - KG => BM_t = KM - KB = (GM + KG) - KB
            kb_val = kb_list[-1]
            gmt_dry = getattr(state, "gmt_dry", None)
            if gmt_dry is not None and vol > EPS:
                km = (gmt_dry + vcg)
                bm_t = max(0.0, km - kb_val)
                i_t_list.append(bm_t * vol)
            else:
                b = length_m * 0.2  # fallback breadth guess
                i_t_list.append(length_m * (b ** 3) / 12)
            # I_L: use longitudinal metacentric radius if available, else rectangular WP
            gml = getattr(state, "gml", None) or getattr(state, "longitudinal_metacentric_height", None)
            if gml is not None and vol > EPS:
                kb_val = kb_list[-1]
                bm_l = max(0.0, (gml + vcg) - kb_val)
                i_l_list.append(bm_l * vol)
            else:
                b = length_m * 0.2
                i_l_list.append(b * (length_m ** 3) / 12)
        return HydrostaticCurves(
            draft_m=draft_list,
            displacement_t=disp_list,
            kb_m=kb_list,
            lcb_norm=lcb_list,
            i_t_m4=i_t_list,
            i_l_m4=i_l_list,
        )
    except Exception:
        return None


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
