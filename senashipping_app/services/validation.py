"""
Validation and limit checks for loading conditions.

Detects negative GM, over-limit BM, invalid tank combos, extreme trim,
zero-weight divisions, and applies free surface correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from ..config.limits import (
    EPS,
    FREE_SURFACE_FACTOR,
    MAX_DRAFT_FRACTION,
    MAX_SWBM_FRACTION,
    MAX_TRIM_FRACTION,
    MIN_GM_M,
)
from ..models import Ship, Tank
from .stability_service import ConditionResults


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
) -> float:
    """
    Approximate free surface correction (m) for slack tanks.
    Reduces effective GM.
    """
    if displacement_t < EPS:
        return 0.0
    correction = 0.0
    for tank in tanks:
        vol = volumes.get(tank.id or -1, 0.0)
        cap = max(EPS, tank.capacity_m3)
        fill_ratio = vol / cap
        # Slack: partially filled (e.g. 5–95%)
        if 0.05 < fill_ratio < 0.95:
            # Simplified: i_t for rectangular tank ~ B³*L/12, mass = vol*density
            # Reduction ≈ (rho * i_t) / disp. Use factor based on tank size.
            mass = vol * cargo_density
            correction += (mass / displacement_t) * FREE_SURFACE_FACTOR * (1 - fill_ratio)
    return min(correction, 2.0)  # Cap total correction


def validate_condition(
    ship: Ship,
    results: ConditionResults,
    tanks: List[Tank],
    volumes: Dict[int, float],
    cargo_density: float = 1.0,
) -> ValidationResult:
    """
    Run all validation checks and compute effective GM after free surface.
    """
    issues: List[ValidationIssue] = []
    gm_raw = results.gm_m

    # Free surface correction
    fsc = compute_free_surface_correction(tanks, volumes, results.displacement_t, cargo_density)
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

    # 2. Extreme trim (only when ship length is set; otherwise limit would be ~0 and always fail)
    from ..config.stability_manual_ref import REF_LOA_M, REF_DESIGN_DRAFT_M

    L = getattr(ship, "length_overall_m", 0.0) or REF_LOA_M
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

    # 3. Draft over limit (only when design draft is set; otherwise limit would be ~0 and always fail)
    design_draft = getattr(ship, "design_draft_m", 0.0) or REF_DESIGN_DRAFT_M
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
