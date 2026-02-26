"""
Validation and limit checks for loading conditions.

Detects negative GM, over-limit BM, invalid tank combos, extreme trim,
zero-weight divisions, and applies free surface correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from senashipping_app.config.limits import EPS, MAX_DRAFT_FRACTION, MAX_SWBM_FRACTION, MAX_TRIM_FRACTION, MIN_GM_M
from senashipping_app.models import Ship, Tank
from senashipping_app.services.stability_service import ConditionResults


class ValidationSeverity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    message: str
    value: float | None = None
    limit: float | None = None


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    gm_effective: float
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)


def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    """Avoid zero-weight divisions."""
    if abs(b) < EPS:
        return default
    return a / b


def compute_free_surface_correction(
    tanks: List[Tank],
    volumes: Dict[int, float],
    displacement_t: float,
    cargo_density: float,
    tank_fsm_mt: Dict[int, float] | None = None,
) -> float:
    """
    Free surface correction (m) for slack tanks, based on FSM tables when available.

    If `tank_fsm_mt` is provided, it should contain the free-surface moment (FSM) in
    tonne·m for each tank at the current filling ratio. The correction is then:

        GG' = sum(FSM) / Δ      (m)
        GM_eff = GM - GG'

    Only tanks with 5–95% fill are treated as slack. If no FSM data is given,
    this function returns 0.0 (no correction).
    """
    if displacement_t < EPS:
        return 0.0
    if not tank_fsm_mt:
        # No FSM data – do not apply an approximate correction here.
        return 0.0

    total_fsm = 0.0
    for tank in tanks:
        tid = tank.id
        if tid is None:
            continue
        vol = volumes.get(tid, 0.0)
        cap = max(EPS, tank.capacity_m3)
        fill_ratio = vol / cap
        # Slack: partially filled (e.g. 5–95%)
        if 0.05 < fill_ratio < 0.95:
            fsm = tank_fsm_mt.get(tid)
            if fsm is not None and fsm > 0.0:
                total_fsm += fsm

    if total_fsm <= 0.0:
        return 0.0
    return total_fsm / displacement_t


def validate_condition(
    ship: Ship,
    results: ConditionResults,
    tanks: List[Tank],
    volumes: Dict[int, float],
    cargo_density: float = 1.0,
    tank_fsm_mt: Dict[int, float] | None = None,
) -> ValidationResult:
    """
    Run all validation checks and compute effective GM after free surface.
    """
    issues: List[ValidationIssue] = []
    gm_raw = results.gm_m

    # Free surface correction from FSM tables when available
    fsc = compute_free_surface_correction(
        tanks, volumes, results.displacement_t, cargo_density, tank_fsm_mt
    )
    gm_effective = max(0.0, gm_raw - fsc)

    # 1. Negative / low GM
    if gm_effective < MIN_GM_M:
        issues.append(
            ValidationIssue(
                code="GM_LOW",
                severity=ValidationSeverity.ERROR,
                message=f"GM {gm_effective:.3f} m below minimum {MIN_GM_M} m. Condition unsafe.",
                value=gm_effective,
                limit=MIN_GM_M,
            )
        )
    elif gm_effective < MIN_GM_M * 1.5:
        issues.append(
            ValidationIssue(
                code="GM_MARGINAL",
                severity=ValidationSeverity.WARNING,
                message=f"GM {gm_effective:.3f} m is marginal. Minimum recommended: {MIN_GM_M} m.",
                value=gm_effective,
                limit=MIN_GM_M,
            )
        )

    # 2. Extreme trim (only when ship length is set; otherwise skip)
    L = getattr(ship, "length_overall_m", 0.0) or 0.0
    if L > 0.01:
        max_trim = L * MAX_TRIM_FRACTION
        if abs(results.trim_m) > max_trim:
            issues.append(
                ValidationIssue(
                    code="TRIM_EXCESSIVE",
                    severity=ValidationSeverity.ERROR,
                    message=f"Trim {results.trim_m:.2f} m exceeds limit {max_trim:.2f} m ({MAX_TRIM_FRACTION*100:.1f}% LOA).",
                    value=abs(results.trim_m),
                    limit=max_trim,
                )
            )

    # 3. Draft over limit (only when design draft is set; otherwise skip)
    design_draft = getattr(ship, "design_draft_m", 0.0) or 0.0
    if design_draft > 0.01:
        max_draft = design_draft * MAX_DRAFT_FRACTION
        if results.draft_m > max_draft:
            issues.append(
                ValidationIssue(
                    code="DRAFT_OVER",
                    severity=ValidationSeverity.ERROR,
                    message=f"Draft {results.draft_m:.2f} m exceeds {MAX_DRAFT_FRACTION*100:.0f}% of design draft {design_draft:.2f} m.",
                    value=results.draft_m,
                    limit=max_draft,
                )
            )

    # 4. Over-limit bending moment
    if hasattr(results, "strength") and results.strength:
        swbm = abs(results.strength.still_water_bm_approx_tm)
        # Placeholder: assume design limit ~ disp * L * 0.1 (simplified)
        design_bm = results.displacement_t * L * 0.1
        if design_bm > EPS and swbm > design_bm * MAX_SWBM_FRACTION:
            issues.append(
                ValidationIssue(
                    code="BM_OVER",
                    severity=ValidationSeverity.WARNING,
                    message=f"Still-water BM {swbm:.0f} tm may exceed design limits. Verify strength.",
                    value=swbm,
                    limit=design_bm,
                )
            )

    # 5. Zero displacement (informational)
    if results.displacement_t < EPS:
        issues.append(
            ValidationIssue(
                code="ZERO_WEIGHT",
                severity=ValidationSeverity.WARNING,
                message="Zero displacement. No cargo/ballast loaded.",
                value=0.0,
                limit=None,
            )
        )

    # 6. Invalid tank IDs (checked earlier in condition_service; here we flag unknown refs)
    tank_ids = {t.id for t in tanks if t.id is not None}
    for tid in volumes:
        if tid not in tank_ids and volumes[tid] > EPS:
            issues.append(
                ValidationIssue(
                    code="TANK_UNKNOWN",
                    severity=ValidationSeverity.WARNING,
                    message=f"Volume specified for unknown tank ID {tid}. Ignored in calculations.",
                    value=volumes[tid],
                    limit=None,
                )
            )

    valid = not any(i.severity == ValidationSeverity.ERROR for i in issues)
    return ValidationResult(
        valid=valid,
        gm_effective=gm_effective,
        issues=issues,
    )
