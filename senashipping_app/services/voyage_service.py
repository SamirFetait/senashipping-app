"""
Business logic for voyages and loading conditions.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from senashipping_app.models import Voyage, LoadingCondition, Ship
from senashipping_app.repositories.voyage_repository import VoyageRepository, ConditionRepository


class VoyageValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class VoyageService:
    def __init__(self, db: Session) -> None:
        self._voyage_repo = VoyageRepository(db)
        self._condition_repo = ConditionRepository(db)

    def list_voyages_for_ship(self, ship_id: int) -> List[Voyage]:
        return self._voyage_repo.list_for_ship(ship_id)

    def get_voyage(self, voyage_id: int) -> Optional[Voyage]:
        v = self._voyage_repo.get(voyage_id)
        if v:
            v.conditions = self._condition_repo.list_for_voyage(voyage_id)
        return v

    def save_voyage(self, voyage: Voyage) -> Voyage:
        if not voyage.name.strip():
            raise VoyageValidationError("Voyage name is required.")
        if voyage.ship_id is None:
            raise VoyageValidationError("Voyage must be linked to a ship.")
        if voyage.id is None:
            return self._voyage_repo.create(voyage)
        return self._voyage_repo.update(voyage)

    def delete_voyage(self, voyage_id: int) -> None:
        for c in self._condition_repo.list_for_voyage(voyage_id):
            if c.id:
                self._condition_repo.delete(c.id)
        self._voyage_repo.delete(voyage_id)

    def list_conditions_for_voyage(self, voyage_id: int) -> List[LoadingCondition]:
        return self._condition_repo.list_for_voyage(voyage_id)

    def get_condition(self, condition_id: int) -> Optional[LoadingCondition]:
        return self._condition_repo.get(condition_id)

    def save_condition(self, condition: LoadingCondition) -> LoadingCondition:
        if not condition.name.strip():
            raise VoyageValidationError("Condition name is required.")
        if condition.voyage_id is None:
            raise VoyageValidationError("Condition must be linked to a voyage.")
        if condition.id is None:
            return self._condition_repo.create(condition)
        return self._condition_repo.update(condition)

    def delete_condition(self, condition_id: int) -> None:
        self._condition_repo.delete(condition_id)
