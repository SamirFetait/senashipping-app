"""
File service for saving and loading condition files.

Supports JSON format for condition files and Excel import/export.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from senashipping_app.models import LoadingCondition


def save_condition_to_file(filepath: Path, condition: LoadingCondition) -> None:
    """
    Save a loading condition to a JSON file.
    
    Args:
        filepath: Path where to save the file
        condition: The condition to save
    """
    data = {
        "name": condition.name,
        "voyage_id": condition.voyage_id,
        "tank_volumes_m3": condition.tank_volumes_m3,
        "pen_loadings": getattr(condition, "pen_loadings", {}) or {},
        # Optional detailed weights so that pen/tank weights are restored exactly as seen on screen
        "pen_mass_per_head_t": getattr(condition, "pen_mass_per_head_t", {}) or {},
        "tank_weights_mt": getattr(condition, "tank_weights_mt", {}) or {},
        "displacement_t": condition.displacement_t,
        "draft_m": condition.draft_m,
        "trim_m": condition.trim_m,
        "gm_m": condition.gm_m,
        "estimated_time_days": getattr(condition, "estimated_time_days", 0.0),
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _dict_str_keys_to_int(
    raw: Dict[str, float] | Dict[int, float] | None,
) -> Dict[int, float]:
    """Normalize dict from JSON (string keys) to int keys for tank_volumes_m3 / pen_loadings."""
    if not raw:
        return {}
    out: Dict[int, float] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def load_condition_from_file(filepath: Path) -> LoadingCondition:
    """
    Load a loading condition from a JSON file.
    JSON keys for tank_volumes_m3 and pen_loadings are normalized to int.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw_volumes = data.get("tank_volumes_m3") or {}
    raw_pen = data.get("pen_loadings") or {}
    raw_pen_mass = data.get("pen_mass_per_head_t") or {}
    raw_tank_w = data.get("tank_weights_mt") or {}
    tank_volumes_m3 = _dict_str_keys_to_int(
        raw_volumes if isinstance(raw_volumes, dict) else {}
    )
    pen_loadings_raw = _dict_str_keys_to_int(
        raw_pen if isinstance(raw_pen, dict) else {}
    )
    pen_loadings = {k: int(v) for k, v in pen_loadings_raw.items()}
    pen_mass_per_head = _dict_str_keys_to_int(
        raw_pen_mass if isinstance(raw_pen_mass, dict) else {}
    )
    tank_weights_mt = _dict_str_keys_to_int(
        raw_tank_w if isinstance(raw_tank_w, dict) else {}
    )
    return LoadingCondition(
        id=None,
        voyage_id=data.get("voyage_id"),
        name=data.get("name", "Loaded Condition"),
        tank_volumes_m3=tank_volumes_m3,
        pen_loadings=pen_loadings,
        pen_mass_per_head_t=pen_mass_per_head,
        tank_weights_mt=tank_weights_mt,
        displacement_t=float(data.get("displacement_t", 0.0)),
        draft_m=float(data.get("draft_m", 0.0)),
        trim_m=float(data.get("trim_m", 0.0)),
        gm_m=float(data.get("gm_m", 0.0)),
        estimated_time_days=float(data.get("estimated_time_days", 0.0) or 0.0),
    )
