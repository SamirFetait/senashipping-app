"""
Business logic for loading conditions and interaction with the calculation engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Ship, LoadingCondition, Tank
from ..models.cargo_type import CargoType
from ..repositories.tank_repository import TankRepository
from ..repositories.livestock_pen_repository import LivestockPenRepository
from ..config.limits import MASS_PER_HEAD_T
from .stability_service import compute_condition, ConditionResults
from .validation import validate_condition
from .criteria_rules import evaluate_all_criteria
from .traceability import create_snapshot


@dataclass(slots=True)
class ConditionValidationError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ConditionService:
    """
    Encapsulates validation and calculation for loading conditions.
    """

    def __init__(self, db: Session) -> None:
        self._tank_repo = TankRepository(db)
        self._pen_repo = LivestockPenRepository(db)

    def get_tanks_for_ship(self, ship_id: int) -> List[Tank]:
        return self._tank_repo.list_for_ship(ship_id)

    def get_pens_for_ship(self, ship_id: int):
        return self._pen_repo.list_for_ship(ship_id)

    def compute(
        self,
        ship: Ship,
        condition: LoadingCondition,
        tank_fill_volumes: Dict[int, float],
        cargo_density_t_per_m3: float = 1.0,
        cargo_type: Optional[CargoType] = None,
    ) -> ConditionResults:
        """
        Validate the condition and run the stability calculation.
        If cargo_type is set, uses its avg_weight_per_head_kg and vcg_from_deck_m for pen calculations.
        """
        pen_loadings = getattr(condition, "pen_loadings", None) or {}
        if not tank_fill_volumes and not pen_loadings:
            raise ConditionValidationError("No tank volumes or pen loadings provided.")

        if not ship.id:
            raise ConditionValidationError("Ship must have an ID.")
        tanks = self._tank_repo.list_for_ship(ship.id)
        pens = self._pen_repo.list_for_ship(ship.id)
        self._validate_tank_limits(tanks, tank_fill_volumes)

        if cargo_type:
            mass_per_head_t = (getattr(cargo_type, "avg_weight_per_head_kg", 520.0) or 520.0) / 1000.0
            vcg_from_deck_m = getattr(cargo_type, "vcg_from_deck_m", 0.0) or 0.0
        else:
            mass_per_head_t = MASS_PER_HEAD_T
            vcg_from_deck_m = 0.0

        condition.tank_volumes_m3 = tank_fill_volumes
        results = compute_condition(
            ship, tanks, condition, cargo_density_t_per_m3,
            pens=pens,
            pen_loadings=pen_loadings,
            mass_per_head_t=mass_per_head_t,
            vcg_from_deck_m=vcg_from_deck_m,
        )

        # Run validation (negative GM, extreme trim, over-limit BM, etc.)
        validation = validate_condition(
            ship, results, tanks, tank_fill_volumes, cargo_density_t_per_m3
        )
        results.validation = validation

        # Run IMO + livestock criteria
        criteria = evaluate_all_criteria(
            ship, results, tanks, tank_fill_volumes, cargo_density_t_per_m3
        )
        results.criteria = criteria

        # Traceability snapshot
        results.snapshot = create_snapshot(
            condition.name,
            ship.name,
            tank_fill_volumes,
            cargo_density_t_per_m3,
            results,
            criteria,
        )

        # Fill condition with the results so it can be displayed / persisted.
        condition.displacement_t = results.displacement_t
        condition.draft_m = results.draft_m
        condition.trim_m = results.trim_m
        condition.gm_m = validation.gm_effective  # Use effective GM (after free surface)

        return results

    def _validate_tank_limits(
        self, tanks: List[Tank], tank_fill_volumes: Dict[int, float]
    ) -> None:
        for tank in tanks:
            vol = tank_fill_volumes.get(tank.id or -1, 0.0)
            if vol < 0:
                raise ConditionValidationError(
                    f"Negative volume in tank {tank.name} is not allowed."
                )
            if vol > tank.capacity_m3 * 1.05:
                # Allow a small numerical tolerance
                raise ConditionValidationError(
                    f"Volume in tank {tank.name} exceeds capacity."
                )

