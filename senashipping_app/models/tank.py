from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple


class TankType(Enum):
    CARGO = auto()
    BALLAST = auto()
    FUEL = auto()
    FRESH_WATER = auto()
    OTHER = auto()


@dataclass(slots=True)
class TankSoundingRow:
    """One row of a tank sounding table: volume and CoG (VCG, LCG, TCG) in metres."""
    sounding_m: float = 0.0
    volume_m3: float = 0.0
    vcg_m: float = 0.0
    lcg_m: float = 0.0
    tcg_m: float = 0.0


def polygon_centroid_2d(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    Return (cx, cy) centroid of a 2D polygon. Uses signed area formula.
    Empty or degenerate polygon returns (0.0, 0.0).
    """
    n = len(points)
    if n < 3:
        if n == 0:
            return 0.0, 0.0
        if n == 1:
            return points[0][0], points[0][1]
        return (points[0][0] + points[1][0]) / 2.0, (points[0][1] + points[1][1]) / 2.0
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
        return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    cx /= 6.0 * area
    cy /= 6.0 * area
    return cx, cy


@dataclass(slots=True)
class Tank:
    """
    Tank with name, polygon_coordinates (for highlighting on drawings), volume,
    lcg, vcg, tcg, max_weight, and density. Volume and LCG/VCG/TCG are set from
    STL mesh at import (Import tanks from STL). For 2D outlines use
    update_tank_centroid_from_polygon to auto-calculate lcg/tcg from polygon.
    """
    id: int | None = None
    ship_id: int | None = None
    name: str = ""
    description: str = ""

    # Total usable capacity in cubic metres (exposed as volume)
    capacity_m3: float = 0.0
    density_t_per_m3: float = 0.0

    # Basic classification (cargo / ballast / fuel / etc.)
    tank_type: TankType = TankType.CARGO
    # Loading condition tab: Water Ballast, Fresh Water, Heavy Fuel Oil, Diesel Oil, Lube Oil, Misc. Tanks, Dung, Fodder Hold, Spaces
    category: str = "Misc. Tanks"

    # Simple longitudinal position for now (relative 0–1)
    longitudinal_pos: float = 0.5

    # Centers of gravity in metres (exposed as vcg, lcg, tcg)
    kg_m: float = 0.0
    tcg_m: float = 0.0
    lcg_m: float = 0.0

    # Polygon for deck view and selection (exposed as polygon_coordinates)
    outline_xy: List[Tuple[float, float]] | None = None
    deck_name: str | None = None  # deck this tank is drawn on (e.g. "A")

    # --- Preferred API: name, polygon_coordinates, volume, lcg, vcg, tcg, max_weight, density ---

    @property
    def polygon_coordinates(self) -> List[Tuple[float, float]] | None:
        """Polygon for highlighting tank on drawings when selected."""
        return self.outline_xy

    @polygon_coordinates.setter
    def polygon_coordinates(self, value: List[Tuple[float, float]] | None) -> None:
        self.outline_xy = value

    @property
    def volume(self) -> float:
        """Tank capacity in m³."""
        return self.capacity_m3

    @volume.setter
    def volume(self, value: float) -> None:
        self.capacity_m3 = max(0.0, value)

    @property
    def vcg(self) -> float:
        """Vertical centre of gravity (m)."""
        return self.kg_m

    @vcg.setter
    def vcg(self, value: float) -> None:
        self.kg_m = value

    @property
    def lcg(self) -> float:
        """Longitudinal centre of gravity (m)."""
        return self.lcg_m

    @lcg.setter
    def lcg(self, value: float) -> None:
        self.lcg_m = value

    @property
    def tcg(self) -> float:
        """Transverse centre of gravity (m)."""
        return self.tcg_m

    @tcg.setter
    def tcg(self, value: float) -> None:
        self.tcg_m = value

    @property
    def density(self) -> float:
        """Density in t/m³."""
        return self.density_t_per_m3

    @density.setter
    def density(self, value: float) -> None:
        self.density_t_per_m3 = max(0.0, value)

    @property
    def max_weight(self) -> float:
        """Maximum weight when full: volume * density (t)."""
        return self.volume * (self.density or 0.0)


def update_tank_centroid_from_polygon(
    tank: Tank,
    vcg_default: float = 0.0,
) -> None:
    """
    Set tank LCG and TCG from polygon centroid; optionally set VCG to vcg_default.
    Use when polygon_coordinates are set (e.g. when tank is selected) to auto-fill from 2D outline; for 3D use STL (volume and LCG/VCG/TCG from mesh).
    to auto-calculate lcg, vcg, tcg.
    """
    coords = tank.polygon_coordinates
    if not coords or len(coords) < 3:
        return
    cx, cy = polygon_centroid_2d(coords)
    tank.lcg_m = cx
    tank.tcg_m = cy
    if vcg_default != 0.0:
        tank.kg_m = vcg_default
