"""
Calculation traceability: inputs snapshot, outputs, timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass(slots=True)
class CalculationSnapshot:
    """Traceability snapshot for a condition calculation."""
    timestamp: datetime
    condition_name: str
    ship_name: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    criteria_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "condition_name": self.condition_name,
            "ship_name": self.ship_name,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "criteria_summary": self.criteria_summary,
        }


def create_snapshot(
    condition_name: str,
    ship_name: str,
    tank_volumes: Dict[int, float],
    cargo_density: float,
    results: object,
    criteria: object | None = None,
) -> CalculationSnapshot:
    """Build a traceability snapshot from calculation inputs and results."""
    res = results
    inputs = {
        "tank_volumes_m3": dict(tank_volumes),
        "cargo_density_t_per_m3": cargo_density,
    }
    outputs = {
        "displacement_t": getattr(res, "displacement_t", None),
        "draft_m": getattr(res, "draft_m", None),
        "trim_m": getattr(res, "trim_m", None),
        "gm_m": getattr(res, "gm_m", None),
        "kg_m": getattr(res, "kg_m", None),
        "km_m": getattr(res, "km_m", None),
    }
    validation = getattr(res, "validation", None)
    if validation:
        outputs["gm_effective"] = getattr(validation, "gm_effective", None)

    criteria_summary = ""
    if criteria and hasattr(criteria, "lines"):
        from senashipping_app.services.criteria_rules import CriterionResult
        passed = sum(1 for ln in criteria.lines if ln.result == CriterionResult.PASS)
        failed = sum(1 for ln in criteria.lines if ln.result == CriterionResult.FAIL)
        criteria_summary = f"Criteria: {passed} passed, {failed} failed"

    return CalculationSnapshot(
        timestamp=datetime.now(timezone.utc),
        condition_name=condition_name,
        ship_name=ship_name,
        inputs=inputs,
        outputs=outputs,
        criteria_summary=criteria_summary,
    )
