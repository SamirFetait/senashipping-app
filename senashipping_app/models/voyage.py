from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware). Replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class LoadingCondition:
    id: int | None = None
    voyage_id: int | None = None
    name: str = ""
    created_at: datetime = field(default_factory=_utc_now)

    # Mapping: tank_id -> volume filled (m3)
    tank_volumes_m3: Dict[int, float] = field(default_factory=dict)

    # Mapping: pen_id -> head count (Phase 2 livestock)
    pen_loadings: Dict[int, int] = field(default_factory=dict)

    # Calculated properties (simplified for MVP)
    displacement_t: float = 0.0
    draft_m: float = 0.0
    trim_m: float = 0.0
    gm_m: float = 0.0


@dataclass(slots=True)
class Voyage:
    id: int | None = None
    ship_id: int | None = None
    name: str = ""
    departure_port: str = ""
    arrival_port: str = ""
    created_at: datetime = field(default_factory=_utc_now)

    conditions: List[LoadingCondition] = field(default_factory=list)

