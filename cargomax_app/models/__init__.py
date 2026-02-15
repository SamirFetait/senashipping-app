"""
Domain models for the senashipping desktop application.

These are pure Python/domain classes, separate from ORM mappings.
"""

from .ship import Ship
from .tank import Tank, TankType
from .cargo import Cargo
from .voyage import Voyage, LoadingCondition
from .livestock_pen import LivestockPen
from .cargo_type import CargoType

__all__ = [
    "Ship",
    "Tank",
    "TankType",
    "Cargo",
    "Voyage",
    "LoadingCondition",
    "LivestockPen",
    "CargoType",
]

