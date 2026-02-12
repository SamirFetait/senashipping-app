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


def export_condition_to_pdf(
    filepath: Path,
    ship: "Ship",
    voyage: "Voyage",
    condition: "LoadingCondition",
    results: "ConditionResults",
) -> None:
    """
    Generate a PDF report for a loading condition.
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
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph(f"Ship: {ship.name} (IMO: {ship.imo_number})", styles["Normal"]))
    story.append(Paragraph(
        f"Voyage: {voyage.name} - {voyage.departure_port} to {voyage.arrival_port}",
        styles["Normal"],
    ))
    story.append(Paragraph(f"Condition: {condition.name}", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    data = [
        ["Parameter", "Value"],
        ["Displacement (t)", f"{condition.displacement_t:.1f}"],
        ["Draft (m)", f"{condition.draft_m:.2f}"],
        ["Trim (m)", f"{condition.trim_m:.2f}"],
        ["GM (m)", f"{condition.gm_m:.2f}"],
        ["KG (m)", f"{results.kg_m:.2f}"],
        ["KM (m)", f"{results.km_m:.2f}"],
    ]
    if hasattr(results, "strength") and results.strength:
        data.append(["SWBM (tm)", f"{results.strength.still_water_bm_approx_tm:.0f}"])

    table = Table(data, colWidths=[8 * cm, 6 * cm])
    table.setStyle(
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
    story.append(table)
    doc.build(story)
