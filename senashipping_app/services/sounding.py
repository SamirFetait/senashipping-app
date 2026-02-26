"""
Sounding table interpolation: volume → VCG, LCG, TCG and Ullage, FSM for tank display.
"""

from __future__ import annotations

from typing import List, Tuple

from senashipping_app.models import TankSoundingRow

# Tolerance for treating volume step as zero (avoids div-by-zero in interpolation)
_VOLUME_EPS = 1e-12


def _sorted_rows_by_volume(rows: List[TankSoundingRow]) -> List[TankSoundingRow]:
    """Return rows sorted by volume_m3 (caller can rely on this order)."""
    return sorted(rows, key=lambda r: r.volume_m3)


def _interpolation_factor(volume_m3: float, v0: float, v1: float) -> float:
    """Linear factor t in [0, 1] for volume between v0 and v1; 1.0 if v0==v1."""
    if abs(v1 - v0) < _VOLUME_EPS:
        return 1.0
    return (volume_m3 - v0) / (v1 - v0)


def interpolate_ullage_fsm_from_volume(
    volume_m3: float,
    rows: List[TankSoundingRow],
) -> Tuple[float, float] | None:
    """
    Interpolate Ullage (m) and FSM (m-MT) for a given tank volume from sounding table rows.
    Returns (ullage_m, fsm_mt) or None if no rows. Clamps to first/last row when outside range.
    """
    if not rows:
        return None
    sorted_rows = _sorted_rows_by_volume(rows)
    v_min, v_max = sorted_rows[0].volume_m3, sorted_rows[-1].volume_m3
    if volume_m3 <= v_min:
        r = sorted_rows[0]
        return (r.ullage_m, r.fsm_mt)
    if volume_m3 >= v_max:
        r = sorted_rows[-1]
        return (r.ullage_m, r.fsm_mt)
    for i in range(len(sorted_rows) - 1):
        r0, r1 = sorted_rows[i], sorted_rows[i + 1]
        if r0.volume_m3 <= volume_m3 <= r1.volume_m3:
            t = _interpolation_factor(volume_m3, r0.volume_m3, r1.volume_m3)
            ull = r0.ullage_m + t * (r1.ullage_m - r0.ullage_m)
            fsm = r0.fsm_mt + t * (r1.fsm_mt - r0.fsm_mt)
            return (ull, fsm)
    return None


def interpolate_cog_from_volume(
    volume_m3: float,
    rows: List[TankSoundingRow],
) -> Tuple[float, float, float] | None:
    """
    Interpolate VCG, LCG, TCG (m) for a given tank volume from sounding table rows.
    Returns (vcg_m, lcg_m, tcg_m) or None if no rows. Clamps to first/last row when outside range.
    """
    if not rows:
        return None
    sorted_rows = _sorted_rows_by_volume(rows)
    v_min, v_max = sorted_rows[0].volume_m3, sorted_rows[-1].volume_m3
    if volume_m3 <= v_min:
        r = sorted_rows[0]
        return (r.vcg_m, r.lcg_m, r.tcg_m)
    if volume_m3 >= v_max:
        r = sorted_rows[-1]
        return (r.vcg_m, r.lcg_m, r.tcg_m)
    for i in range(len(sorted_rows) - 1):
        r0, r1 = sorted_rows[i], sorted_rows[i + 1]
        if r0.volume_m3 <= volume_m3 <= r1.volume_m3:
            t = _interpolation_factor(volume_m3, r0.volume_m3, r1.volume_m3)
            vcg = r0.vcg_m + t * (r1.vcg_m - r0.vcg_m)
            lcg = r0.lcg_m + t * (r1.lcg_m - r0.lcg_m)
            tcg = r0.tcg_m + t * (r1.tcg_m - r0.tcg_m)
            return (vcg, lcg, tcg)
    return None
