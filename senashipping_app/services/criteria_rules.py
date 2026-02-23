"""
IMO and Livestock criteria rule sets with hierarchical lines structure.

Rules follow vessel Loading Manual (assets/stability.pdf) and IMO IS Code A.749(18):
general intact stability (§3.1), weather criterion (§3.2), applied livestock (§3.3).
Evaluated against condition results; return pass/fail with margins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List

from ..config.limits import (
    EPS,
    MAX_DRAFT_FRACTION,
    MAX_TRIM_FRACTION,
    MIN_AIR_DRAFT_M,
    MIN_FREEBORD_M,
    MIN_GM_LIVESTOCK_M,
    MIN_GM_M,
    MIN_PROP_IMMERSION_PCT,
    MIN_VISIBILITY_M,
    MAX_ROLL_PERIOD_S,
)
from ..models import Ship, Tank
from .stability_service import ConditionResults
from .validation import compute_free_surface_correction


class CriterionResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    N_A = "N/A"


@dataclass(slots=True)
class CriterionLine:
    """Single criterion line with pass/fail and margin."""
    code: str
    name: str
    reference: str  # e.g. "IS Code", "AMSA MO43"
    result: CriterionResult
    value: float | None
    limit: float | None
    margin: float | None  # value - limit (positive = pass margin)
    message: str
    parent_code: str | None = None  # for hierarchy


@dataclass(slots=True)
class CriteriaEvaluation:
    """Full evaluation of IMO + livestock criteria."""
    lines: List[CriterionLine] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    n_a: int = 0

    @property
    def all_passed(self) -> bool:
        return self.failed == 0


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if abs(b) < EPS:
        return default
    return a / b


def evaluate_imo_criteria(
    ship: Ship,
    results: ConditionResults,
    tanks: List[Tank],
    volumes: Dict[int, float],
    cargo_density: float,
) -> List[CriterionLine]:
    """Evaluate IMO intact stability criteria."""
    lines: List[CriterionLine] = []
    L = max(EPS, ship.length_overall_m)
    validation = getattr(results, "validation", None)
    gm_eff = getattr(validation, "gm_effective", None) if validation else None
    if gm_eff is None:
        fsc = compute_free_surface_correction(tanks, volumes, results.displacement_t, cargo_density)
        gm_eff = max(0.0, results.gm_m - fsc)

    # 1. Minimum GM
    margin = gm_eff - MIN_GM_M if gm_eff is not None else None
    result = CriterionResult.PASS if (margin is not None and margin >= 0) else CriterionResult.FAIL
    lines.append(CriterionLine(
        code="IMO_GM",
        name="Minimum GM",
        reference="IS Code Ch.2",
        result=result,
        value=gm_eff,
        limit=MIN_GM_M,
        margin=margin,
        message=f"GM {gm_eff:.3f} m, min {MIN_GM_M} m" + (f", margin {margin:+.3f} m" if margin is not None else ""),
    ))

    # 2. Trim limit
    max_trim = L * MAX_TRIM_FRACTION
    margin_trim = max_trim - abs(results.trim_m)
    result_trim = CriterionResult.PASS if margin_trim >= 0 else CriterionResult.FAIL
    lines.append(CriterionLine(
        code="IMO_TRIM",
        name="Trim limit",
        reference="IS Code",
        result=result_trim,
        value=abs(results.trim_m),
        limit=max_trim,
        margin=margin_trim,
        message=f"Trim {abs(results.trim_m):.2f} m, max {max_trim:.2f} m, margin {margin_trim:+.2f} m",
    ))

    # 3. Draft limit
    design_draft = max(EPS, ship.design_draft_m)
    max_draft = design_draft * MAX_DRAFT_FRACTION
    margin_draft = max_draft - results.draft_m
    result_draft = CriterionResult.PASS if margin_draft >= 0 else CriterionResult.FAIL
    lines.append(CriterionLine(
        code="IMO_DRAFT",
        name="Draft limit",
        reference="Load Line",
        result=result_draft,
        value=results.draft_m,
        limit=max_draft,
        margin=margin_draft,
        message=f"Draft {results.draft_m:.2f} m, max {max_draft:.2f} m, margin {margin_draft:+.2f} m",
    ))

    return lines


def evaluate_livestock_criteria(
    ship: Ship,
    results: ConditionResults,
    tanks: List[Tank],
    volumes: Dict[int, float],
    cargo_density: float,
) -> List[CriterionLine]:
    """Evaluate livestock-specific criteria (AMSA MO43 / IMO livestock)."""
    lines: List[CriterionLine] = []
    L = max(EPS, ship.length_overall_m)
    B = max(EPS, ship.breadth_m)
    validation = getattr(results, "validation", None)
    gm_eff = getattr(validation, "gm_effective", None) if validation else None
    if gm_eff is None:
        fsc = compute_free_surface_correction(tanks, volumes, results.displacement_t, cargo_density)
        gm_eff = max(0.0, results.gm_m - fsc)

    # 1. Livestock GM (stricter)
    margin = gm_eff - MIN_GM_LIVESTOCK_M
    result = CriterionResult.PASS if margin >= 0 else CriterionResult.FAIL
    lines.append(CriterionLine(
        code="LIV_GM",
        name="Livestock minimum GM",
        reference="AMSA MO43 / IMO Livestock",
        result=result,
        value=gm_eff,
        limit=MIN_GM_LIVESTOCK_M,
        margin=margin,
        message=f"GM {gm_eff:.3f} m, min {MIN_GM_LIVESTOCK_M} m, margin {margin:+.3f} m",
    ))

    # 2. Roll period (T = 2*pi*K/sqrt(g*GM), K~0.4-0.5)
    if gm_eff > EPS:
        import math
        K = 0.45  # radius of gyration / B
        roll_period = 2 * math.pi * K * B / (9.81 * gm_eff) ** 0.5
        margin_rp = MAX_ROLL_PERIOD_S - roll_period
        result_rp = CriterionResult.PASS if margin_rp >= 0 else CriterionResult.FAIL
        lines.append(CriterionLine(
            code="LIV_ROLL",
            name="Roll period (animal welfare)",
            reference="AMSA MO43",
            result=result_rp,
            value=roll_period,
            limit=MAX_ROLL_PERIOD_S,
            margin=margin_rp,
            message=f"Roll period {roll_period:.1f} s, max {MAX_ROLL_PERIOD_S} s, margin {margin_rp:+.1f} s",
        ))
    else:
        lines.append(CriterionLine(
            code="LIV_ROLL",
            name="Roll period (animal welfare)",
            reference="AMSA MO43",
            result=CriterionResult.N_A,
            value=None,
            limit=MAX_ROLL_PERIOD_S,
            margin=None,
            message="N/A (GM too low)",
        ))

    # 3. Deck immersion / freeboard
    depth = max(EPS, ship.depth_m)
    freeboard = depth - results.draft_m - 0.5 * abs(results.trim_m)
    margin_fb = freeboard - MIN_FREEBORD_M
    result_fb = CriterionResult.PASS if margin_fb >= 0 else CriterionResult.FAIL
    lines.append(CriterionLine(
        code="LIV_FREEBORD",
        name="Minimum freeboard (no deck immersion)",
        reference="AMSA MO43",
        result=result_fb,
        value=freeboard,
        limit=MIN_FREEBORD_M,
        margin=margin_fb,
        message=f"Freeboard {freeboard:.2f} m, min {MIN_FREEBORD_M} m, margin {margin_fb:+.2f} m",
    ))

    return lines


def evaluate_gz_and_ancillary_criteria(
    ship: Ship,
    results: ConditionResults,
) -> List[CriterionLine]:
    """Phase 3: GZ status, prop immersion, visibility, air draft."""
    lines: List[CriterionLine] = []
    ancillary = getattr(results, "ancillary", None)
    if not ancillary:
        return lines

    # GZ criteria (simplified)
    gz_ok = getattr(ancillary, "gz_criteria_ok", False)
    lines.append(CriterionLine(
        code="GZ_STATUS",
        name="GZ Criteria Status",
        reference="IS Code Ch.2",
        result=CriterionResult.PASS if gz_ok else CriterionResult.FAIL,
        value=1.0 if gz_ok else 0.0,
        limit=1.0,
        margin=0.0 if gz_ok else -1.0,
        message="PASS" if gz_ok else "FAIL (GM or heel)",
    ))

    # Prop immersion
    prop_pct = getattr(ancillary, "prop_immersion_pct", 0.0)
    margin_prop = prop_pct - MIN_PROP_IMMERSION_PCT
    lines.append(CriterionLine(
        code="PROP_IMM",
        name="Propeller immersion",
        reference="Operational",
        result=CriterionResult.PASS if margin_prop >= 0 else CriterionResult.FAIL,
        value=prop_pct,
        limit=MIN_PROP_IMMERSION_PCT,
        margin=margin_prop,
        message=f"Prop immersion {prop_pct:.1f}%, min {MIN_PROP_IMMERSION_PCT}%",
    ))

    # Visibility
    vis = getattr(ancillary, "visibility_m", 0.0)
    margin_vis = vis - MIN_VISIBILITY_M
    lines.append(CriterionLine(
        code="VISIBILITY",
        name="Visibility",
        reference="SOLAS",
        result=CriterionResult.PASS if margin_vis >= 0 else CriterionResult.FAIL,
        value=vis,
        limit=MIN_VISIBILITY_M,
        margin=margin_vis,
        message=f"Visibility {vis:.1f} m, min {MIN_VISIBILITY_M} m",
    ))

    # Air draft
    air = getattr(ancillary, "air_draft_m", 0.0)
    margin_air = air - MIN_AIR_DRAFT_M
    lines.append(CriterionLine(
        code="AIR_DRAFT",
        name="Air draft",
        reference="Operational",
        result=CriterionResult.PASS if margin_air >= 0 else CriterionResult.FAIL,
        value=air,
        limit=MIN_AIR_DRAFT_M,
        margin=margin_air,
        message=f"Air draft {air:.1f} m, min {MIN_AIR_DRAFT_M} m",
    ))

    return lines


def evaluate_all_criteria(
    ship: Ship,
    results: ConditionResults,
    tanks: List[Tank],
    volumes: Dict[int, float],
    cargo_density: float = 1.0,
) -> CriteriaEvaluation:
    """Evaluate IMO + livestock criteria and return hierarchical lines."""
    imo_lines = evaluate_imo_criteria(ship, results, tanks, volumes, cargo_density)
    livestock_lines = evaluate_livestock_criteria(ship, results, tanks, volumes, cargo_density)
    ancillary_lines = evaluate_gz_and_ancillary_criteria(ship, results)

    all_lines: List[CriterionLine] = []
    for line in imo_lines:
        line.parent_code = "IMO"
        all_lines.append(line)
    for line in livestock_lines:
        line.parent_code = "LIVESTOCK"
        all_lines.append(line)
    for line in ancillary_lines:
        line.parent_code = "ANCILLARY"
        all_lines.append(line)

    passed = sum(1 for l in all_lines if l.result == CriterionResult.PASS)
    failed = sum(1 for l in all_lines if l.result == CriterionResult.FAIL)
    n_a = sum(1 for l in all_lines if l.result == CriterionResult.N_A)

    return CriteriaEvaluation(lines=all_lines, passed=passed, failed=failed, n_a=n_a)
