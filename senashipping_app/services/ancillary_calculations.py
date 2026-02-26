"""
Phase 3: Propeller immersion, visibility, air draft, GZ-related checks.

Uses ship dimensions and condition results. Formulas are simplified
where full hydrostatics are not available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from senashipping_app.models import Ship


@dataclass(slots=True)
class AncillaryResults:
    """Prop immersion, visibility, air draft, and GZ summary."""

    prop_immersion_pct: float  # 0–100
    visibility_m: float  # approx distance from bridge to bow waterline
    air_draft_m: float  # clearance above waterline to highest point
    gz_criteria_ok: bool  # simplified: based on GM and heel


# Typical ratios when ship-specific data not available
PROP_CENTER_ABOVE_BASELINE_RATIO = 0.05  # prop center ~5% of depth above keel
PROP_DIAMETER_RATIO = 0.03  # prop diameter ~3% of LOA
BRIDGE_POS_FROM_AP_RATIO = 0.85  # bridge ~85% from AP (near stern)
BRIDGE_HEIGHT_RATIO = 1.0  # bridge height ~ depth
MAST_HEIGHT_RATIO = 1.8  # mast ~ 1.8 * depth


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if abs(b) < 1e-9:
        return default
    return a / b


def compute_prop_immersion_pct(
    draft_aft_m: float,
    length_m: float,
    depth_m: float,
    prop_center_above_baseline_m: float | None = None,
    prop_diameter_m: float | None = None,
) -> float:
    """
    Propeller immersion as % of diameter.

    Prop center typically near stern at prop_center above baseline.
    Immersion = draft_aft - prop_center_above_baseline.
    """
    if length_m <= 0 or depth_m <= 0:
        return 0.0
    prop_center = prop_center_above_baseline_m if prop_center_above_baseline_m is not None else depth_m * PROP_CENTER_ABOVE_BASELINE_RATIO
    prop_dia = prop_diameter_m if prop_diameter_m is not None else length_m * PROP_DIAMETER_RATIO
    if prop_dia <= 0:
        return 100.0 if draft_aft_m > prop_center else 0.0
    immersion = max(0.0, draft_aft_m - prop_center)
    pct = min(100.0, max(0.0, 100.0 * immersion / prop_dia))
    return pct


def compute_visibility_m(
    length_m: float,
    depth_m: float,
    draft_fwd_m: float,
    trim_m: float,
    bridge_pos_from_ap_m: float | None = None,
    bridge_height_m: float | None = None,
) -> float:
    """
    Approximate visibility: distance from bridge to water at bow.

    Simplified: bridge at stern area, looking forward. Uses geometry of
    sight line from bridge to water surface at bow. Returns positive
    if water is visible (trim not excessive).
    """
    if length_m <= 0:
        return 0.0
    bridge_x = bridge_pos_from_ap_m if bridge_pos_from_ap_m is not None else length_m * BRIDGE_POS_FROM_AP_RATIO
    bridge_h = bridge_height_m if bridge_height_m is not None else depth_m * BRIDGE_HEIGHT_RATIO
    dist_to_bow = length_m - bridge_x
    if dist_to_bow <= 0:
        return length_m
    trim_angle_rad = math.atan(trim_m / length_m) if length_m > 0 else 0.0
    water_at_bow = draft_fwd_m
    height_diff = bridge_h - water_at_bow
    if height_diff <= 0:
        return dist_to_bow
    if abs(trim_angle_rad) < 1e-9:
        return dist_to_bow
    visibility = height_diff / abs(math.tan(trim_angle_rad))
    return min(length_m, max(0.0, visibility))


def compute_air_draft_m(
    depth_m: float,
    draft_m: float,
    mast_height_m: float | None = None,
) -> float:
    """
    Air draft = clearance above waterline to highest point (e.g. mast).

    mast_top - draft = air_draft.
    """
    mast_h = mast_height_m if mast_height_m is not None else depth_m * MAST_HEIGHT_RATIO
    return max(0.0, mast_h - draft_m)


def compute_ancillary(
    ship: Ship,
    draft_m: float,
    draft_aft_m: float,
    draft_fwd_m: float,
    trim_m: float,
    gm_m: float,
    heel_deg: float,
) -> AncillaryResults:
    """
    Compute prop immersion, visibility, air draft, and GZ criteria status.

    GZ criteria: simplified pass if GM >= 0.15 and heel within limits.
    Full GZ curve evaluation would require stability calculations.
    """
    from ..config.stability_manual_ref import REF_LOA_M, REF_DEPTH_M

    # Use ship dimensions from DB when available, else fall back to manual values.
    L = getattr(ship, "length_overall_m", 0.0) or REF_LOA_M
    D = getattr(ship, "depth_m", 0.0) or REF_DEPTH_M
    L = max(1e-6, L)
    D = max(1e-6, D)

    prop_pct = compute_prop_immersion_pct(draft_aft_m, L, D)
    visibility = compute_visibility_m(L, D, draft_fwd_m, trim_m)
    air_draft = compute_air_draft_m(D, draft_m)

    gz_ok = gm_m >= 0.15 and abs(heel_deg) < 5.0

    return AncillaryResults(
        prop_immersion_pct=prop_pct,
        visibility_m=visibility,
        air_draft_m=air_draft,
        gz_criteria_ok=gz_ok,
    )
