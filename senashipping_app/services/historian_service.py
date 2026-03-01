"""
Historian: persist and retrieve calculation snapshots for history/export.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

# Default columns for historian table/export (ordered)
HISTORIAN_DEFAULT_FIELDS = [
    "timestamp",
    "condition_name",
    "ship_name",
    "displacement_t",
    "draft_m",
    "trim_m",
    "gm_m",
    "kg_m",
    "km_m",
    "criteria_summary",
]

# All available fields (for field selection dialog)
HISTORIAN_ALL_FIELDS = [
    "timestamp",
    "condition_name",
    "ship_name",
    "displacement_t",
    "draft_m",
    "trim_m",
    "gm_m",
    "kg_m",
    "km_m",
    "gm_effective",
    "criteria_summary",
    "tank_volumes_m3",
    "cargo_density_t_per_m3",
]


def _snapshots_path(data_dir: Path) -> Path:
    return data_dir / "historian_snapshots.json"


def _fields_path(data_dir: Path) -> Path:
    return data_dir / "historian_fields.json"


def load_snapshots(data_dir: Path) -> List[Dict[str, Any]]:
    """Load all stored historian snapshots from JSON."""
    path = _snapshots_path(data_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("snapshots", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    except (json.JSONDecodeError, OSError):
        return []


def save_snapshot(data_dir: Path, snapshot_dict: Dict[str, Any]) -> str:
    """Append one snapshot (from CalculationSnapshot.to_dict()) and save. Returns id."""
    path = _snapshots_path(data_dir)
    snapshots = load_snapshots(data_dir)
    sid = str(uuid.uuid4())[:8]
    record = {"id": sid, **snapshot_dict}
    snapshots.append(record)
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"snapshots": snapshots}, f, indent=2)
    return sid


def load_field_selection(data_dir: Path) -> List[str]:
    """Load which fields are selected for historian view/export."""
    path = _fields_path(data_dir)
    if not path.exists():
        return list(HISTORIAN_DEFAULT_FIELDS)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        fields = data.get("fields", data) if isinstance(data, dict) else data
        return [f for f in fields if f in HISTORIAN_ALL_FIELDS] or list(HISTORIAN_DEFAULT_FIELDS)
    except (json.JSONDecodeError, OSError):
        return list(HISTORIAN_DEFAULT_FIELDS)


def save_field_selection(data_dir: Path, fields: List[str]) -> None:
    """Save selected historian fields."""
    path = _fields_path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fields": [f for f in fields if f in HISTORIAN_ALL_FIELDS]}, f, indent=2)


def snapshot_to_flat_row(snap: Dict[str, Any], columns: List[str]) -> Dict[str, Any]:
    """Convert a stored snapshot dict to a flat row for table/CSV using given columns."""
    row = {}
    for col in columns:
        if col == "timestamp":
            row[col] = snap.get("timestamp", "")
        elif col in ("condition_name", "ship_name", "criteria_summary"):
            row[col] = snap.get(col, "")
        elif col in ("tank_volumes_m3", "cargo_density_t_per_m3"):
            inp = snap.get("inputs") or {}
            if col == "tank_volumes_m3":
                row[col] = inp.get("tank_volumes_m3", inp)
            else:
                row[col] = inp.get("cargo_density_t_per_m3", "")
        else:
            out = snap.get("outputs") or {}
            row[col] = out.get(col, "")
    return row
