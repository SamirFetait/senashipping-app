"""
Simple text-based report builder for a loading condition.
"""

from __future__ import annotations

from senashipping_app.models import Ship, Voyage, LoadingCondition


def build_condition_summary_text(
    ship: Ship,
    voyage: Voyage,
    condition: LoadingCondition,
    kg_m: float = 0.0,
    km_m: float = 0.0,
    swbm_tm: float = 0.0,
    criteria_summary: str = "",
    trace_timestamp: str = "",
) -> str:
    lines: list[str] = []
    lines.append(f"Ship: {ship.name} (IMO: {ship.imo_number})")
    lines.append(f"Voyage: {voyage.name} {voyage.departure_port} -> {voyage.arrival_port}")
    lines.append(f"Condition: {condition.name}")
    lines.append("")
    lines.append(f"Displacement: {condition.displacement_t:.1f} t")
    lines.append(f"Draft: {condition.draft_m:.2f} m")
    lines.append(f"Trim: {condition.trim_m:.2f} m")
    lines.append(f"GM: {condition.gm_m:.2f} m")
    lines.append(f"KG: {kg_m:.2f} m")
    lines.append(f"KM: {km_m:.2f} m")
    lines.append(f"SWBM: {swbm_tm:.0f} tm")
    if criteria_summary:
        lines.append("")
        lines.append(f"Criteria: {criteria_summary}")
    if trace_timestamp:
        lines.append(f"Calculated: {trace_timestamp}")
    return "\n".join(lines)

