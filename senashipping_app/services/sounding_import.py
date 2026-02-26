"""
Import tank sounding tables from Excel or CSV.

Expected columns: Volume (m³) or Capacity (m³); optional Sounding, VCG, LCG, TCG, Ullage (m), FSM (tonne.m).
Header names are flexible (e.g. "Capacity m^3", "Ullage m", "FSM tonne.m"). Multi-sheet Excel uses
Tank Name column as key when present so e.g. sheet "Table 1" with Tank Name "SILO" maps to ship tank SILO.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from senashipping_app.models import TankSoundingRow


# Column name variants (lowercase, strip; \n in headers normalized to space)
_SOUNDING_ALIASES = ("sounding", "sounding (m)", "sounding(m)", "sounding m", "depth", "depth (m)")
_VOLUME_ALIASES = ("volume", "volume (m³)", "volume (m3)", "volume(m³)", "vol", "capacity m^3", "capacity m3", "capacity m³")
_VCG_ALIASES = ("vcg", "vcg (m)", "vcg(m)", "vcg m", "kg", "kg (m)")
_LCG_ALIASES = ("lcg", "lcg (m)", "lcg(m)", "lcg m")
_TCG_ALIASES = ("tcg", "tcg (m)", "tcg(m)", "tcg m")
# Excel: "Ullage m", "FSM tonne.m" (or "FSM" + "tonne.m" on two lines) -> App: "UII/Snd (m)", "FSt (m-MT)"
# Headers with newlines are normalized to one space (e.g. "FSM\ntonne.m" -> "fsm tonne.m")
_ULLAGE_ALIASES = (
    "ullage",
    "ullage (m)",
    "ullage(m)",
    "ullage m",
    "ull/snd",
    "ull snd",
    "uii/snd",
    "uii/snd (m)",
    "uii snd",
    "uii snd (m)",
    "uiiage",
    "uiiage (m)",
    "uiiage(m)",
    "uiiage m",
)
_FSM_ALIASES = (
    "fsm",
    "fsm (tonne.m)",
    "fsm(tonne.m)",
    "fsm tonne.m",
    "fsm tonne m",
    "fsm tonne. m",
    "fst",
    "fst (m-mt)",
    "fst(m-mt)",
    "free surface moment",
    "free surface",
)
_TANK_NAME_ALIASES = (
    "tank",
    "tank name",
    "tankname",
    "name",
    "tank no",
    "tank no.",
    "tank id",
    "tank number",
    "tank #",
)


def _flatten_column_name(c) -> str:
    """Flatten MultiIndex or tuple column to single string (e.g. ('FSM', 'tonne.m') -> 'FSM tonne.m')."""
    if hasattr(c, "__iter__") and not isinstance(c, str):
        try:
            return " ".join(str(x).strip() for x in c).strip()
        except TypeError:
            pass
    return str(c).strip()


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to canonical names if they match known aliases.
    Fallback: if header contains 'ullage'/'uii' or 'fsm'/'fst' (e.g. 'Ullage m', 'FSM tonne.m'), map to ullage_m / fsm_mt.
    Handles MultiIndex columns (two header rows in Excel) by flattening first.
    """
    if hasattr(df.columns, "levels"):
        df = df.copy()
        df.columns = [_flatten_column_name(c) for c in df.columns]
    rename = {}
    for c in df.columns:
        raw = _flatten_column_name(c)
        key = raw.lower().replace("\n", " ").replace("\r", " ").replace("\t", " ")
        key = re.sub(r"[^\w\s.()/-]", "", key)
        key = re.sub(r"\s+", " ", key).strip()
        if key in _SOUNDING_ALIASES:
            rename[c] = "sounding_m"
        elif key in _VOLUME_ALIASES:
            rename[c] = "volume_m3"
        elif key in _VCG_ALIASES:
            rename[c] = "vcg_m"
        elif key in _LCG_ALIASES:
            rename[c] = "lcg_m"
        elif key in _TCG_ALIASES:
            rename[c] = "tcg_m"
        elif key in _ULLAGE_ALIASES:
            rename[c] = "ullage_m"
        elif key in _FSM_ALIASES:
            rename[c] = "fsm_mt"
        elif key in _TANK_NAME_ALIASES:
            rename[c] = "tank_name"
        else:
            if "ullage" in key or "uii" in key or ("snd" in key and ("uii" in key or "ull" in key)):
                rename[c] = "ullage_m"
            elif "fsm" in key or "fst" in key or ("tonne" in key and "m" in key):
                rename[c] = "fsm_mt"
    return df.rename(columns=rename)


def _parse_dataframe_to_rows(df: pd.DataFrame) -> List[TankSoundingRow] | None:
    """
    Parse a DataFrame into TankSoundingRow list.
    Full table: needs volume_m3, vcg_m, lcg_m, tcg_m (and optional ullage_m, fsm_mt).
    Relaxed (e.g. SILO): if only volume_m3 is present (and optional ullage_m, fsm_mt), use 0 for missing vcg/lcg/tcg so Ullage/FSM still interpolate from volume.
    """
    if "volume_m3" not in df.columns:
        return None
    if "sounding_m" not in df.columns:
        df = df.copy()
        df["sounding_m"] = 0.0
    has_vcg = "vcg_m" in df.columns
    has_lcg = "lcg_m" in df.columns
    has_tcg = "tcg_m" in df.columns
    has_ullage = "ullage_m" in df.columns
    has_fsm = "fsm_mt" in df.columns
    rows: List[TankSoundingRow] = []
    for _, r in df.iterrows():
        try:
            vol = float(r["volume_m3"])
            vcg = _safe_float(r.get("vcg_m", 0.0), 0.0) if has_vcg else 0.0
            lcg = _safe_float(r.get("lcg_m", 0.0), 0.0) if has_lcg else 0.0
            tcg = _safe_float(r.get("tcg_m", 0.0), 0.0) if has_tcg else 0.0
            sound = float(r["sounding_m"]) if pd.notna(r.get("sounding_m")) else 0.0
            ull = _safe_float(r.get("ullage_m", 0.0), 0.0) if has_ullage else 0.0
            fsm = _safe_float(r.get("fsm_mt", 0.0), 0.0) if has_fsm else 0.0
        except (TypeError, ValueError):
            continue
        if pd.isna(vol) or vol < 0:
            continue
        rows.append(
            TankSoundingRow(
                sounding_m=sound,
                volume_m3=vol,
                vcg_m=vcg,
                lcg_m=lcg,
                tcg_m=tcg,
                ullage_m=ull,
                fsm_mt=fsm,
            )
        )
    if not rows:
        return None
    rows.sort(key=lambda x: x.volume_m3)
    return rows


def parse_sounding_file(file_path: str | Path) -> List[TankSoundingRow]:
    """
    Parse a single sounding table from Excel (.xlsx) or CSV.

    Returns list of TankSoundingRow sorted by volume_m3.
    Raises ValueError if required columns are missing or data is invalid.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, engine="openpyxl")
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported format: {path.suffix}. Use .xlsx or .csv.")

    df = _normalize_columns(df)
    rows = _parse_dataframe_to_rows(df)
    if rows is None:
        required = {"volume_m3", "vcg_m", "lcg_m", "tcg_m"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"Missing columns: {missing}. Expected at least: Volume, VCG, LCG, TCG. Found: {list(df.columns)}"
            )
        raise ValueError("No valid numeric rows found in the file.")
    return rows


def _safe_float(val, default: float = 0.0) -> float:
    """Convert value to float; use default for NaN, None, empty string, or invalid."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    if isinstance(val, str) and not val.strip():
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _find_ullage_fsm_columns(df: pd.DataFrame) -> Tuple[str | None, str | None]:
    """Return (ullage_col_name, fsm_col_name) if found in df (by canonical name or by substring match)."""
    ull_col = None
    fsm_col = None
    if "ullage_m" in df.columns:
        ull_col = "ullage_m"
    if "fsm_mt" in df.columns:
        fsm_col = "fsm_mt"
    if ull_col is None or fsm_col is None:
        for c in df.columns:
            k = _flatten_column_name(c).lower().replace("\n", " ")
            k = re.sub(r"\s+", " ", k).strip()
            if ull_col is None and ("ullage" in k or "uii" in k):
                ull_col = c
            if fsm_col is None and ("fsm" in k or "fst" in k or ("tonne" in k and "m" in k)):
                fsm_col = c
    return (ull_col, fsm_col)


def _first_ullage_fsm(df: pd.DataFrame) -> Tuple[float, float] | None:
    """If df has ullage and/or FSM columns, return (ullage_m, fsm_mt) from the first data row (skips header rows where both are 0)."""
    ull_col, fsm_col = _find_ullage_fsm_columns(df)
    if ull_col is None and fsm_col is None:
        return None
    first_row_uf: Tuple[float, float] | None = None
    for _, r in df.iterrows():
        u = _safe_float(r.get(ull_col, 0.0), 0.0) if ull_col is not None else 0.0
        f = _safe_float(r.get(fsm_col, 0.0), 0.0) if fsm_col is not None else 0.0
        if first_row_uf is None:
            first_row_uf = (u, f)
        # Use first row that has at least one non-zero (avoids using a header row)
        if u != 0.0 or f != 0.0:
            return (u, f)
    return first_row_uf


def parse_sounding_file_all_tanks(
    file_path: str | Path,
) -> Tuple[Dict[str, List[TankSoundingRow]], Dict[str, Tuple[float, float]]]:
    """
    Parse sounding tables for multiple tanks from Excel (.xlsx) or CSV.

    - Excel with multiple sheets: each sheet name (trimmed) is the tank key.
    - Excel with one sheet: if a "Tank" / "Tank name" column exists, rows are grouped by it.
    - CSV: single table returned under key "" (empty string).

    Returns:
      - by_name: Dict[tank_identifier, List[TankSoundingRow]] for matching to ship tanks by name.
      - ullage_fsm_by_name: Dict[tank_identifier, (ullage_m, fsm_mt)] when Excel has Ullage (m) and FSM (tonne.m) columns.

    Skips sheets that lack required columns or have no valid rows.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    result: Dict[str, List[TankSoundingRow]] = {}
    ullage_fsm_by_name: Dict[str, Tuple[float, float]] = {}

    def _read_sheet_tanks(sheet_name: str, df: pd.DataFrame) -> None:
        """Parse one sheet (already loaded). Groups by tank_name if present (forward-fill so block rows match).
        Ullage/FSM are extracted even when sheet has no valid sounding rows (Volume/VCG/LCG/TCG missing).
        """
        df = _normalize_columns(df)
        if "tank_name" in df.columns:
            df = df.copy()
            df["tank_name"] = df["tank_name"].ffill()
            for tank_name, group in df.groupby("tank_name", dropna=False):
                key = str(tank_name).strip() if pd.notna(tank_name) else ""
                if not key:
                    continue
                sub = group.drop(columns=["tank_name"], errors="ignore")
                rows = _parse_dataframe_to_rows(sub)
                if rows:
                    result[key] = rows
                uf = _first_ullage_fsm(sub)
                if uf is not None:
                    ullage_fsm_by_name[key] = uf
            return
        rows = _parse_dataframe_to_rows(df)
        if rows:
            key = sheet_name.strip()
            result[key] = rows
        uf = _first_ullage_fsm(df)
        if uf is not None:
            ullage_fsm_by_name[sheet_name.strip()] = uf

    if path.suffix.lower() in (".xlsx", ".xls"):
        all_sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
        if not all_sheets:
            return result, ullage_fsm_by_name
        if len(all_sheets) == 1:
            sheet_name, df = next(iter(all_sheets.items()))
            _read_sheet_tanks(sheet_name, df)
            if not result:
                df_alt = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", header=1)
                _read_sheet_tanks(sheet_name, df_alt)
        else:
            # Use _read_sheet_tanks per sheet so "Tank Name" column (e.g. SILO) is used as key when present, not sheet name (e.g. Table 1)
            for sheet_name, df in all_sheets.items():
                _read_sheet_tanks(sheet_name, df)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        df = _normalize_columns(df)
        if "tank_name" in df.columns:
            for tank_name, group in df.groupby("tank_name", dropna=False):
                key = str(tank_name).strip() if pd.notna(tank_name) else ""
                if not key:
                    continue
                sub = group.drop(columns=["tank_name"], errors="ignore")
                rows = _parse_dataframe_to_rows(sub)
                if rows:
                    result[key] = rows
                uf = _first_ullage_fsm(sub)
                if uf is not None:
                    ullage_fsm_by_name[key] = uf
        else:
            rows = _parse_dataframe_to_rows(df)
            if rows:
                result[""] = rows
            uf = _first_ullage_fsm(df)
            if uf is not None:
                ullage_fsm_by_name[""] = uf
    else:
        raise ValueError(f"Unsupported format: {path.suffix}. Use .xlsx or .csv.")

    return result, ullage_fsm_by_name
