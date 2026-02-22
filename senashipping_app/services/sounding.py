"""
Sounding table interpolation: volume → VCG, LCG, TCG for tank CoG in stability/strength.
"""

from __future__ import annotations

from typing import List, Tuple

from ..models import TankSoundingRow


def interpolate_cog_from_volume(
    volume_m3: float,
    rows: List[TankSoundingRow],
) -> Tuple[float, float, float] | None:
    """
    Interpolate VCG, LCG, TCG (m) for a given tank volume from sounding table rows.

    Rows should be sorted by volume_m3 (caller responsibility).
    Returns (vcg_m, lcg_m, tcg_m) or None if table empty or volume outside range.
    Uses linear interpolation; clamps to first/last row if volume is below/above range.
    """
    if not rows:
        return None
    sorted_rows = sorted(rows, key=lambda r: r.volume_m3)
    v_min = sorted_rows[0].volume_m3
    v_max = sorted_rows[-1].volume_m3
    if volume_m3 <= v_min:
        r = sorted_rows[0]
        return (r.vcg_m, r.lcg_m, r.tcg_m)
    if volume_m3 >= v_max:
        r = sorted_rows[-1]
        return (r.vcg_m, r.lcg_m, r.tcg_m)
    for i in range(len(sorted_rows) - 1):
        r0, r1 = sorted_rows[i], sorted_rows[i + 1]
        if r0.volume_m3 <= volume_m3 <= r1.volume_m3:
            if r1.volume_m3 - r0.volume_m3 < 1e-12:
                t = 1.0
            else:
                t = (volume_m3 - r0.volume_m3) / (r1.volume_m3 - r0.volume_m3)
            vcg = r0.vcg_m + t * (r1.vcg_m - r0.vcg_m)
            lcg = r0.lcg_m + t * (r1.lcg_m - r0.lcg_m)
            tcg = r0.tcg_m + t * (r1.tcg_m - r0.tcg_m)
            return (vcg, lcg, tcg)
    return None
