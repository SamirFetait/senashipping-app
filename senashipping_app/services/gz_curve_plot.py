"""
GZ curve computation and matplotlib plotting.

Physics-only: GZ(θ) = KN(θ) − KG×sin(θ). No smoothing or shape enforcement.
KN table from Excel (assets/KN tables.xlsx). For backwards compatibility, the
old name assets/KZ tables.xlsx is also accepted if the KN file is absent.
Sheet = trim (m), rows = displacement (t), columns = heel angle (deg).
KN and GZ in metres; angles in degrees.
Bilinear interpolation: displacement (rows), then heel angle (columns).
For θ < 10°: KN ≈ KN(10°) × (θ / 10°); no extrapolation below 10°.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

_LOG = logging.getLogger(__name__)

# NumPy 2.0+ removed np.trapz; use np.trapezoid when available
_trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))

# Do not use table for heel angles below this (use KN(10°)*(θ/10) instead)
_KN_ANGLE_MIN_DEG = 10.0


def _angle_to_column_name(angle_deg: float) -> str:
    """Canonical column name for an angle, e.g. 10 -> '10°', 20.5 -> '20.5°'."""
    a = float(angle_deg)
    return f"{int(a)}°" if a == int(a) else f"{a}°"


def _column_index_for_angle(angle_deg: float, heel: np.ndarray, column_names: list[str]) -> int | None:
    """Return column index j for the given angle (dynamic lookup by angle/name). None if not found."""
    target_name = _angle_to_column_name(angle_deg)
    for j, name in enumerate(column_names):
        if name == target_name:
            return j
    for j in range(len(heel)):
        if abs(float(heel[j]) - angle_deg) < 0.01:
            return j
    return None


class _KNTable(dict):
    """
    KN table that supports lookup by angle (float) or by column name (str, e.g. '10°').
    Use interpolated_row[column_name] dynamically; no fixed column indices.
    """

    def __init__(self, numeric: dict[float, float], by_column_name: dict[str, float]) -> None:
        super().__init__(numeric)
        self._by_name = by_column_name

    def __getitem__(self, key: float | str) -> float:
        if isinstance(key, str):
            return self._by_name[key]
        return super().__getitem__(key)


def get_kn_bilinear(
    disp: np.ndarray,
    heel: np.ndarray,
    kz: np.ndarray,
    displacement_t: float,
    angle_deg: float,
) -> float:
    """
    Bilinear interpolation of KN: displacement rows, then angle columns.
    Do not extrapolate below 10°: for θ < 10° use KN ≈ KN(10°) × (θ / 10°).
    """
    if disp.size == 0 or heel.size == 0 or kz.shape != (disp.size, heel.size):
        return 0.0

    if angle_deg < _KN_ANGLE_MIN_DEG:
        kn_10 = get_kn_bilinear(disp, heel, kz, displacement_t, _KN_ANGLE_MIN_DEG)
        return kn_10 * (angle_deg / _KN_ANGLE_MIN_DEG)

    # 1) Find bounding displacement rows
    if displacement_t <= disp[0]:
        row = kz[0, :].copy()
    elif displacement_t >= disp[-1]:
        row = kz[-1, :].copy()
    else:
        idx = int(np.searchsorted(disp, displacement_t))
        i0 = max(0, idx - 1)
        i1 = min(len(disp) - 1, idx)
        if i0 == i1:
            row = kz[i0, :].copy()
        else:
            d0, d1 = float(disp[i0]), float(disp[i1])
            t = (displacement_t - d0) / (d1 - d0) if d1 > d0 else 0.0
            row = ((1.0 - t) * kz[i0, :] + t * kz[i1, :]).astype(float)

    # 2) For requested heel angle, interpolate between nearest angle columns
    if angle_deg <= heel[0]:
        return float(row[0])
    if angle_deg >= heel[-1]:
        return float(row[-1])
    j = int(np.searchsorted(heel, angle_deg))
    j0 = max(0, j - 1)
    j1 = min(len(heel) - 1, j)
    if j0 == j1:
        return float(row[j0])
    a0, a1 = float(heel[j0]), float(heel[j1])
    t = (angle_deg - a0) / (a1 - a0) if a1 > a0 else 0.0
    return (1.0 - t) * float(row[j0]) + t * float(row[j1])


def _interp_kn(angle_deg: float, kn_table: dict[float, float]) -> float:
    """
    Interpolate KN at heel angle from table (table already bilinear in displacement).
    Do not extrapolate below 10°: for θ < 10° use KN ≈ KN(10°) × (θ / 10°).
    """
    keys = sorted(kn_table.keys())
    if not keys:
        return 0.0
    if angle_deg < _KN_ANGLE_MIN_DEG:
        kn_10 = _interp_kn(_KN_ANGLE_MIN_DEG, kn_table)
        return kn_10 * (angle_deg / _KN_ANGLE_MIN_DEG)
    if angle_deg <= keys[0]:
        return float(kn_table[keys[0]])
    if angle_deg >= keys[-1]:
        return float(kn_table[keys[-1]])
    for i in range(len(keys) - 1):
        a0, a1 = keys[i], keys[i + 1]
        if a0 <= angle_deg <= a1:
            t = (angle_deg - a0) / (a1 - a0) if a1 > a0 else 0.0
            return (1.0 - t) * float(kn_table[a0]) + t * float(kn_table[a1])
    return float(kn_table[keys[-1]])


def get_kn_at_angle(angle_deg: float, kn_table: dict[float, float]) -> float:
    """Return KN (m) at given heel angle; uses bilinear/interpolation rules (incl. θ < 10°)."""
    return _interp_kn(angle_deg, kn_table)


def compute_gz_curve(
    kg: float,
    kn_table: dict[float, float],
    *,
    angle_step_deg: float = 0.3,
    angle_max_deg: float = 180.0,
) -> tuple[list[float], list[float]]:
    """
    Compute GZ curve from KG and KN table.

    Args:
        kg: Centre of gravity height (m).
        kn_table: Dictionary mapping heel angle (deg) → KN (m).
        angle_step_deg: Heel angle step.
        angle_max_deg: Maximum heel angle (default 180° so tables with angles > 90° are used).

    Returns:
        (angles, gz_values): angles in degrees, GZ in metres.
        Formula: GZ(θ) = KN(θ) − KG × sin(θ).
    """
    angles: list[float] = []
    gz_values: list[float] = []
    n = int(round(angle_max_deg / angle_step_deg)) + 1
    for i in range(n):
        angle_deg = i * angle_step_deg
        if angle_deg > angle_max_deg:
            break
        theta_rad = math.radians(angle_deg)
        kn = _interp_kn(angle_deg, kn_table)
        # GZ(θ) = KN(θ) − KG × sin(θ) — no smoothing or shape enforcement
        gz = kn - kg * math.sin(theta_rad)
        angles.append(angle_deg)
        gz_values.append(gz)
    return angles, gz_values


def compute_gz_curve_stats(
    kg: float,
    kn_table: dict[float, float],
    *,
    angle_step_deg: float = 0.3,
    angle_max_deg: float = 180.0,
) -> tuple[list[float], list[float], float, float, float, float]:
    """
    Compute GZ curve and stability statistics.

    Returns:
        angles: Heel angles (deg).
        gz_values: GZ (m).
        max_gz: Maximum GZ (m).
        angle_at_max_gz: Heel angle at max GZ (deg).
        area_m_rad: Area under GZ curve from 0 to angle of vanishing stability (m·rad).
        range_positive_deg: Range of positive stability = angle of vanishing stability (deg).
    """
    angles, gz_values = compute_gz_curve(
        kg, kn_table, angle_step_deg=angle_step_deg, angle_max_deg=angle_max_deg
    )
    if not angles or not gz_values:
        return angles, gz_values, 0.0, 0.0, 0.0, 0.0

    x = np.asarray(angles, dtype=float)
    y = np.asarray(gz_values, dtype=float)
    i_max = int(np.argmax(y))
    max_gz = float(y[i_max])
    angle_at_max_gz = float(x[i_max])

    # Angle of vanishing stability (last angle where GZ > small threshold)
    positive = y > 0.02
    if not np.any(positive):
        range_positive_deg = 0.0
        area_m_rad = 0.0
    else:
        last_positive_idx = int(np.where(positive)[0][-1])
        range_positive_deg = float(x[last_positive_idx])
        # Area under curve: integral of GZ d(angle in rad) from 0 to range_positive_deg
        x_rad = np.radians(x[: last_positive_idx + 1])
        y_sub = y[: last_positive_idx + 1]
        area_m_rad = float(_trapz(y_sub, x_rad)) if _trapz is not None else 0.0

    return angles, gz_values, max_gz, angle_at_max_gz, area_m_rad, range_positive_deg


# ---- KN tables from Excel (self-contained, no kn_curves dependency) ----

# Cache keyed by Excel path string; value is (draft->(disp, heel, kz_matrix), file_mtime)
_KN_TABLE_CACHE: dict[str, tuple[dict[float, tuple[np.ndarray, np.ndarray, np.ndarray]], float]] = {}


def _get_kz_tables_path() -> Path | None:
    """Locate the bundled KN tables Excel file (supports old KZ name as fallback)."""
    try:
        from senashipping_app.config.settings import Settings
        settings = Settings.default()
    except Exception:
        return None
    assets_root = settings.project_root / "assets"
    kn_candidate = assets_root / "KN tables.xlsx"
    if kn_candidate.exists():
        return kn_candidate
    kz_candidate = assets_root / "KZ tables.xlsx"
    return kz_candidate if kz_candidate.exists() else None


def _normalize_header(name: str) -> str:
    return str(name).replace("\n", " ").strip().lower()


def _iter_numeric_draft_sheets(path: Path) -> dict[float, str]:
    """
    Return mapping trim_m -> sheet_name for all sheets whose name parses as a float.

    In these KN tables, each sheet is labelled by **trim** in metres, e.g. '0.00', '0.50'.
    """
    import pandas as pd

    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return {}
    out: dict[float, str] = {}
    for name in xl.sheet_names:
        s = str(name).strip()
        try:
            trim_val = float(s)
        except ValueError:
            continue
        out[trim_val] = name
    return out


def _load_kn_matrix(sheet_name: str, path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """
    Load one sheet: (primary_axis, heel_deg, kz_matrix). Returns None on failure.

    The primary axis is taken from the **draft** column when present (per‑row drafts),
    and only falls back to the displacement column when no draft column exists.
    """
    import pandas as pd
    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
    except Exception:
        return None
    if df.empty:
        return None
    df = df.copy()
    original_columns = list(df.columns)
    df.columns = [_normalize_header(c) for c in df.columns]

    # Prefer a dedicated draft column for the primary axis; ignore displacement
    # when per‑row drafts are available. This matches KN tables where rows are
    # tabulated by draft rather than displacement.
    disp_col = None
    for c in df.columns:
        if "displac" in c:
            disp_col = c
            break
    draft_col = None
    for c in df.columns:
        if "draft" in c:
            draft_col = c
            break
    primary_col = draft_col or disp_col or df.columns[0]

    angle_cols: list[str] = []
    angle_vals: list[float] = []
    for norm_name in df.columns:
        if norm_name == primary_col or norm_name == draft_col:
            continue
        digits = "".join(ch for ch in norm_name if (ch.isdigit() or ch in ".-"))
        try:
            ang = float(digits) if digits else None
        except (TypeError, ValueError):
            ang = None
        # Accept KN columns for a wider range of heel angles (0–180°) so
        # the curve can extend beyond 90° when the Excel file provides it.
        if ang is None or not (0 <= ang <= 180):
            continue
        has_kn_kz = "kn" in norm_name or "kz" in norm_name
        has_angle_hint = "deg" in norm_name or "degree" in norm_name or "°" in norm_name
        # Be tolerant of headers like "0.0°" or "3.0�": accept when the
        # name starts with the numeric part even if extra symbols follow.
        if (
            has_kn_kz
            or has_angle_hint
            or digits == norm_name.strip()
            or norm_name.strip().startswith(digits)
        ):
            angle_cols.append(norm_name)
            angle_vals.append(float(ang))

    if not angle_cols:
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, header=1)
        except Exception:
            return None
        if df.empty:
            return None
        df.columns = [_normalize_header(c) for c in df.columns]
        disp_col = next((c for c in df.columns if "displac" in c), None)
        draft_col = next((c for c in df.columns if "draft" in c), None)
        primary_col = draft_col or disp_col or df.columns[0]
        angle_cols, angle_vals = [], []
        for norm_name in df.columns:
            if norm_name == primary_col or norm_name == draft_col:
                continue
            digits = "".join(ch for ch in norm_name if (ch.isdigit() or ch in ".-"))
            try:
                ang = float(digits) if digits else None
            except (TypeError, ValueError):
                ang = None
            # Same widened 0–180° acceptance for the header-row+1 fallback.
            if ang is None or not (0 <= ang <= 180):
                continue
            has_kn_kz = "kn" in norm_name or "kz" in norm_name
            has_angle_hint = "deg" in norm_name or "degree" in norm_name or "°" in norm_name
            if (
                has_kn_kz
                or has_angle_hint
                or digits == norm_name.strip()
                or norm_name.strip().startswith(digits)
            ):
                angle_cols.append(norm_name)
                angle_vals.append(float(ang))
    if not angle_cols:
        return None

    # Primary axis values: use draft when available, otherwise displacement.
    primary_series = pd.to_numeric(df[primary_col], errors="coerce")
    primary_values = np.asarray(primary_series, dtype=float)
    valid = np.isfinite(primary_values)
    primary_values = primary_values[valid]

    # Keep KN columns aligned with primary-axis rows (same row index = same condition)
    kz_cols: list[np.ndarray] = []
    used_angle_vals: list[float] = []
    for c, ang in zip(angle_cols, angle_vals):
        col = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        if col.size != len(valid):
            continue
        col = col[valid]
        kz_cols.append(col)
        used_angle_vals.append(ang)
    if not kz_cols:
        return None
    kz_matrix = np.stack(kz_cols, axis=1)
    row_ok = np.isfinite(kz_matrix).any(axis=1)
    primary_values = primary_values[row_ok]
    kz_matrix = kz_matrix[row_ok, :]
    for j in range(kz_matrix.shape[1]):
        col = kz_matrix[:, j]
        mask = np.isfinite(col)
        if mask.any() and not mask.all():
            kz_matrix[:, j] = np.interp(primary_values, primary_values[mask], col[mask])
    disp_order = np.argsort(primary_values)
    primary_values = primary_values[disp_order]
    kz_matrix = kz_matrix[disp_order, :]
    heel = np.asarray(used_angle_vals, dtype=float)
    ang_order = np.argsort(heel)
    heel = heel[ang_order]
    kz_matrix = kz_matrix[:, ang_order]
    _, unique_idx = np.unique(heel, return_index=True)
    unique_idx = np.sort(unique_idx)
    heel = heel[unique_idx]
    kz_matrix = kz_matrix[:, unique_idx]
    if heel.size > 0 and heel[0] > 0.0:
        heel = np.concatenate(([0.0], heel))
        kz_matrix = np.concatenate([np.zeros((kz_matrix.shape[0], 1)), kz_matrix], axis=1)
    return primary_values, heel, kz_matrix


def get_kn_table_dict(displacement_t: float, draft_m: float = 0.0, trim_m: float = 0.0) -> dict[float, float] | None:
    """
    Return angle→KN dictionary for the given condition using 2D interpolation:

    - Sheets are treated as KN slices at different **trims** (sheet name = trim in m).
    - Within each sheet, rows are at different **drafts** when a draft column exists
      (preferred), otherwise different displacements.
    - We interpolate first in draft (preferred) or displacement within each sheet,
      then in mean draft between sheets.
    """
    path = _get_kz_tables_path()
    if path is None:
        return None

    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        current_mtime = 0.0

    cache_key = str(path)
    cached = _KN_TABLE_CACHE.get(cache_key)
    if cached is None or cached[1] != current_mtime:
        # Load all numeric draft sheets into the cache
        draft_to_sheet = _iter_numeric_draft_sheets(path)
        if not draft_to_sheet:
            return None
        data_by_draft: dict[float, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for draft_val, sheet_name in draft_to_sheet.items():
            data = _load_kn_matrix(sheet_name, path)
            if data is None:
                continue
            data_by_draft[draft_val] = data
        if not data_by_draft:
            return None
        _KN_TABLE_CACHE[cache_key] = (data_by_draft, current_mtime)
        draft_map = data_by_draft
    else:
        draft_map = cached[0]

    if not draft_map:
        return None

    # Sorted available trims from the KN file
    available_trims = sorted(draft_map.keys())

    # Helper: interpolate KN row in one sheet at the condition draft
    def _row_at_disp(primary_axis: np.ndarray, kz: np.ndarray) -> np.ndarray:
        """
        Interpolate along the sheet's primary axis, which is draft when available.

        We deliberately use the condition's draft_m instead of displacement_t so that
        KN selection follows the per‑row draft values from the table.
        """
        if primary_axis.size == 0 or kz.size == 0:
            return np.zeros((kz.shape[1],), dtype=float)
        # Inner interpolation follows **draft** along the sheet's primary axis.
        target = draft_m
        if target <= primary_axis[0]:
            return kz[0, :].astype(float)
        if target >= primary_axis[-1]:
            return kz[-1, :].astype(float)
        idx = int(np.searchsorted(primary_axis, target))
        i0 = max(0, idx - 1)
        i1 = min(len(primary_axis) - 1, idx)
        if i0 == i1:
            return kz[i0, :].astype(float)
        d0, d1 = float(primary_axis[i0]), float(primary_axis[i1])
        t_loc = (target - d0) / (d1 - d0) if d1 > d0 else 0.0
        return ((1.0 - t_loc) * kz[i0, :] + t_loc * kz[i1, :]).astype(float)

    # Below/above table range: clamp to nearest trim slice (outer interpolation in trim)
    trim_val = trim_m
    if trim_val <= available_trims[0]:
        disp, heel, kz = draft_map[available_trims[0]]
        row = _row_at_disp(disp, kz)
    elif trim_val >= available_trims[-1]:
        disp, heel, kz = draft_map[available_trims[-1]]
        row = _row_at_disp(disp, kz)
    else:
        # Find bracketing trims
        lower_trim = max(d for d in available_trims if d <= trim_val)
        upper_trim = min(d for d in available_trims if d >= trim_val)
        if abs(upper_trim - lower_trim) < 1e-6:
            disp, heel, kz = draft_map[lower_trim]
            row = _row_at_disp(disp, kz)
        else:
            disp_lo, heel_lo, kz_lo = draft_map[lower_trim]
            disp_hi, heel_hi, kz_hi = draft_map[upper_trim]
            # Assume same heel grid across sheets; if not, bail out to lower sheet only.
            if heel_lo.shape != heel_hi.shape or not np.allclose(heel_lo, heel_hi, equal_nan=False):
                disp, heel, kz = disp_lo, heel_lo, kz_lo
                row = _row_at_disp(disp, kz)
            else:
                row_lo = _row_at_disp(disp_lo, kz_lo)
                row_hi = _row_at_disp(disp_hi, kz_hi)
                t = (trim_val - lower_trim) / (upper_trim - lower_trim)
                row = (1.0 - t) * row_lo + t * row_hi
                heel = heel_lo

    if row.size == 0:
        return None

    # 2) Column names and interpolated row: select by column name dynamically (no fixed index).
    column_names = [_angle_to_column_name(float(heel[j])) for j in range(len(heel))]
    interpolated_row: dict[str, float] = {}
    for j in range(len(heel)):
        column_name = column_names[j]
        kn_value = float(row[j])
        interpolated_row[column_name] = kn_value

    # Full angle→KN dict (numeric keys for _interp_kn); support string key "10°" via KNTable.
    out_numeric = {float(heel[j]): float(row[j]) for j in range(len(heel))}
    return _KNTable(out_numeric, interpolated_row)


def make_kn_function(kn_table: dict[float, float]) -> Callable[[float], float]:
    """
    Return KN as a function of angle: callable theta_deg -> KN (m).
    Interpolates between nearest angle columns; for θ < 10° uses KN(10°)×(θ/10).
    """
    return lambda angle_deg: _interp_kn(angle_deg, kn_table)


def _sanitize_for_spline(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Remove NaN, sort by x, and merge duplicate x so spline interpolators don't fail."""
    mask = np.isfinite(x) & np.isfinite(y)
    if not np.all(mask):
        x, y = x[mask].copy(), y[mask].copy()
    if len(x) < 2:
        return x, y
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    # Keep unique x (first y per x)
    _, idx = np.unique(x, return_index=True)
    idx = np.sort(idx)
    x = x[idx]
    y = y[idx]
    return x, y


def _knot_points_for_smooth_display(
    x: np.ndarray, y: np.ndarray, knot_spacing_deg: float = 2.0
) -> tuple[np.ndarray, np.ndarray]:
    """
    Reduce to ~45 knot points (e.g. every 2°) so the spline draws a smooth curve
    instead of following piecewise-linear segments from a sparse table.
    """
    x_end = float(x[-1])
    if x_end <= 0:
        return x, y
    knot_angles = np.arange(0.0, x_end + 0.5 * knot_spacing_deg, knot_spacing_deg)
    if len(knot_angles) < 3:
        return x, y
    knot_gz = np.interp(knot_angles, x, y)
    return knot_angles, knot_gz


def _smooth_display_points(
    x: np.ndarray, y: np.ndarray, num_points: int = 2000
) -> tuple[np.ndarray, np.ndarray]:
    """Dense points for smooth curve display only; stats still from raw (x, y)."""
    if len(x) < 2 or len(x) != len(y):
        return x, y
    # For display, stop at the angle where GZ returns to zero so the right‑hand
    # side of the curve tapers back cleanly instead of running flat along GZ = 0.
    x_use = np.asarray(x, dtype=float)
    y_use = np.asarray(y, dtype=float)
    if np.any(y_use > 0.0):
        pos_idx = np.where(y_use > 0.0)[0]
        last_pos = int(pos_idx[-1])
        # If there is a point after the last positive value, interpolate the
        # exact zero‑crossing between last_pos and last_pos + 1 and include it
        # as the final knot so the curve visually reaches GZ = 0.
        if last_pos < len(y_use) - 1:
            y0, y1 = float(y_use[last_pos]), float(y_use[last_pos + 1])
            x0, x1 = float(x_use[last_pos]), float(x_use[last_pos + 1])
            if y0 > 0.0 and y1 <= 0.0 and x1 > x0:
                # Linear interpolation for θ_zero where GZ crosses zero
                t = y0 / (y0 - y1) if (y0 - y1) != 0.0 else 1.0
                x_zero = x0 + t * (x1 - x0)
                x_use = np.concatenate([x_use[: last_pos + 1], np.array([x_zero])])
                y_use = np.concatenate([y_use[: last_pos + 1], np.array([0.0])])
            else:
                x_use = x_use[: last_pos + 1]
                y_use = y_use[: last_pos + 1]
        else:
            x_use = x_use[: last_pos + 1]
            y_use = y_use[: last_pos + 1]
    x_use, y_use = _sanitize_for_spline(x_use, y_use)
    if len(x_use) < 2:
        return x, y
    # Use knot points every 1° (~77 knots) so the spline draws a smooth curve even when
    # the table has only 10 angles; then evaluate at many points for a smooth line
    x_knot, y_knot = _knot_points_for_smooth_display(x_use, y_use, knot_spacing_deg=1.0)
    x_fine = np.linspace(float(x_use[0]), float(x_use[-1]), num_points)
    # Prefer shape-preserving Pchip, then cubic spline (smooth curve; requires scipy)
    try:
        from scipy.interpolate import PchipInterpolator
        interp = PchipInterpolator(x_knot, y_knot)
        y_fine = np.maximum(0.0, interp(x_fine))
        # Force the curve to end exactly at GZ = 0 at the last angle
        end_angle = float(x_use[-1])
        end_idx = int(np.argmin(np.abs(x_fine - end_angle)))
        y_fine[end_idx:] = 0.0
        _LOG.info("GZ curve: smooth interpolation (Pchip), %d knots -> %d points", len(x_knot), len(x_fine))
        # Trim any trailing flat segment beyond the zero-crossing for cleaner display
        return x_fine[: end_idx + 1], y_fine[: end_idx + 1]
    except Exception as e:
        _LOG.debug("Pchip failed for GZ smooth display: %s", e)
    try:
        from scipy.interpolate import CubicSpline
        cs = CubicSpline(x_knot, y_knot)
        y_fine = np.maximum(0.0, cs(x_fine))
        end_angle = float(x_use[-1])
        end_idx = int(np.argmin(np.abs(x_fine - end_angle)))
        y_fine[end_idx:] = 0.0
        _LOG.info("GZ curve: smooth interpolation (CubicSpline), %d knots -> %d points", len(x_knot), len(x_fine))
        return x_fine[: end_idx + 1], y_fine[: end_idx + 1]
    except Exception as e:
        _LOG.debug("CubicSpline failed for GZ smooth display: %s", e)
    try:
        from scipy.interpolate import interp1d
        f = interp1d(x_knot, y_knot, kind="cubic", bounds_error=False, fill_value=(y_knot[0], y_knot[-1]))
        y_fine = np.maximum(0.0, f(x_fine))
        end_angle = float(x_use[-1])
        end_idx = int(np.argmin(np.abs(x_fine - end_angle)))
        y_fine[end_idx:] = 0.0
        _LOG.info("GZ curve: smooth interpolation (cubic interp1d), %d knots -> %d points", len(x_knot), len(x_fine))
        return x_fine[: end_idx + 1], y_fine[: end_idx + 1]
    except Exception as e:
        _LOG.debug("interp1d cubic failed for GZ smooth display: %s", e)
    # Fallback: dense linear; install scipy for a smooth curve
    _LOG.warning(
        "GZ curve: piecewise linear (no scipy). Install scipy for smooth curve: pip install scipy"
    )
    y_fine = np.maximum(0.0, np.interp(x_fine, x_use, y_use))
    end_angle = float(x_use[-1])
    end_idx = int(np.argmin(np.abs(x_fine - end_angle)))
    y_fine[end_idx:] = 0.0
    return x_fine[: end_idx + 1], y_fine[: end_idx + 1]


def prepare_gz_curve_display_points(
    angles: list[float],
    gz_values: list[float],
) -> tuple[list[float], list[float]]:
    """
    Public helper for display-only GZ curves.

    Uses the same smoothing and zero-cross handling as the Curves view so that
    other outputs (e.g. PDF reports) can render a visually identical curve
    without duplicating the interpolation logic.
    """
    x = np.asarray(angles, dtype=float)
    y = np.asarray(gz_values, dtype=float)
    if x.size == 0 or y.size == 0:
        return [], []
    x_plot, y_plot = _smooth_display_points(x, y)
    return [float(a) for a in x_plot], [float(g) for g in y_plot]


def estimate_gm_from_gz_curve(
    angles_deg: list[float] | np.ndarray,
    gz_values: list[float] | np.ndarray,
    *,
    max_angle_deg: float = 10.0,
) -> float | None:
    """
    Estimate GM (m) from the initial slope of the GZ curve, using the
    standard graphical construction where GM ≈ dGZ/dφ at φ = 0 (φ in radians).

    The fit is performed in (φ_rad, GZ) space over small heel angles so
    the result matches what you would obtain by drawing a tangent at
    the origin and reading off GZ at 1 radian.
    """
    x = np.asarray(angles_deg, dtype=float)
    y = np.asarray(gz_values, dtype=float)
    if x.size < 2 or x.size != y.size:
        return None

    phi = np.radians(x)
    mask = (phi > 0.0) & (x <= float(max_angle_deg)) & np.isfinite(y)
    if not np.any(mask):
        return None

    phi_small = phi[mask]
    gz_small = y[mask]
    if phi_small.size == 0 or not np.all(np.isfinite(phi_small)) or not np.all(np.isfinite(gz_small)):
        return None

    # Prefer a least‑squares fit through all small‑angle points; fall back
    # to a simple ratio GZ/φ when only one point is available.
    try:
        if phi_small.size >= 3:
            coeffs = np.polyfit(phi_small, gz_small, 1)
            gm = float(coeffs[0])
        else:
            gm = float(gz_small[0] / phi_small[0]) if phi_small[0] > 0.0 else float("nan")
    except Exception:
        return None

    if not np.isfinite(gm) or gm <= 0.0:
        return None
    return gm


def plot_gz_curve(
    angles: list[float],
    gz_values: list[float],
    *,
    ax: Any | None = None,
    xlabel: str = "Heel Angle (deg)",
    ylabel: str = "GZ (m)",
    title: str = "GZ curve",
    show_grid: bool = True,
    show_zero_line: bool = True,
    smooth_display: bool = True,
    show_max_marker: bool = True,
    show_area_shade: bool = True,
    max_gz: float | None = None,
    angle_at_max_gz: float | None = None,
    range_positive_deg: float | None = None,
    area_m_rad: float | None = None,
    show_stats: bool = True,
    gm_value: float | None = None,
) -> Any:
    """
    Plot GZ curve. Underlying data and stats are from the given (angles, gz_values).
    If smooth_display is True, the line and fill are drawn with a smooth curve for presentation.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        ax = plt.gca()

    x = np.asarray(angles, dtype=float)
    y = np.asarray(gz_values, dtype=float)

    # GM for graphical construction: prefer the condition's GM value (from the
    # stability solver / Results view) so all views and reports stay aligned.
    # Only fall back to estimating GM from the GZ curve when no positive GM
    # was provided.
    gm_for_display: float | None = None
    gm_from_curve = estimate_gm_from_gz_curve(x, y)
    if gm_value is not None and gm_value > 0.0:
        gm_for_display = float(gm_value)
    elif gm_from_curve is not None and gm_from_curve > 0.0:
        gm_for_display = gm_from_curve

    # Optional quality diagnostic: compare the small-angle slope of the GZ curve
    # against the GM from the condition. Large discrepancies can indicate issues
    # with the KN tables (e.g. wrong draft/trim slice or inconsistent data).
    gm_quality_warning = False
    gm_quality_delta: float | None = None
    if (
        gm_value is not None
        and gm_value > 0.0
        and gm_from_curve is not None
        and gm_from_curve > 0.0
    ):
        gm_quality_delta = abs(float(gm_from_curve) - float(gm_value))
        if gm_quality_delta > 0.05:
            gm_quality_warning = True
            _LOG.warning(
                "GZ curve GM consistency warning: GM(condition)=%.4f, GM(from GZ slope)=%.4f, Δ=%.4f m",
                float(gm_value),
                float(gm_from_curve),
                gm_quality_delta,
            )

    # Range of positive stability for shading
    if range_positive_deg is None and len(y) > 0 and np.any(y > 0.02):
        pos_idx = np.where(y > 0.02)[0]
        range_positive_deg = float(x[pos_idx[-1]]) if pos_idx.size else 0.0

    # Points used for drawing (smooth curve for display only; stats stay from raw)
    x_plot, y_plot = _smooth_display_points(x, y) if smooth_display and len(x) >= 2 else (x, y)

    # Shade positive area (up to the vanishing-stability angle where GZ returns to zero).
    if show_area_shade and len(x_plot) > 0 and np.any(y_plot > 0):
        end_deg = range_positive_deg if range_positive_deg is not None else float(x_plot[-1])
        mask = x_plot <= end_deg
        x_shade = x_plot[mask]
        y_shade = np.maximum(0.0, y_plot[mask])
        ax.fill_between(
            x_shade,
            0.0,
            y_shade,
            color="#cbe7ff",  # slightly softer light blue fill
            alpha=0.55,
            label="Stability energy",
        )

    # Curve (smooth line for display when requested; antialiased, rounded joins)
    ax.plot(
        x_plot,
        y_plot,
        color="#1f2a44",
        linewidth=2.0,
        label="GZ",
        antialiased=True,
        solid_capstyle="round",
        solid_joinstyle="round",
    )

    # Mark max GZ point
    if show_max_marker and len(y) > 0:
        if angle_at_max_gz is None or max_gz is None:
            i_max = int(np.argmax(y))
            angle_at_max_gz = float(x[i_max])
            max_gz = float(y[i_max])
        ax.plot(angle_at_max_gz, max_gz, "o", color="crimson", markersize=8, zorder=5)
        ax.axvline(angle_at_max_gz, color="gray", linestyle="--", alpha=0.6)
        ax.axhline(max_gz, color="gray", linestyle="--", alpha=0.6)
        ax.annotate(f"GZmax = {max_gz:.3f} m\n{angle_at_max_gz:.1f}°", xy=(angle_at_max_gz, max_gz),
                    xytext=(10, 10), textcoords="offset points", fontsize=8,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.8))

    # Stats text box
    if show_stats and len(y) > 0:
        i_m = int(np.argmax(y))
        _max_gz = float(y[i_m])
        _angle_max = float(x[i_m])
        pos = np.where(y > 0.02)[0]
        _range_deg = float(x[pos[-1]]) if pos.size else 0.0
        _area = float(_trapz(y[: pos[-1] + 1], np.radians(x[: pos[-1] + 1]))) if pos.size and _trapz is not None else 0.0
        if max_gz is not None:
            _max_gz = max_gz
        if angle_at_max_gz is not None:
            _angle_max = angle_at_max_gz
        if range_positive_deg is not None:
            _range_deg = range_positive_deg
        if area_m_rad is not None:
            _area = area_m_rad
        text = (
            f"Max GZ = {_max_gz:.3f} m\n"
            f"Angle at max GZ = {_angle_max:.1f}°\n"
            f"Area = {_area:.4f} m·rad\n"
            f"Range of positive stability = {_range_deg:.1f}°"
        )
        if gm_quality_warning and gm_quality_delta is not None:
            text += f"\nGM/GZ slope mismatch > 0.05 m (Δ = {gm_quality_delta:.3f} m)"
        ax.text(0.02, 0.98, text, transform=ax.transAxes, fontsize=8, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    # Axes, labels, and grid styling
    ax.set_facecolor("#f8fafc")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if show_grid:
        ax.grid(True, linestyle="--", alpha=0.5, color="#d0d7e2", linewidth=0.8)
    if show_zero_line:
        ax.axhline(0.0, color="#9ca3af", linestyle="-", linewidth=0.9)

    # Slight zoom‑out so the curve, GM guides, and labels do not touch the frame
    try:
        x_max_val = float(x_plot[-1]) if len(x_plot) else 90.0
        y_max_val = float(np.max(y_plot)) if len(y_plot) else 1.0
        # Give more headroom so the GM line, its label, and all ticks are clearly visible.
        x_right = max(10.0, x_max_val * 1.05)
        y_top = max(0.5, y_max_val * 1.20)
        # Ensure the GM value itself is comfortably inside the Y‑range when provided.
        if gm_for_display is not None and gm_for_display > 0.0:
            y_top = max(y_top, float(gm_for_display) * 1.25)
        ax.set_xlim(left=0.0, right=x_right)
        ax.set_ylim(bottom=0.0, top=y_top)
    except Exception:
        ax.set_xlim(left=0.0)
        ax.set_ylim(bottom=0.0)

    # Geometric guides at 90° heel: GM-based reference using the small-angle
    # tangent GZ ≈ GM·φ (φ in radians).
    try:
        # Use current axis limits so guides stay within the visible frame.
        x_min, x_max_ax = ax.get_xlim()
        y_min, y_max_ax = ax.get_ylim()
        if x_max_ax > x_min and y_max_ax > y_min:
            # Vertical guide at φ = 1 radian (≈57.3°), clamped to the visible X‑range.
            import math as _math
            one_rad_deg = _math.degrees(1.0)
            x_guide = min(one_rad_deg, x_max_ax)
            guide_color = "#9ca3af"
            # Vertical dotted line at φ = 1 radian (≈57.3°) or at the right edge if < 90.
            ax.vlines(
                x_guide,
                0.0,
                y_max_ax,
                colors=guide_color,
                linestyles=":",
                linewidth=1.6,
            )

            # GM-based reference curve and horizontal GM line: small-angle tangent
            # GZ_ref(φ) = GM · φ, using the GM passed in from the condition/results
            # so the initial slope at the origin is exactly GM (φ in radians).
            if gm_for_display is not None and gm_for_display > 0.0:
                import numpy as _np

                # Horizontal line at GZ = GM for quick visual reference.
                ax.axhline(
                    gm_for_display,
                    color=guide_color,
                    linestyle="--",
                    linewidth=1.0,
                )

                angles_ref = _np.linspace(0.0, x_guide, 180)
                phi_rad = _np.radians(angles_ref)
                gz_ref = _np.asarray(gm_for_display, dtype=float) * phi_rad
                # Clip to visible Y-range.
                gz_ref = _np.clip(gz_ref, 0.0, y_max_ax)
                ax.plot(
                    angles_ref,
                    gz_ref,
                    color=guide_color,
                    linestyle=":",
                    linewidth=1.1,
                    label=None,
                )

                # Mark and label the GM-based reference value at φ = 1 radian,
                # where the tangent gives GZ(1 rad) = GM.
                gz_at_one_rad = float(gm_for_display)
                gz_at_one_rad = max(0.0, min(gz_at_one_rad, y_max_ax))
                ax.plot(
                    [x_guide],
                    [gz_at_one_rad],
                    marker="o",
                    markersize=4,
                    color=guide_color,
                )

            # Label the 1 radian heel angle on the X‑axis directly under the guide.
            ax.annotate(
                "ϕ = 1 rad",
                xy=(x_guide, 0.0),
                xycoords="data",
                xytext=(0, -14),
                textcoords="offset points",
                ha="center",
                va="top",
                fontsize=8,
                color="#4b5563",
            )
            # Label GM near the tangent reference point at φ = 1 rad, if GM is provided.
            if gm_for_display is not None and gz_at_one_rad > 0.0:
                ax.text(
                    x_guide,
                    gz_at_one_rad * 1.05,
                    f"GM = {gm_for_display:.2f} m",
                    rotation=0,
                    ha="right",
                    va="bottom",
                    fontsize=8,
                    color="#4b5563",
                    bbox=dict(
                        boxstyle="round,pad=0.2",
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.8,
                    ),
                )
    except Exception:
        # If anything goes wrong while drawing guides, skip them silently.
        pass

    return ax


def plot_gz_curve_from_kg(
    kg: float,
    kn_table: dict[float, float],
    *,
    ax: Any | None = None,
    **kwargs: Any,
) -> Any:
    """
    Compute GZ curve from KG and KN table, then plot.

    Call again with a new kg to update the plot (e.g. when KG changes).
    """
    angles, gz_values = compute_gz_curve(kg, kn_table)
    return plot_gz_curve(angles, gz_values, ax=ax, **kwargs)


class GZCurvePlot:
    """
    Matplotlib GZ curve plot that updates when KG changes.

    Usage:
        fig, ax = plt.subplots()
        plotter = GZCurvePlot(kn_table, ax=ax)
        plotter.update(kg=7.5)
        plt.show()
        # When KG changes:
        plotter.update(kg=7.8)
    """

    def __init__(
        self,
        kn_table: dict[float, float],
        *,
        ax: Any | None = None,
        **plot_kwargs: Any,
    ) -> None:
        import matplotlib.pyplot as plt
        self._kn_table = dict(kn_table)
        self._ax = ax if ax is not None else plt.gca()
        self._plot_kwargs = plot_kwargs

    def update(self, kg: float) -> None:
        """Recompute GZ curve for the given KG and update the plot."""
        angles, gz_values = compute_gz_curve(kg, self._kn_table)
        self._ax.clear()
        plot_gz_curve(
            angles,
            gz_values,
            ax=self._ax,
            **self._plot_kwargs,
        )
        self._ax.figure.canvas.draw_idle()
