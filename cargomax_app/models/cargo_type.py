"""
Cargo type library model.

Each cargo type has name, color, pattern, method, type, and calculation fields
(Avg Weight Per Head, VCG from Deck, Deck Area per Head, Dung %/day).
Used as the main variable for loading conditions; calculations use these values.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CargoType:
    """A cargo type in the user-defined library."""

    id: int | None = None
    display_order: int = 0
    color_hex: str = "#8844aa"
    pattern: str = "Solid"
    in_use: bool = True
    name: str = ""
    description: str = ""

    # Method / Type (for display and filtering)
    method: str = "Livestock"
    cargo_subtype: str = "Walk-On, Walk-Off"

    # Calculation inputs (used dynamically in stability and condition table)
    avg_weight_per_head_kg: float = 520.0
    vcg_from_deck_m: float = 1.5
    deck_area_per_head_m2: float = 1.85
    dung_weight_pct_per_day: float = 1.5
