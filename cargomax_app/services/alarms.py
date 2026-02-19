"""
Alarms panel data: status rows with Attained, Pass If, Type.

Maps criteria and validation to the reference app's Alarms format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from .criteria_rules import CriterionResult, CriterionLine, CriteriaEvaluation
from .stability_service import ConditionResults
from .validation import ValidationResult, ValidationSeverity


class AlarmStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


class AlarmType(Enum):
    REQUIREMENT = "Requirement"
    RECOMMENDATION = "Recommendation"


@dataclass(slots=True)
class AlarmRow:
    no: int
    status: AlarmStatus
    description: str
    attained: str
    pass_if: str
    type: AlarmType


def build_alarm_rows(
    results: ConditionResults,
    validation: ValidationResult | None,
    criteria: CriteriaEvaluation | None,
) -> List[AlarmRow]:
    """Build alarm rows for the Alarms panel."""
    rows: List[AlarmRow] = []
    n = 0

    # Calculation Status
    n += 1
    if validation:
        has_errors = getattr(validation, "has_errors", False)
        has_warnings = getattr(validation, "has_warnings", False)
        if has_errors:
            calc_status = AlarmStatus.FAIL
            calc_attained = "FAILED"
            calc_pass_if = "No errors"
        elif has_warnings:
            calc_status = AlarmStatus.WARN
            calc_attained = "WARNING"
            calc_pass_if = "No warnings"
        else:
            calc_status = AlarmStatus.PASS
            calc_attained = "OK"
            calc_pass_if = "OK"
    else:
        # No validation available - assume OK
        calc_status = AlarmStatus.PASS
        calc_attained = "OK"
        calc_pass_if = "OK"
    
    rows.append(AlarmRow(
        no=n,
        status=calc_status,
        description="Calculation Status",
        attained=calc_attained,
        pass_if=calc_pass_if,
        type=AlarmType.REQUIREMENT,
    ))

    # Avail Deadweight (placeholder: disp as available)
    n += 1
    av_dwt = max(0.0, results.displacement_t)  # simplified
    rows.append(AlarmRow(
        no=n,
        status=AlarmStatus.PASS if av_dwt >= 0 else AlarmStatus.FAIL,
        description="Avail Deadweight",
        attained=f"{av_dwt:.2f} MT",
        pass_if="AvDWT >= 0.00 MT",
        type=AlarmType.REQUIREMENT,
    ))

    # Max BMom %Allow
    strength = getattr(results, "strength", None)
    if strength and hasattr(strength, "bm_pct_allow"):
        n += 1
        bm_pct = strength.bm_pct_allow
        ok = -100 <= bm_pct <= 100
        rows.append(AlarmRow(
            no=n,
            status=AlarmStatus.PASS if ok else AlarmStatus.FAIL,
            description="Max BMom %Allow",
            attained=f"{bm_pct:.2f}%",
            pass_if="-100.00 <= BM% <= 100.00",
            type=AlarmType.REQUIREMENT,
        ))

    # Max Shear %Allow
    if strength and hasattr(strength, "sf_pct_allow"):
        n += 1
        sf_pct = strength.sf_pct_allow
        ok = -100 <= sf_pct <= 100
        rows.append(AlarmRow(
            no=n,
            status=AlarmStatus.PASS if ok else AlarmStatus.FAIL,
            description="Max Shear %Allow",
            attained=f"{sf_pct:.2f}%",
            pass_if="-100.00 <= SF% <= 100.00",
            type=AlarmType.REQUIREMENT,
        ))

    # Criteria from evaluate_all_criteria (GM, Trim, Draft, Livestock GM, Roll, Freeboard)
    if criteria and hasattr(criteria, "lines"):
        for line in criteria.lines:
            n += 1
            st = AlarmStatus.PASS if line.result == CriterionResult.PASS else (
                AlarmStatus.FAIL if line.result == CriterionResult.FAIL else AlarmStatus.WARN
            )
            attained = f"{line.value:.3f}" if line.value is not None else "N/A"
            if line.limit is not None:
                is_max_limit = any(x in line.name.lower() for x in ("trim", "draft", "roll", "limit"))
                pass_if = f"<= {line.limit:.3f}" if is_max_limit else f">= {line.limit:.3f}"
            else:
                pass_if = "N/A"
            rows.append(AlarmRow(
                no=n,
                status=st,
                description=line.name,
                attained=attained,
                pass_if=pass_if,
                type=AlarmType.REQUIREMENT,
            ))

    return rows
