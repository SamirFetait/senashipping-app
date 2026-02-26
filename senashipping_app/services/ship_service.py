"""
Business logic for ships and their basic validation rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy.orm import Session

from senashipping_app.models import Ship
from senashipping_app.repositories.ship_repository import ShipRepository


@dataclass(slots=True)
class ShipValidationError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ShipService:
    """Encapsulates ship-related rules and operations."""

    def __init__(self, db: Session) -> None:
        self._repo = ShipRepository(db)

    def list_ships(self) -> List[Ship]:
        return self._repo.list()

    def save_ship(self, ship: Ship) -> Ship:
        self._validate(ship)
        if ship.id is None:
            return self._repo.create(ship)
        return self._repo.update(ship)

    def delete_ship(self, ship_id: int) -> None:
        self._repo.delete(ship_id)

    def get_ship(self, ship_id: int) -> Ship | None:
        return self._repo.get(ship_id)

    def _validate(self, ship: Ship) -> None:
        if not ship.name.strip():
            raise ShipValidationError("Ship name is required.")
        if ship.length_overall_m <= 0:
            raise ShipValidationError("Length overall must be greater than zero.")
        if ship.breadth_m <= 0:
            raise ShipValidationError("Breadth must be greater than zero.")
        if ship.design_draft_m < 0 or ship.design_draft_m > 30:
            raise ShipValidationError("Design draft must be between 0 and 30 m.")

