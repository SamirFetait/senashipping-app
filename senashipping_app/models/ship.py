from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(slots=True)
class Ship:
    id: int | None = None
    name: str = ""
    imo_number: str = ""
    flag: str = ""
    length_overall_m: float = 0.0
    breadth_m: float = 0.0
    depth_m: float = 0.0
    design_draft_m: float = 0.0
    lightship_draft_m: float = 0.0  # empty-ship draft (0 = use manual ref)
    lightship_displacement_t: float = 0.0  # empty-ship displacement (0 = use manual ref)

    # For now, just keep a list of tank IDs or objects; can refine later.
    tank_ids: List[int] = field(default_factory=list)

