"""
Parse DXF polygons and create Tank objects.

- Extracts closed LWPOLYLINE/POLYLINE (and from INSERT blocks).
- Computes centroid and area for each polygon.
- Can create Tank model instances and persist via TankRepository.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Any

from ..models import Tank
from ..models.tank import TankType


def _polygon_area_and_centroid(points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    """Returns (area, cx, cy). Area may be negative if clockwise."""
    n = len(points)
    if n < 3:
        return 0.0, 0.0, 0.0
    area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        j = (i + 1) % n
        xi, yi = points[i]
        xj, yj = points[j]
        cross = xi * yj - xj * yi
        area += cross
        cx += (xi + xj) * cross
        cy += (yi + yj) * cross
    area *= 0.5
    if abs(area) < 1e-12:
        return abs(area), sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    cx /= 6.0 * area
    cy /= 6.0 * area
    return abs(area), cx, cy


def _get_points(entity: Any) -> List[Tuple[float, float]] | None:
    """Get 2D points from LWPOLYLINE or POLYLINE. Y flipped to match Qt (y up)."""
    try:
        pts = list(entity.get_points())
    except Exception:
        return None
    if len(pts) < 3:
        return None
    out: List[Tuple[float, float]] = []
    for p in pts:
        x = p[0] if hasattr(p, "__getitem__") else getattr(p, "x", 0.0)
        y = p[1] if hasattr(p, "__getitem__") else getattr(p, "y", 0.0)
        out.append((float(x), -float(y)))
    return out


def parse_dxf_polygons(dxf_path: Path) -> List[dict]:
    """
    Parse a DXF file and return a list of polygon dicts.

    Each dict has:
      - name: from layer or "Tank_1", "Tank_2", ...
      - outline_xy: list of (x, y) tuples
      - area: polygon area (drawing units²)
      - centroid_xy: (cx, cy)
      - closed: bool
    """
    if not dxf_path.exists():
        return []
    try:
        import ezdxf  # type: ignore[import]
    except ImportError:
        return []
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:
        return []
    msp = doc.modelspace()
    result: List[dict] = []
    idx = 0

    def process_entity(e: Any) -> None:
        nonlocal idx
        et = e.dxftype()
        if et == "LINE":
            return
        if et in ("LWPOLYLINE", "POLYLINE"):
            points = _get_points(e)
            if not points or len(points) < 3:
                return
            closed = getattr(e, "closed", False)
            if not closed:
                points = list(points)
                if points[0] != points[-1]:
                    points.append(points[0])
            area, cx, cy = _polygon_area_and_centroid(points)
            name = getattr(e.dxf, "layer", None) or f"Tank_{idx + 1}"
            idx += 1
            result.append({
                "name": name,
                "outline_xy": points,
                "area": area,
                "centroid_xy": (cx, cy),
                "closed": True,
            })
            return
        if et == "INSERT":
            try:
                for ve in e.virtual_entities():
                    process_entity(ve)
            except Exception:
                pass

    for entity in msp:
        process_entity(entity)
    return result


def tanks_from_dxf(
    dxf_path: Path,
    ship_id: int,
    deck_name: str,
    default_capacity_height_m: float = 2.0,
) -> List[Tank]:
    """
    Convert DXF polygons to Tank model instances (not persisted).

    - Uses polygon centroid for longitudinal_pos (normalized 0–1), lcg_m, tcg_m.
    - Estimates capacity_m3 from area * default_capacity_height_m (drawing units
      assumed same scale as metres; adjust if your DXF is in mm).
    """
    polygons = parse_dxf_polygons(dxf_path)
    tanks: List[Tank] = []
    for i, p in enumerate(polygons):
        outline = p["outline_xy"]
        cx, cy = p["centroid_xy"]
        area = p["area"]
        name = p.get("name") or f"Tank_{i + 1}"
        # Normalize longitudinal_pos to 0–1 if we have a known range; else use 0.5
        longitudinal_pos = 0.5
        capacity_m3 = area * default_capacity_height_m
        tanks.append(Tank(
            ship_id=ship_id,
            name=name,
            capacity_m3=max(0.0, capacity_m3),
            longitudinal_pos=longitudinal_pos,
            kg_m=default_capacity_height_m / 2.0,
            lcg_m=cx,
            tcg_m=cy,
            tank_type=TankType.CARGO,
            outline_xy=outline,
            deck_name=deck_name,
        ))
    return tanks


def create_tanks_from_dxf(
    dxf_path: Path,
    ship_id: int,
    deck_name: str,
    tank_repo: Any,
    default_capacity_height_m: float = 2.0,
) -> List[Tank]:
    """
    Parse DXF, create Tank instances, persist them, and return the list.

    tank_repo: TankRepository instance (from a live DB session).
    """
    tank_models = tanks_from_dxf(
        dxf_path, ship_id, deck_name, default_capacity_height_m
    )
    created: List[Tank] = []
    for t in tank_models:
        created.append(tank_repo.create(t))
    return created
