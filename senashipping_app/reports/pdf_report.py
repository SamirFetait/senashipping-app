"""
PDF report generation for loading conditions.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from ..models import Ship, Voyage, LoadingCondition
    from ..services.stability_service import ConditionResults


def _fmt(value: object, fmt: str) -> str:
    """Safely format numeric values for PDF tables."""
    if value is None:
        return ""
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return str(value)


def _section_title(text: str, styles) -> Paragraph:
    return Paragraph(f"<b>{text}</b>", styles["Heading3"])


def export_condition_to_pdf(
    filepath: Path,
    ship: "Ship",
    voyage: "Voyage",
    condition: "LoadingCondition",
    results: "ConditionResults",
) -> None:
    """
    Generate a PDF report for a loading condition.

    Layout is inspired by the loading manual pages:
    - Condition summary
    - Equilibrium / hydrostatic-style data
    - IMO / ancillary criteria with pass/fail indicator
    """
    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
    )

    story = []
    story.append(Paragraph("senashipping - Loading Condition Report", title_style))
    story.append(Spacer(1, 0.3 * cm))

    # Header info (ship / voyage / condition)
    story.append(
        Paragraph(
            f"Ship: {ship.name} (IMO: {getattr(ship, 'imo_number', '') or ''})",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            f"Voyage: {voyage.name} - {voyage.departure_port} to {voyage.arrival_port}",
            styles["Normal"],
        )
    )
    story.append(Paragraph(f"Condition: {condition.name}", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    # --- Section 1: Condition summary (similar to Excel sheet 1) ---
    story.append(_section_title("Condition Summary", styles))
    story.append(Spacer(1, 0.2 * cm))

    validation = getattr(results, "validation", None)
    gm_eff = getattr(validation, "gm_effective", None) if validation else None
    strength = getattr(results, "strength", None)
    ancillary = getattr(results, "ancillary", None)

    summary_rows = [
        ["Parameter", "Value"],
        ["Displacement (t)", _fmt(getattr(condition, "displacement_t", None), ".1f")],
        ["Draft mid (m)", _fmt(getattr(condition, "draft_m", None), ".3f")],
        ["Draft aft (m)", _fmt(getattr(results, "draft_aft_m", None), ".3f")],
        ["Draft fwd (m)", _fmt(getattr(results, "draft_fwd_m", None), ".3f")],
        ["Trim (m, +ve stern down)", _fmt(getattr(condition, "trim_m", None), ".3f")],
        ["Heel (deg)", _fmt(getattr(results, "heel_deg", None), ".2f")],
        ["GM (effective, m)", _fmt(gm_eff, ".3f")],
        ["GM (raw, m)", _fmt(getattr(results, "gm_m", None), ".3f")],
        ["KG (m)", _fmt(getattr(results, "kg_m", None), ".3f")],
        ["KM (m)", _fmt(getattr(results, "km_m", None), ".3f")],
    ]
    if strength:
        summary_rows.append(
            ["SWBM approx. (tm)", _fmt(getattr(strength, "still_water_bm_approx_tm", None), ".0f")]
        )
    if ancillary:
        summary_rows.extend(
            [
                ["Propeller immersion (%)", _fmt(getattr(ancillary, "prop_immersion_pct", None), ".1f")],
                ["Visibility ahead (m)", _fmt(getattr(ancillary, "visibility_m", None), ".1f")],
                ["Air draft (m)", _fmt(getattr(ancillary, "air_draft_m", None), ".2f")],
                [
                    "GZ criteria OK",
                    "YES" if getattr(ancillary, "gz_criteria_ok", False) else "NO",
                ],
            ]
        )

    summary_table = Table(summary_rows, colWidths=[8 * cm, 6 * cm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
                ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), "#E7E6E6"),
                ("GRID", (0, 0), (-1, -1), 0.5, "gray"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.5 * cm))

    # --- Section 2: Equilibrium / hydrostatic-style data ---
    story.append(_section_title("Equilibrium Data", styles))
    story.append(Spacer(1, 0.2 * cm))

    eq_rows = [
        ["Parameter", "Value", "Unit"],
        ["Displacement", _fmt(getattr(results, "displacement_t", None), ".1f"), "t"],
        ["Draft amidships", _fmt(getattr(results, "draft_m", None), ".3f"), "m"],
        ["Draft at AP", _fmt(getattr(results, "draft_aft_m", None), ".3f"), "m"],
        ["Draft at FP", _fmt(getattr(results, "draft_fwd_m", None), ".3f"), "m"],
        ["Trim (stern down)", _fmt(getattr(results, "trim_m", None), ".3f"), "m"],
        ["Heel", _fmt(getattr(results, "heel_deg", None), ".2f"), "deg"],
        ["GM (effective)", _fmt(gm_eff, ".3f"), "m"],
        ["GM (raw)", _fmt(getattr(results, "gm_m", None), ".3f"), "m"],
        ["KG", _fmt(getattr(results, "kg_m", None), ".3f"), "m"],
        ["KM", _fmt(getattr(results, "km_m", None), ".3f"), "m"],
    ]
    if strength:
        eq_rows.append(
            ["SWBM approx.", _fmt(getattr(strength, "still_water_bm_approx_tm", None), ".0f"), "tm"]
        )
    if ancillary:
        eq_rows.extend(
            [
                [
                    "Propeller immersion",
                    _fmt(getattr(ancillary, "prop_immersion_pct", None), ".1f"),
                    "% dia",
                ],
                ["Visibility ahead", _fmt(getattr(ancillary, "visibility_m", None), ".1f"), "m"],
                ["Air draft", _fmt(getattr(ancillary, "air_draft_m", None), ".2f"), "m"],
            ]
        )

    eq_table = Table(eq_rows, colWidths=[7 * cm, 4 * cm, 3 * cm])
    eq_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
                ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), "#E7E6E6"),
                ("GRID", (0, 0), (-1, -1), 0.5, "gray"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(eq_table)
    story.append(Spacer(1, 0.5 * cm))

    # --- Section 3: IMO / ancillary criteria table (if available) ---
    criteria = getattr(results, "criteria", None)
    if criteria is not None and getattr(criteria, "lines", None):
        story.append(_section_title("IMO / Livestock / Ancillary Criteria", styles))
        story.append(Spacer(1, 0.2 * cm))

        crit_rows = [
            [
                "Group",
                "Code",
                "Name",
                "Reference",
                "Result",
                "Value",
                "Limit",
                "Margin",
            ]
        ]
        for line in criteria.lines:
            result_obj = getattr(line, "result", None)
            result_str = getattr(result_obj, "name", str(result_obj)) if result_obj is not None else ""
            crit_rows.append(
                [
                    getattr(line, "parent_code", "") or "",
                    getattr(line, "code", "") or "",
                    getattr(line, "name", "") or "",
                    getattr(line, "reference", "") or "",
                    result_str,
                    _fmt(getattr(line, "value", None), ".3f")
                    if getattr(line, "value", None) is not None
                    else "",
                    _fmt(getattr(line, "limit", None), ".3f")
                    if getattr(line, "limit", None) is not None
                    else "",
                    _fmt(getattr(line, "margin", None), ".3f")
                    if getattr(line, "margin", None) is not None
                    else "",
                ]
            )

        crit_table = Table(crit_rows, colWidths=[2 * cm, 2.5 * cm, 5.5 * cm, 3 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])
        # Header and grid
        base_style = [
            ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
            ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("BACKGROUND", (0, 1), (-1, -1), "#FFFFFF"),
            ("GRID", (0, 0), (-1, -1), 0.25, "gray"),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]

        # Add per-row colouring for Result column (similar to Excel).
        result_col = 4
        for i in range(1, len(crit_rows)):
            text = str(crit_rows[i][result_col]).upper()
            if "PASS" in text:
                base_style.append(
                    ("BACKGROUND", (result_col, i), (result_col, i), "#C6EFCE")
                )
            elif "FAIL" in text:
                base_style.append(
                    ("BACKGROUND", (result_col, i), (result_col, i), "#FFC7CE")
                )
            elif "N_A" in text or "N/A" in text:
                base_style.append(
                    ("BACKGROUND", (result_col, i), (result_col, i), "#E7E6E6")
                )

        crit_table.setStyle(TableStyle(base_style))
        story.append(crit_table)

    doc.build(story)
