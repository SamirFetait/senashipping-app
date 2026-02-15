"""
Livestock pen model for Phase 2.

Pens belong to a ship and have position (VCG, LCG, TCG), area, and capacity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LivestockPen:
    """A livestock pen on a ship deck."""

    id: int | None = None
    ship_id: int | None = None
    name: str = ""  # e.g. PEN 1-1, 1-2
    deck: str = ""  # e.g. DK1, DK2, DK3
    pen_no: int | None = None  # display order on deck (1-14, descending in table)

    # Position / CoG (m from AP for LCG, from centerline for TCG, from keel for VCG)
    vcg_m: float = 0.0
    lcg_m: float = 0.0
    tcg_m: float = 0.0

    # Area and capacity
    area_m2: float = 0.0
    capacity_head: int = 0  # max head count (optional)

    # Deck table: Area and TCG by quadrant (A/B/C/D). None = show "---"
    area_a_m2: float | None = None
    area_b_m2: float | None = None
    area_c_m2: float | None = None
    area_d_m2: float | None = None
    tcg_a_m: float | None = None
    tcg_b_m: float | None = None
    tcg_c_m: float | None = None
    tcg_d_m: float | None = None