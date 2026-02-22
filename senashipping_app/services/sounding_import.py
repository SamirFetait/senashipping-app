"""
Import tank sounding tables from Excel or CSV.

Expected columns: Sounding (m), Volume (m³), VCG (m), LCG (m), TCG (m).
Header names are flexible (e.g. "Sounding", "Volume", "VCG", "LCG", "TCG" with or without units).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from ..models import TankSoundingRow


# Column name variants (lowercase, strip; \n in headers normalized to space)
_SOUNDING_ALIASES = ("sounding", "sounding (m)", "sounding(m)", "sounding m", "depth", "depth (m)")
_VOLUME_ALIASES = ("volume", "volume (m³)", "volume (m3)", "volume(m³)", "vol", "capacity m^3", "capacity m3", "capacity m³")
_VCG_ALIASES = ("vcg", "vcg (m)", "vcg(m)", "vcg m", "kg", "kg (m)")
_LCG_ALIASES = ("lcg", "lcg (m)", "lcg(m)", "lcg m")
_TCG_ALIASES = ("tcg", "tcg (m)", "tcg(m)", "tcg m")
_TANK_NAME_ALIASES = ("tank", "tank name", "tankname", "name")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to canonical names if they match known aliases."""
    rename = {}
    for c in df.columns:
        key = str(c).strip().lower().replace("\n", " ").replace("^", "")
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
        elif key in _TANK_NAME_ALIASES:
            rename[c] = "tank_name"
    return df.rename(columns=rename)


def _parse_dataframe_to_rows(df: pd.DataFrame) -> List[TankSoundingRow] | None:
    """
    Parse a DataFrame with canonical columns (volume_m3, vcg_m, lcg_m, tcg_m) into
    sorted TankSoundingRow list. Returns None if required columns are missing.
    """
    required = {"volume_m3", "vcg_m", "lcg_m", "tcg_m"}
    if required - set(df.columns):
        return None
    if "sounding_m" not in df.columns:
        df = df.copy()
        df["sounding_m"] = 0.0
    rows: List[TankSoundingRow] = []
    for _, r in df.iterrows():
        try:
            vol = float(r["volume_m3"])
            vcg = float(r["vcg_m"])
            lcg = float(r["lcg_m"])
            tcg = float(r["tcg_m"])
            sound = float(r["sounding_m"]) if pd.notna(r["sounding_m"]) else 0.0
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


def parse_sounding_file_all_tanks(file_path: str | Path) -> Dict[str, List[TankSoundingRow]]:
    """
    Parse sounding tables for multiple tanks from Excel (.xlsx) or CSV.

    - Excel with multiple sheets: each sheet name (trimmed) is the tank key.
    - Excel with one sheet: if a "Tank" / "Tank name" column exists, rows are grouped by it.
    - CSV: single table returned under key "" (empty string).

    Returns Dict[tank_identifier, List[TankSoundingRow]] for matching to ship tanks by name.
    Skips sheets that lack required columns or have no valid rows.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    result: Dict[str, List[TankSoundingRow]] = {}

    def _read_sheet_tanks(sheet_name: str, df: pd.DataFrame) -> None:
        """Parse one sheet (already loaded). Groups by tank_name if present (forward-fill so block rows match)."""
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
            return
        rows = _parse_dataframe_to_rows(df)
        if rows:
            result[sheet_name.strip()] = rows

    if path.suffix.lower() in (".xlsx", ".xls"):
        all_sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
        if not all_sheets:
            return result
        if len(all_sheets) == 1:
            sheet_name, df = next(iter(all_sheets.items()))
            _read_sheet_tanks(sheet_name, df)
            # If no data, try header on row 1 (row 0 = title line)
            if not result:
                df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", header=1)
                _read_sheet_tanks(sheet_name, df)
        else:
            for sheet_name, df in all_sheets.items():
                df = _normalize_columns(df)
                rows = _parse_dataframe_to_rows(df)
                if rows:
                    result[str(sheet_name).strip()] = rows
                else:
                    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", header=1)
                    df = _normalize_columns(df)
                    rows = _parse_dataframe_to_rows(df)
                    if rows:
                        result[str(sheet_name).strip()] = rows
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        df = _normalize_columns(df)
        if "tank_name" in df.columns:
            for tank_name, group in df.groupby("tank_name", dropna=False):
                key = str(tank_name).strip() if pd.notna(tank_name) else ""
                sub = group.drop(columns=["tank_name"], errors="ignore")
                rows = _parse_dataframe_to_rows(sub)
                if rows:
                    result[key] = rows
        else:
            rows = _parse_dataframe_to_rows(df)
            if rows:
                result[""] = rows
    else:
        raise ValueError(f"Unsupported format: {path.suffix}. Use .xlsx or .csv.")

    return result
