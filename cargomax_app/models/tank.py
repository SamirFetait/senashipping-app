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
class Tank:
    id: int | None = None
    ship_id: int | None = None
    name: str = ""
    description: str = ""

    # Total usable capacity in cubic metres
    capacity_m3: float = 0.0
    density_t_per_m3: float = 0.0

    # Basic classification (cargo / ballast / fuel / etc.)
    tank_type: TankType = TankType.CARGO
    # Loading condition tab: Water Ballast, Fresh Water, Heavy Fuel Oil, Diesel Oil, Lube Oil, Misc. Tanks, Dung, Fodder Hold, Spaces
    category: str = "Misc. Tanks"

    # Simple longitudinal position for now (relative 0–1)
    longitudinal_pos: float = 0.5

    # Simplified centers of gravity – can be refined to full 3D later
    kg_m: float = 0.0
    tcg_m: float = 0.0
    lcg_m: float = 0.0

    # Optional polygon from DXF (list of (x, y) in drawing units); used for deck view and selection
    outline_xy: List[Tuple[float, float]] | None = None
    deck_name: str | None = None  # deck this tank is drawn on (e.g. "A")
