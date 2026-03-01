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
    angle_step_deg: float = 0.25,
    angle_max_deg: float = 90.0,
) -> tuple[list[float], list[float]]:
    """
    Compute GZ curve from KG and KN table.

    Args:
        kg: Centre of gravity height (m).
        kn_table: Dictionary mapping heel angle (deg) → KN (m).
        angle_step_deg: Heel angle step (default 0.25° for smooth curve from table).
        angle_max_deg: Maximum heel angle (default 90°).

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
    angle_step_deg: float = 0.25,
    angle_max_deg: float = 90.0,
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


# ---- KN table from Excel (self-contained, no kn_curves dependency) ----

# sheet_name -> ((disp, heel, kz_matrix), file_mtime) so we reload when Excel is edited
_KN_TABLE_CACHE: dict[str, tuple[tuple[np.ndarray, np.ndarray, np.ndarray], float]] = {}


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


def _sheet_name_for_trim(path: Path, trim_m: float) -> str | None:
    """Return the sheet name that best matches trim (sheet names = trim numbers)."""
    import pandas as pd
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return None
    names = xl.sheet_names
    if not names:
        return None
    best_name, best_diff = names[0], float("inf")
    for name in names:
        s = str(name).strip()
        try:
            sheet_trim = float(s)
        except ValueError:
            continue
        diff = abs(sheet_trim - trim_m)
        if diff < best_diff:
            best_diff, best_name = diff, name
    return best_name


def _load_kn_matrix(sheet_name: str, path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Load one sheet: (displacements_t, heel_deg, kz_matrix). Returns None on failure."""
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

    disp_col = None
    for c in df.columns:
        if "displac" in c:
            disp_col = c
            break
    if disp_col is None:
        disp_col = df.columns[0]

    draft_col = None
    for c in df.columns:
        if c != disp_col and "draft" in c:
            draft_col = c
            break

    angle_cols: list[str] = []
    angle_vals: list[float] = []
    for norm_name in df.columns:
        if norm_name == disp_col or norm_name == draft_col:
            continue
        digits = "".join(ch for ch in norm_name if (ch.isdigit() or ch in ".-"))
        try:
            ang = float(digits) if digits else None
        except (TypeError, ValueError):
            ang = None
        if ang is None or not (0 <= ang <= 90):
            continue
        has_kn_kz = "kn" in norm_name or "kz" in norm_name
        has_angle_hint = "deg" in norm_name or "degree" in norm_name or "°" in norm_name
        if has_kn_kz or has_angle_hint or (digits == norm_name.strip()):
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
        disp_col = next((c for c in df.columns if "displac" in c), df.columns[0])
        draft_col = next((c for c in df.columns if c != disp_col and "draft" in c), None)
        angle_cols, angle_vals = [], []
        for norm_name in df.columns:
            if norm_name == disp_col or norm_name == draft_col:
                continue
            digits = "".join(ch for ch in norm_name if (ch.isdigit() or ch in ".-"))
            try:
                ang = float(digits) if digits else None
            except (TypeError, ValueError):
                ang = None
            if ang is None or not (0 <= ang <= 90):
                continue
            has_kn_kz = "kn" in norm_name or "kz" in norm_name
            has_angle_hint = "deg" in norm_name or "degree" in norm_name or "°" in norm_name
            if has_kn_kz or has_angle_hint or (digits == norm_name.strip()):
                angle_cols.append(norm_name)
                angle_vals.append(float(ang))
    if not angle_cols:
        return None

    disp_series = pd.to_numeric(df[disp_col], errors="coerce")
    disp_values = np.asarray(disp_series, dtype=float)
    valid = np.isfinite(disp_values)
    disp_values = disp_values[valid]

    # Keep KN columns aligned with displacement rows (same row index = same condition)
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
    disp_values = disp_values[row_ok]
    kz_matrix = kz_matrix[row_ok, :]
    for j in range(kz_matrix.shape[1]):
        col = kz_matrix[:, j]
        mask = np.isfinite(col)
        if mask.any() and not mask.all():
            kz_matrix[:, j] = np.interp(disp_values, disp_values[mask], col[mask])
    disp_order = np.argsort(disp_values)
    disp_values = disp_values[disp_order]
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
    return disp_values, heel, kz_matrix


def get_kn_table_dict(displacement_t: float, trim_m: float = 0.0) -> dict[float, float] | None:
    """
    For a given displacement: identify two bounding displacement rows; for EACH angle
    column (10°, 20°, 30°, …), interpolate KN between those two rows. Return the full
    angle→KN dictionary. When computing GZ at angle θ, use _interp_kn(θ, this_dict)
    to interpolate between nearest angle columns.
    """
    path = _get_kz_tables_path()
    if path is None:
        return None
    sheet_name = _sheet_name_for_trim(path, trim_m)
    if sheet_name is None:
        return None
    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    cached = _KN_TABLE_CACHE.get(sheet_name)
    if cached is None or cached[1] != current_mtime:
        data = _load_kn_matrix(sheet_name, path)
        if data is None:
            return None
        _KN_TABLE_CACHE[sheet_name] = (data, current_mtime)
        disp, heel, kz = data
    else:
        disp, heel, kz = cached[0]
    if disp.size == 0 or heel.size == 0:
        return None

    # 1) Identify two bounding displacement rows
    if displacement_t <= disp[0]:
        row = kz[0, :]
    elif displacement_t >= disp[-1]:
        row = kz[-1, :]
    else:
        idx = int(np.searchsorted(disp, displacement_t))
        i0 = max(0, idx - 1)
        i1 = min(len(disp) - 1, idx)
        if i0 == i1:
            row = kz[i0, :]
        else:
            d0, d1 = float(disp[i0]), float(disp[i1])
            t = (displacement_t - d0) / (d1 - d0) if d1 > d0 else 0.0
            row = (1.0 - t) * kz[i0, :] + t * kz[i1, :]

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
    x: np.ndarray, y: np.ndarray, num_points: int = 1200
) -> tuple[np.ndarray, np.ndarray]:
    """Dense points for smooth curve display only; stats still from raw (x, y)."""
    if len(x) < 2 or len(x) != len(y):
        return x, y
    # For display, stop at last positive GZ so we don't draw a flat segment on the zero axis
    x_use = np.asarray(x, dtype=float)
    y_use = np.asarray(y, dtype=float)
    if np.any(y_use > 0.0):
        pos_idx = np.where(y_use > 0.0)[0]
        last_pos = int(pos_idx[-1])
        x_use = x_use[: last_pos + 1]
        y_use = y_use[: last_pos + 1]
    x_use, y_use = _sanitize_for_spline(x_use, y_use)
    if len(x_use) < 2:
        return x, y
    # Use ~45 knot points (every 2°) so the spline draws a smooth curve even when
    # the table has only 10 angles (0,10,...,90) and raw data is piecewise linear
    x_knot, y_knot = _knot_points_for_smooth_display(x_use, y_use, knot_spacing_deg=2.0)
    x_fine = np.linspace(float(x_use[0]), float(x_use[-1]), num_points)
    # Prefer shape-preserving Pchip, then cubic spline (smooth curve from ~45 knots)
    try:
        from scipy.interpolate import PchipInterpolator
        interp = PchipInterpolator(x_knot, y_knot)
        y_fine = np.maximum(0.0, interp(x_fine))
        _LOG.info("GZ curve: smooth interpolation (Pchip), %d knots -> %d points", len(x_knot), len(x_fine))
        return x_fine, y_fine
    except Exception as e:
        _LOG.debug("Pchip failed for GZ smooth display: %s", e)
    try:
        from scipy.interpolate import CubicSpline
        cs = CubicSpline(x_knot, y_knot)
        y_fine = np.maximum(0.0, cs(x_fine))
        _LOG.info("GZ curve: smooth interpolation (CubicSpline), %d knots -> %d points", len(x_knot), len(x_fine))
        return x_fine, y_fine
    except Exception as e:
        _LOG.debug("CubicSpline failed for GZ smooth display: %s", e)
    try:
        from scipy.interpolate import interp1d
        f = interp1d(x_knot, y_knot, kind="cubic", bounds_error=False, fill_value=(y_knot[0], y_knot[-1]))
        y_fine = np.maximum(0.0, f(x_fine))
        _LOG.info("GZ curve: smooth interpolation (cubic interp1d), %d knots -> %d points", len(x_knot), len(x_fine))
        return x_fine, y_fine
    except Exception as e:
        _LOG.debug("interp1d cubic failed for GZ smooth display: %s", e)
    # Fallback: dense linear; install scipy for a smooth curve
    _LOG.warning(
        "GZ curve: piecewise linear (no scipy). Install scipy for smooth curve: pip install scipy"
    )
    y_fine = np.maximum(0.0, np.interp(x_fine, x_use, y_use))
    return x_fine, y_fine


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

    # Range of positive stability for shading
    if range_positive_deg is None and len(y) > 0 and np.any(y > 0.02):
        pos_idx = np.where(y > 0.02)[0]
        range_positive_deg = float(x[pos_idx[-1]]) if pos_idx.size else 0.0

    # Points used for drawing (smooth curve for display only; stats stay from raw)
    x_plot, y_plot = _smooth_display_points(x, y) if smooth_display and len(x) >= 2 else (x, y)

    # Shade positive area
    if show_area_shade and len(x_plot) > 0 and np.any(y_plot > 0):
        end_deg = range_positive_deg if range_positive_deg is not None else float(x_plot[-1])
        mask = x_plot <= end_deg
        x_shade = x_plot[mask]
        y_shade = np.maximum(0.0, y_plot[mask])
        ax.fill_between(x_shade, 0, y_shade, color="steelblue", alpha=0.25, label="Stability energy")

    # Curve (smooth line for display when requested; antialiased for clean rendering)
    ax.plot(x_plot, y_plot, color="#2c3e50", linewidth=2, label="GZ", antialiased=True)

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
        text = f"Max GZ = {_max_gz:.3f} m\nAngle at max GZ = {_angle_max:.1f}°\nArea = {_area:.4f} m·rad\nRange of positive stability = {_range_deg:.1f}°"
        ax.text(0.02, 0.98, text, transform=ax.transAxes, fontsize=8, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if show_grid:
        ax.grid(True, linestyle="--", alpha=0.7)
    if show_zero_line:
        ax.axhline(0.0, color="gray", linestyle="-", linewidth=0.8)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
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
