"""
Excel report generation for loading conditions.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

if TYPE_CHECKING:
    from ..models import Ship, Voyage, LoadingCondition
    from ..services.stability_service import ConditionResults


def _fmt(value: object, fmt: str) -> str:
    """Safely format numeric values, falling back to string/blank."""
    if value is None:
        return ""
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return str(value)


def _style_header(ws) -> None:
    """Apply a simple header style similar to the manual tables."""
    header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment


def export_condition_to_excel(
    filepath: Path,
    ship: "Ship",
    voyage: "Voyage",
    condition: "LoadingCondition",
    results: "ConditionResults",
) -> None:
    """
    Generate a multi-sheet Excel report for a loading condition.

    The layout is inspired by the vessel loading manual pages:
    - Condition summary
    - Equilibrium / hydrostatic-style data
    - IMO / ancillary criteria with pass/fail highlighting
    """
    # --- Sheet 1: high-level condition summary ---
    summary_data = {
        "Parameter": [
            "Ship",
            "IMO",
            "Voyage",
            "Departure",
            "Arrival",
            "Condition",
            "Displacement (t)",
            "Draft mid (m)",
            "Draft aft (m)",
            "Draft fwd (m)",
            "Trim (m, +ve stern down)",
            "Heel (deg)",
            "GM (effective, m)",
            "GM (raw, m)",
            "KG (m)",
            "KM (m)",
        ],
        "Value": [
            ship.name,
            getattr(ship, "imo_number", "") or "",
            voyage.name,
            voyage.departure_port,
            voyage.arrival_port,
            condition.name,
            _fmt(getattr(condition, "displacement_t", None), ".1f"),
            _fmt(getattr(condition, "draft_m", None), ".3f"),
            _fmt(getattr(results, "draft_aft_m", None), ".3f"),
            _fmt(getattr(results, "draft_fwd_m", None), ".3f"),
            _fmt(getattr(condition, "trim_m", None), ".3f"),
            _fmt(getattr(results, "heel_deg", None), ".2f"),
            _fmt(getattr(getattr(results, "validation", None), "gm_effective", None), ".3f"),
            _fmt(getattr(results, "gm_m", None), ".3f"),
            _fmt(getattr(results, "kg_m", None), ".3f"),
            _fmt(getattr(results, "km_m", None), ".3f"),
        ],
    }
    strength = getattr(results, "strength", None)
    if strength:
        summary_data["Parameter"].append("SWBM approx. (tm)")
        summary_data["Value"].append(_fmt(getattr(strength, "still_water_bm_approx_tm", None), ".0f"))

    ancillary = getattr(results, "ancillary", None)
    if ancillary:
        summary_data["Parameter"].extend(
            [
                "Propeller immersion (%)",
                "Visibility ahead (m)",
                "Air draft (m)",
                "GZ criteria OK",
            ]
        )
        summary_data["Value"].extend(
            [
                _fmt(getattr(ancillary, "prop_immersion_pct", None), ".1f"),
                _fmt(getattr(ancillary, "visibility_m", None), ".1f"),
                _fmt(getattr(ancillary, "air_draft_m", None), ".2f"),
                "YES" if getattr(ancillary, "gz_criteria_ok", False) else "NO",
            ]
        )

    df_summary = pd.DataFrame(summary_data)

    # --- Sheet 2: equilibrium-style data (narrower, with units) ---
    eq_rows = {
        "Parameter": [
            "Displacement",
            "Draft amidships",
            "Draft at AP",
            "Draft at FP",
            "Trim (stern down +ve)",
            "Heel",
            "GM (effective)",
            "GM (raw)",
            "KG",
            "KM",
        ],
        "Value": [
            _fmt(getattr(results, "displacement_t", None), ".1f"),
            _fmt(getattr(results, "draft_m", None), ".3f"),
            _fmt(getattr(results, "draft_aft_m", None), ".3f"),
            _fmt(getattr(results, "draft_fwd_m", None), ".3f"),
            _fmt(getattr(results, "trim_m", None), ".3f"),
            _fmt(getattr(results, "heel_deg", None), ".2f"),
            _fmt(getattr(getattr(results, "validation", None), "gm_effective", None), ".3f"),
            _fmt(getattr(results, "gm_m", None), ".3f"),
            _fmt(getattr(results, "kg_m", None), ".3f"),
            _fmt(getattr(results, "km_m", None), ".3f"),
        ],
        "Unit": [
            "t",
            "m",
            "m",
            "m",
            "m",
            "deg",
            "m",
            "m",
            "m",
            "m",
        ],
    }
    if strength:
        eq_rows["Parameter"].append("SWBM approx.")
        eq_rows["Value"].append(_fmt(getattr(strength, "still_water_bm_approx_tm", None), ".0f"))
        eq_rows["Unit"].append("tm")

    if ancillary:
        eq_rows["Parameter"].extend(
            [
                "Propeller immersion",
                "Visibility ahead",
                "Air draft",
            ]
        )
        eq_rows["Value"].extend(
            [
                _fmt(getattr(ancillary, "prop_immersion_pct", None), ".1f"),
                _fmt(getattr(ancillary, "visibility_m", None), ".1f"),
                _fmt(getattr(ancillary, "air_draft_m", None), ".2f"),
            ]
        )
        eq_rows["Unit"].extend(["% dia", "m", "m"])

    df_eq = pd.DataFrame(eq_rows)

    # --- Sheet 3: IMO / ancillary criteria table, if available ---
    criteria = getattr(results, "criteria", None)
    crit_df = None
    if criteria is not None and getattr(criteria, "lines", None):
        crit_rows = []
        for line in criteria.lines:
            result_obj = getattr(line, "result", None)
            result_str = getattr(result_obj, "name", str(result_obj)) if result_obj is not None else ""
            crit_rows.append(
                {
                    "Group": getattr(line, "parent_code", "") or "",
                    "Code": getattr(line, "code", "") or "",
                    "Name": getattr(line, "name", "") or "",
                    "Reference": getattr(line, "reference", "") or "",
                    "Result": result_str,
                    "Value": _fmt(getattr(line, "value", None), ".3f")
                    if getattr(line, "value", None) is not None
                    else "",
                    "Limit": _fmt(getattr(line, "limit", None), ".3f")
                    if getattr(line, "limit", None) is not None
                    else "",
                    "Margin": _fmt(getattr(line, "margin", None), ".3f")
                    if getattr(line, "margin", None) is not None
                    else "",
                    "Message": getattr(line, "message", "") or "",
                }
            )
        crit_df = pd.DataFrame(crit_rows)

    # --- Write all sheets and apply basic styling ---
    with pd.ExcelWriter(str(filepath), engine="openpyxl") as writer:
        # Sheet 1 – condition summary
        df_summary.to_excel(writer, sheet_name="Condition Summary", index=False)
        ws_summary = writer.sheets["Condition Summary"]
        ws_summary.column_dimensions["A"].width = 32
        ws_summary.column_dimensions["B"].width = 40
        _style_header(ws_summary)

        # Sheet 2 – equilibrium data
        df_eq.to_excel(writer, sheet_name="Equilibrium Data", index=False)
        ws_eq = writer.sheets["Equilibrium Data"]
        ws_eq.column_dimensions["A"].width = 32
        ws_eq.column_dimensions["B"].width = 18
        ws_eq.column_dimensions["C"].width = 10
        _style_header(ws_eq)

        # Sheet 3 – IMO / ancillary criteria (optional)
        if crit_df is not None and not crit_df.empty:
            crit_df.to_excel(writer, sheet_name="IMO Criteria", index=False)
            ws_crit = writer.sheets["IMO Criteria"]
            # Set reasonable widths
            ws_crit.column_dimensions["A"].width = 10  # Group
            ws_crit.column_dimensions["B"].width = 12  # Code
            ws_crit.column_dimensions["C"].width = 28  # Name
            ws_crit.column_dimensions["D"].width = 16  # Reference
            ws_crit.column_dimensions["E"].width = 10  # Result
            ws_crit.column_dimensions["F"].width = 14  # Value
            ws_crit.column_dimensions["G"].width = 14  # Limit
            ws_crit.column_dimensions["H"].width = 14  # Margin
            ws_crit.column_dimensions["I"].width = 50  # Message
            _style_header(ws_crit)

            # Colour the Result column similar to the manual (green PASS, red FAIL, grey N/A).
            result_col_idx = list(crit_df.columns).index("Result") + 1
            for row_idx in range(2, ws_crit.max_row + 1):
                cell = ws_crit.cell(row=row_idx, column=result_col_idx)
                value = (str(cell.value) or "").upper()
                if "PASS" in value:
                    cell.fill = PatternFill(fill_type="solid", fgColor="C6EFCE")
                elif "FAIL" in value:
                    cell.fill = PatternFill(fill_type="solid", fgColor="FFC7CE")
                elif "N_A" in value or "N/A" in value:
                    cell.fill = PatternFill(fill_type="solid", fgColor="E7E6E6")
