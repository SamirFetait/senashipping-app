from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import logging
import math

import numpy as np
import pandas as pd

from senashipping_app.config.settings import Settings


@dataclass(slots=True)
class KzTable:
    """KZ (or KN) values as a function of heel angle and displacement.

    displacements_t: shape (N,)  – rows
    heel_deg: shape (M,)         – columns
    kz_matrix: shape (N, M) with KZ at each (displacement, heel).
    """

    displacements_t: np.ndarray
    heel_deg: np.ndarray
    kz_matrix: np.ndarray

    def interpolate_kz(self, displacement_t: float) -> Tuple[np.ndarray, np.ndarray]:
        """Return (heel_deg, KZ) at the given displacement (linear interpolation)."""
        if self.kz_matrix.size == 0 or self.displacements_t.size == 0:
            raise ValueError("KZ table is empty")

        disp = self.displacements_t
        kz = self.kz_matrix

        if displacement_t <= disp[0]:
            return self.heel_deg, kz[0, :]
        if displacement_t >= disp[-1]:
            return self.heel_deg, kz[-1, :]

        idx = int(np.searchsorted(disp, displacement_t))
        i0 = max(0, idx - 1)
        i1 = min(len(disp) - 1, idx)
        d0 = float(disp[i0])
        d1 = float(disp[i1])
        if d1 <= d0:
            return self.heel_deg, kz[i0, :]

        t = (float(displacement_t) - d0) / (d1 - d0)
        kz_interp = (1.0 - t) * kz[i0, :] + t * kz[i1, :]
        return self.heel_deg, kz_interp


_KZ_TABLE_CACHE: KzTable | None = None
_LOG = logging.getLogger(__name__)


def _get_kz_tables_path() -> Path | None:
    """Locate the bundled KZ/KN tables Excel file."""
    try:
        settings = Settings.default()
    except Exception:
        _LOG.warning("KZ tables: failed to resolve Settings.default()", exc_info=True)
        return None

    root = settings.project_root
    candidate = root / "assets" / "KZ tables.xlsx"
    if candidate.exists():
        return candidate
    _LOG.warning("KZ tables: file not found at %s", candidate)
    return None


def _normalize_header(name: str) -> str:
    return str(name).replace("\n", " ").strip().lower()


def _load_kz_table_from_excel() -> KzTable | None:
    """Load KZ (or KN) tables from the Excel file into a structured table.

    Expected layout (first sheet), matching KN tables from the manual:
      - Column 0: Displacement (intact) tonne
      - Column 1: Draft (amidships) m (ignored for GZ)
      - Columns 2..M: KN/KZ at fixed heel angles, headers like
        'KN 10.0 deg. Starb.', 'KN 20.0 deg. Starb.', etc.
      - Each row: one displacement; each KN column: value in metres.

    The parser is tolerant: it skips non-numeric columns and rows with NaNs.
    """
    path = _get_kz_tables_path()
    if path is None:
        return None

    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception:
        _LOG.warning("KZ tables: failed to read Excel %s", path, exc_info=True)
        return None

    if df.empty:
        _LOG.warning("KZ tables: Excel %s is empty", path)
        return None

    df = df.copy()
    original_columns = list(df.columns)
    df.columns = [_normalize_header(c) for c in df.columns]

    # Displacement column
    disp_col = None
    for c in df.columns:
        if "displac" in c:
            disp_col = c
            break
    if disp_col is None:
        disp_col = df.columns[0]
        _LOG.info("KZ tables: using first column '%s' as displacement", original_columns[0])

    # KN columns: headers must contain 'kn' and 'deg' and a numeric angle
    angle_cols: List[str] = []
    angle_vals: List[float] = []
    for norm_name, orig_name in zip(df.columns, original_columns):
        if norm_name == disp_col:
            continue
        if "kn" in norm_name and "deg" in norm_name:
            digits = "".join(ch for ch in norm_name if (ch.isdigit() or ch in ".-"))
            try:
                ang = float(digits)
            except (TypeError, ValueError):
                continue
            angle_cols.append(norm_name)
            angle_vals.append(ang)

    if not angle_cols:
        _LOG.warning("KZ tables: no KN/angle columns found in %s", path)
        return None

    # Displacement values
    disp_series = pd.to_numeric(df[disp_col], errors="coerce")
    disp_values = disp_series.to_numpy(dtype=float)
    valid_rows = np.isfinite(disp_values)
    disp_values = disp_values[valid_rows]

    if disp_values.size == 0:
        _LOG.warning("KZ tables: no valid displacement values")
        return None

    # KZ matrix: rows = displacement, cols = angle
    kz_cols: List[np.ndarray] = []
    for c in angle_cols:
        col = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        col = col[valid_rows]
        if col.size != disp_values.size:
            if col.size < disp_values.size:
                col = np.pad(col, (0, disp_values.size - col.size), constant_values=np.nan)
            else:
                col = col[: disp_values.size]
        kz_cols.append(col)

    kz_matrix = np.stack(kz_cols, axis=1)  # shape (N_rows, N_angles)

    # Remove rows where all KZ are NaN
    row_valid = np.isfinite(kz_matrix).any(axis=1)
    disp_values = disp_values[row_valid]
    kz_matrix = kz_matrix[row_valid, :]

    if disp_values.size == 0:
        _LOG.warning("KZ tables: all rows invalid after NaN filtering")
        return None

    # Replace remaining NaNs by interpolation over displacement, per angle
    for j in range(kz_matrix.shape[1]):
        col = kz_matrix[:, j]
        mask = np.isfinite(col)
        if not mask.any() or mask.all():
            continue
        kz_matrix[:, j] = np.interp(
            x=disp_values,
            xp=disp_values[mask],
            fp=col[mask],
        )

    # Sort by displacement and angle
    disps_sorted_idx = np.argsort(disp_values)
    disps_sorted = disp_values[disps_sorted_idx]
    kz_sorted = kz_matrix[disps_sorted_idx, :]

    heel = np.asarray(angle_vals, dtype=float)
    idx_angles = np.argsort(heel)
    heel_sorted = heel[idx_angles]
    kz_sorted = kz_sorted[:, idx_angles]

    # Ensure 0° is included as GZ = 0 (prepend column)
    if heel_sorted[0] > 0.0:
        heel_sorted = np.concatenate(([0.0], heel_sorted))
        kz_sorted = np.concatenate(
            [np.zeros((kz_sorted.shape[0], 1)), kz_sorted],
            axis=1,
        )

    table = KzTable(
        displacements_t=disps_sorted,
        heel_deg=heel_sorted,
        kz_matrix=kz_sorted,
    )
    _LOG.info(
        "KZ tables: loaded %d heel angles and %d displacement columns from %s",
        table.heel_deg.size,
        table.displacements_t.size,
        path,
    )
    return table


def _get_kz_table() -> KzTable | None:
    global _KZ_TABLE_CACHE
    if _KZ_TABLE_CACHE is not None:
        return _KZ_TABLE_CACHE

    table = _load_kz_table_from_excel()
    if table is None:
        _LOG.warning("KZ tables: could not load table; CurvesView will fall back to GM-based approximation")
        return None

    _KZ_TABLE_CACHE = table
    return _KZ_TABLE_CACHE


def build_gz_curve_from_kn(
    displacement_t: float,
    kg_m: float,
    angles_deg: Sequence[int] | None = None,
) -> tuple[List[float], List[float]] | None:
    """
    Build a GZ curve (angles, GZ) using KZ/KN tables from Excel:

    GZ(φ) = KZ(φ) − KG * sin φ.
    """
    if displacement_t <= 0.0 or kg_m <= 0.0:
        return None

    table = _get_kz_table()
    if table is None:
        return None

    heel_deg, kz_vals = table.interpolate_kz(displacement_t)

    # If caller passed custom angles, interpolate onto that grid
    if angles_deg is not None:
        target_angles = np.asarray(list(angles_deg), dtype=float)
        gz_from_kz = np.interp(
            x=target_angles,
            xp=heel_deg,
            fp=kz_vals,
        )
        heel_deg = target_angles
        kz_vals = gz_from_kz

    phi_rad = np.radians(heel_deg, dtype=float)
    gz_vals = kz_vals - float(kg_m) * np.sin(phi_rad)
    gz_vals = np.maximum(0.0, gz_vals)

    return heel_deg.tolist(), gz_vals.tolist()
