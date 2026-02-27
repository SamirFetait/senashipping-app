"""
PDF report generation for loading conditions.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, Line, String, PolyLine

from senashipping_app.config.limits import MASS_PER_HEAD_T
from senashipping_app.repositories import database
from senashipping_app.repositories.tank_repository import TankRepository
from senashipping_app.repositories.livestock_pen_repository import LivestockPenRepository
from senashipping_app.services.gz_curve_plot import (
    compute_gz_curve_stats,
    get_kn_table_dict,
)

if TYPE_CHECKING:
    from senashipping_app.models import Ship, Voyage, LoadingCondition
    from senashipping_app.services.stability_service import ConditionResults


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


def _deck_to_letter(deck: str) -> str | None:
    """Normalize Ship Manager deck value to A–H so it matches loading tabs."""
    s = (deck or "").strip().upper()
    if not s:
        return None
    deck_letters = ("A", "B", "C", "D", "E", "F", "G", "H")
    if s in deck_letters:
        return s
    if s.isdigit() and 1 <= int(s) <= 8:
        return chr(ord("A") + int(s) - 1)
    if s.startswith("DK") and s[2:].strip().isdigit():
        n = int(s[2:].strip())
        if 1 <= n <= 8:
            return chr(ord("A") + n - 1)
    return s if s in deck_letters else None


def _build_items_table(ship, condition, results) -> list[list[str]] | None:
    """
    Build a compact items / FSM-style table combining pens and tanks.

    Columns:
        Item | Quantity / Fill | Unit mass (t) | Total mass (t) |
        Long. arm (m) | Vert. arm (m) | Total FSM (t·m) | FSM Type
    """
    pen_loadings = getattr(condition, "pen_loadings", None) or {}
    tank_volumes = getattr(condition, "tank_volumes_m3", None) or {}
    if not pen_loadings and not tank_volumes:
        return None

    headers = [
        "Item",
        "Quantity / Fill",
        "Unit mass (t)",
        "Total mass (t)",
        "Long. arm (m)",
        "Vert. arm (m)",
        "Total FSM (t·m)",
        "FSM Type",
    ]
    rows: list[list[str]] = [headers]

    # Try to pull detailed pen and tank data from the database when available so
    # that we can compute realistic arms per deck and per tank.
    pens = []
    tanks = []
    if getattr(ship, "id", None) and database.SessionLocal is not None:
        with database.SessionLocal() as db:
            pens = LivestockPenRepository(db).list_for_ship(ship.id)
            tanks = TankRepository(db).list_for_ship(ship.id)

    # --- Pens (livestock) rows by deck (DECK A, DECK B, ...) ------------------
    if pens and pen_loadings:
        pen_by_id = {p.id: p for p in pens if p.id is not None}
        deck_groups: dict[str, dict[str, float]] = {}
        for pen_id, heads in pen_loadings.items():
            try:
                heads_int = int(heads)
            except (TypeError, ValueError):
                continue
            if heads_int <= 0:
                continue
            pen = pen_by_id.get(pen_id)
            if not pen:
                continue
            deck_letter = _deck_to_letter(getattr(pen, "deck", "") or "") or (getattr(pen, "deck", "") or "")
            if not deck_letter:
                continue
            grp = deck_groups.setdefault(
                deck_letter,
                {"heads": 0.0, "mass": 0.0, "lcg_moment": 0.0, "vcg_moment": 0.0},
            )
            mass = heads_int * MASS_PER_HEAD_T
            grp["heads"] += heads_int
            grp["mass"] += mass
            grp["lcg_moment"] += mass * float(getattr(pen, "lcg_m", 0.0) or 0.0)
            grp["vcg_moment"] += mass * float(getattr(pen, "vcg_m", 0.0) or 0.0)

        for deck_key in sorted(deck_groups):
            grp = deck_groups[deck_key]
            mass = grp["mass"]
            heads_total = int(grp["heads"])
            if heads_total <= 0:
                continue
            long_arm = grp["lcg_moment"] / mass if mass > 0 else 0.0
            vert_arm = grp["vcg_moment"] / mass if mass > 0 else 0.0
            rows.append(
                [
                    f"DECK {deck_key}",
                    str(heads_total),
                    _fmt(MASS_PER_HEAD_T, ".2f"),
                    _fmt(mass, ".2f"),
                    _fmt(long_arm, ".2f") if mass > 0 else "",
                    _fmt(vert_arm, ".2f") if mass > 0 else "",
                    "",
                    "N/A (pens)",
                ]
            )
    elif pen_loadings:
        # Fallback: aggregate pens when we cannot resolve decks (no DB).
        total_heads = sum(max(0, int(h)) for h in pen_loadings.values())
        if total_heads > 0:
            rows.append(
                [
                    "Livestock (pens)",
                    str(total_heads),
                    _fmt(MASS_PER_HEAD_T, ".2f"),
                    _fmt(total_heads * MASS_PER_HEAD_T, ".2f"),
                    "",
                    "",
                    "",
                    "N/A (pens)",
                ]
            )

    # --- Tanks rows (one per tank) -------------------------------------------
    snapshot = getattr(results, "snapshot", None)
    inputs = getattr(snapshot, "inputs", {}) if snapshot else {}
    cargo_density = float(inputs.get("cargo_density_t_per_m3", 1.0) or 1.0)

    total_tank_mass = 0.0
    total_tank_lcg_moment = 0.0
    total_tank_vcg_moment = 0.0
    if tanks and tank_volumes:
        tank_by_id = {t.id: t for t in tanks if t.id is not None}
        L = float(getattr(ship, "length_overall_m", 0.0) or 0.0)
        if L <= 0.0:
            L = 0.0
        for tid, vol_m3 in tank_volumes.items():
            try:
                vol = float(vol_m3)
            except (TypeError, ValueError):
                continue
            if vol <= 0.0:
                continue
            tank = tank_by_id.get(tid)
            name = getattr(tank, "name", None) if tank else None
            item_label = name or f"Tank {tid}"
            mass_t = vol * cargo_density
            total_tank_mass += mass_t
            # Longitudinal arm in metres (handle stored as 0–1 or metres)
            if tank and L > 0.0:
                pos = float(getattr(tank, "longitudinal_pos", 0.0) or 0.0)
                if pos > 1.5:
                    lcg_m = pos
                else:
                    lcg_m = pos * L
            else:
                lcg_m = 0.0
            vcg_m = float(getattr(tank, "kg_m", 0.0) or 0.0) if tank else 0.0
            total_tank_lcg_moment += mass_t * lcg_m
            total_tank_vcg_moment += mass_t * vcg_m

            rows.append(
                [
                    item_label,
                    _fmt(vol, ".1f") + " m³",
                    _fmt(cargo_density, ".3f"),
                    _fmt(mass_t, ".2f"),
                    _fmt(lcg_m, ".2f") if lcg_m else "",
                    _fmt(vcg_m, ".2f") if vcg_m else "",
                    "",
                    "N/A (tanks)",
                ]
            )

    # --- Aggregate FSM row (all tanks) ---------------------------------------
    if tank_volumes:
        gm_raw = getattr(results, "gm_m", None)
        validation = getattr(results, "validation", None)
        gm_eff = getattr(validation, "gm_effective", None) if validation else None
        total_fsm = ""
        fsm_type = "N/A"
        try:
            if gm_raw is not None and gm_eff is not None and float(gm_raw) > 0:
                fsc = float(gm_raw) - float(gm_eff)
                if fsc > 0 and getattr(results, "displacement_t", None):
                    total_fsm_val = fsc * float(results.displacement_t)
                    total_fsm = _fmt(total_fsm_val, ".1f")
                    fsm_type = "Aggregate FSM (from GM eff.)"
        except (TypeError, ValueError):
            total_fsm = ""
            fsm_type = "N/A"

        rows.append(
            [
                "FSM total (all tanks)",
                "",
                "",
                "",
                "",
                "",
                total_fsm,
                fsm_type,
            ]
        )

    return rows if len(rows) > 1 else None


def _compute_gz_curve_from_kn(
    results,
) -> tuple[list[float], list[float], float, float, float, float]:
    """
    Compute GZ curve from KN tables, matching the Curves view.

    Returns (angles_deg, gz_values, max_gz, angle_at_max, area_m_rad, range_positive_deg).
    When data is missing or invalid, returns empty curves and zeros.
    """
    kg_m = float(getattr(results, "kg_m", 0.0) or 0.0)
    displacement_t = float(getattr(results, "displacement_t", 0.0) or 0.0)
    trim_m = float(getattr(results, "trim_m", 0.0) or 0.0)

    if kg_m <= 0.0 or displacement_t <= 0.0:
        return [], [], 0.0, 0.0, 0.0, 0.0

    kn_table = get_kn_table_dict(displacement_t, trim_m)
    if not kn_table:
        return [], [], 0.0, 0.0, 0.0, 0.0

    return compute_gz_curve_stats(kg_m, kn_table)


def _build_gz_curve_drawing(results, width: float = 16 * cm, height: float = 9 * cm) -> Drawing:
    """Create a ReportLab drawing of the GZ curve from KN tables (same as Curves view)."""
    angles_deg, gz_values, max_gz, angle_at_max, area_m_rad, range_positive = _compute_gz_curve_from_kn(results)

    d = Drawing(width, height)

    # Plot area margins inside the drawing
    left = 1.8 * cm
    right = width - 0.8 * cm
    bottom = 1.5 * cm
    top = height - 1.0 * cm

    plot_width = right - left
    plot_height = top - bottom

    if not gz_values or max(gz_values) <= 0.0:
        d.add(
            String(
                width / 2,
                height / 2,
                "No positive GZ values to plot.",
                textAnchor="middle",
                fontSize=9,
                fillColor=colors.HexColor("#555555"),
            )
        )
        return d

    gm_eff = float(getattr(results, "gm_m", 0.0) or 0.0)
    # Match Curves view: scale Y based on max GZ, not GM
    max_gz = max(gz_values)
    value_max = max_gz * 1.2 if max_gz > 0.0 else 1.0

    # Match Curves view: X axis and curve stop at last positive GZ (range of positive stability)
    # Build plotting arrays truncated at the last positive GZ, including an interpolated zero-crossing.
    if range_positive > 0.0:
        x_max = range_positive
    else:
        x_max = max(angles_deg) if angles_deg else 90.0

    plot_angles: list[float] = []
    plot_gz: list[float] = []
    for i, (a, g) in enumerate(zip(angles_deg, gz_values)):
        a_f = float(a)
        g_f = float(g)
        if a_f < x_max:
            plot_angles.append(a_f)
            plot_gz.append(g_f)
            continue
        if a_f == x_max:
            plot_angles.append(a_f)
            plot_gz.append(max(0.0, g_f))
            break
        # a_f > x_max: interpolate between previous point and this one to get GZ at x_max
        if not plot_angles:
            break
        a0 = plot_angles[-1]
        g0 = plot_gz[-1]
        span = a_f - a0
        t = 0.0 if span == 0.0 else (x_max - a0) / span
        g_x = g0 + t * (g_f - g0)
        plot_angles.append(x_max)
        plot_gz.append(max(0.0, g_x))
        break
    if not plot_angles:
        plot_angles = [float(a) for a in angles_deg]
        plot_gz = [float(g) for g in gz_values]

    def map_point(angle_deg: float, gz: float) -> tuple[float, float]:
        x = left + (angle_deg / x_max) * plot_width
        y = bottom + (gz / value_max) * plot_height
        return x, y

    # Axes
    axis_color = colors.HexColor("#333333")
    d.add(Line(left, bottom, right, bottom, strokeColor=axis_color, strokeWidth=1))
    d.add(Line(left, bottom, left, top, strokeColor=axis_color, strokeWidth=1))

    # X-axis ticks and labels (angle of heel)
    for angle in (0, 10, 20, 30, 40, 50, 60, 75, 90):
        if angle > x_max:
            continue
        x = left + (angle / x_max) * plot_width
        d.add(Line(x, bottom, x, bottom - 4, strokeColor=axis_color, strokeWidth=0.8))
        d.add(
            String(
                x,
                bottom - 10,
                str(angle),
                textAnchor="middle",
                fontSize=8,
                fillColor=axis_color,
            )
        )

    # Y-axis ticks (GZ)
    num_y_ticks = 4
    for i in range(1, num_y_ticks + 1):
        val = value_max * i / num_y_ticks
        y = bottom + (val / value_max) * plot_height
        d.add(Line(left, y, left - 4, y, strokeColor=axis_color, strokeWidth=0.8))
        d.add(
            String(
                left - 6,
                y - 3,
                f"{val:.2f}",
                textAnchor="end",
                fontSize=8,
                fillColor=axis_color,
            )
        )

    # Axis titles
    d.add(
        String(
            left + plot_width / 2,
            0.4 * cm,
            "Angle of heel (degrees) φ",
            textAnchor="middle",
            fontSize=9,
            fillColor=axis_color,
        )
    )
    d.add(
        String(
            0.4 * cm,
            bottom + plot_height / 2,
            "Righting lever, GZ (m)",
            textAnchor="middle",
            fontSize=9,
            fillColor=axis_color,
            angle=90,
        )
    )

    # GM horizontal guide (clamped into plot area)
    gm_clamped = max(0.0, min(gm_eff, value_max))
    gm_y = bottom + (gm_clamped / value_max) * plot_height
    gm_color = colors.HexColor("#808080")
    d.add(
        Line(
            left,
            gm_y,
            right,
            gm_y,
            strokeColor=gm_color,
            strokeWidth=0.8,
            strokeDashArray=[3, 2],
        )
    )
    d.add(
        String(
            right - 4,
            gm_y + 4,
            "GM",
            textAnchor="end",
            fontSize=8,
            fillColor=gm_color,
        )
    )

    # GZmax guides
    max_index = max(range(len(gz_values)), key=lambda i: gz_values[i])
    gz_max = gz_values[max_index]
    # angle_at_max from stats is more precise than from index alone, but keep both aligned
    angle_at_max_stat = angle_at_max
    angle_at_max = angle_at_max_stat if angle_at_max_stat else angles_deg[max_index]

    gzmax_y = bottom + (gz_max / value_max) * plot_height
    guide_color = colors.HexColor("#999999")
    d.add(
        Line(
            left,
            gzmax_y,
            right,
            gzmax_y,
            strokeColor=guide_color,
            strokeWidth=0.8,
            strokeDashArray=[3, 2],
        )
    )
    x_max_pos = left + (angle_at_max / x_max) * plot_width
    d.add(
        Line(
            x_max_pos,
            bottom,
            x_max_pos,
            top,
            strokeColor=guide_color,
            strokeWidth=0.8,
            strokeDashArray=[3, 2],
        )
    )

    d.add(
        String(
            left + 4,
            gzmax_y + 4,
            "GZmax",
            textAnchor="start",
            fontSize=8,
            fillColor=guide_color,
        )
    )
    d.add(
        String(
            x_max_pos,
            top + 4,
            f"{angle_at_max}° at GZmax",
            textAnchor="middle",
            fontSize=8,
            fillColor=guide_color,
        )
    )

    # Angle of vanishing stability marker at 90°
    x_90 = right
    d.add(
        String(
            x_90,
            bottom - 22,
            "Angle of vanishing stability",
            textAnchor="middle",
            fontSize=8,
            fillColor=guide_color,
        )
    )

    # Main GZ curve (truncated at last positive GZ)
    points = []
    for angle_deg, gz in zip(plot_angles, plot_gz):
        x, y = map_point(float(angle_deg), float(gz))
        points.append((x, y))

    if points:
        flat_points: list[float] = []
        for x, y in points:
            flat_points.extend([x, y])
        d.add(
            PolyLine(
                flat_points,
                strokeColor=colors.HexColor("#2c3e50"),
                strokeWidth=1.8,
            )
        )

    return d


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
    doc = BaseDocTemplate(
        str(filepath),
        pagesize=A4,
        rightMargin=2.2 * cm,
        leftMargin=2.2 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
    )
    # Set document-level title metadata so viewers (e.g. browsers) show "OSAMA BAY"
    # instead of "anonymous" in their title / metadata panes.
    doc.title = "OSAMA BAY"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        spaceAfter=6,
    )
    styles["Heading3"].spaceBefore = 6
    styles["Heading3"].spaceAfter = 2
    styles["Normal"].spaceAfter = 2

    def _draw_page_frame(canvas, _doc) -> None:
        # Apply document title metadata and draw a border frame on every page.
        canvas.setTitle("OSAMA BAY")
        # Use the actual canvas page size so the frame matches
        # both portrait and landscape templates correctly.
        width, height = canvas._pagesize
        margin = 0.7 * cm
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#000000"))
        canvas.setLineWidth(0.7)
        canvas.rect(margin, margin, width - 2 * margin, height - 2 * margin, stroke=1, fill=0)
        canvas.restoreState()

    # Page templates: portrait for the main summary/content, landscape for criteria
    # and GZ-curve pages.
    portrait_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="portrait_frame",
    )
    portrait_template = PageTemplate(
        id="Portrait",
        frames=[portrait_frame],
        onPage=_draw_page_frame,
        pagesize=A4,
    )

    landscape_size = landscape(A4)
    landscape_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        landscape_size[0] - doc.leftMargin - doc.rightMargin,
        landscape_size[1] - doc.topMargin - doc.bottomMargin,
        id="landscape_frame",
    )
    landscape_template = PageTemplate(
        id="Landscape",
        frames=[landscape_frame],
        onPage=_draw_page_frame,
        pagesize=landscape_size,
    )

    doc.addPageTemplates([portrait_template, landscape_template])

    story = []
    story.append(Paragraph("senashipping - Loading Condition Report", title_style))
    story.append(Spacer(1, 0.3 * cm))

    # Header info (ship / condition)
    story.append(
        Paragraph(
            f"Ship: {ship.name} (IMO: {getattr(ship, 'imo_number', '') or ''})",
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
                ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
                ("GRID", (0, 0), (-1, -1), 0.4, "#BBBBBB"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
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
                ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
                ("GRID", (0, 0), (-1, -1), 0.4, "#BBBBBB"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(eq_table)
    story.append(Spacer(1, 0.5 * cm))

    # --- Section 3: Items / FSM-style summary ---
    items_rows = _build_items_table(ship, condition, results)
    if items_rows:
        story.append(_section_title("Weight Items and Free Surface Summary", styles))
        story.append(Spacer(1, 0.2 * cm))

        # Wrap cell contents so long text stays within column width.
        items_header_style = ParagraphStyle(
            "ItemsHeader",
            parent=styles["Heading4"],
            fontSize=8,
            leading=9,
            alignment=1,  # center
            spaceBefore=0,
            spaceAfter=0,
        )
        items_cell_style = ParagraphStyle(
            "ItemsCell",
            parent=styles["Normal"],
            fontSize=7,
            leading=8,
            spaceBefore=0,
            spaceAfter=0,
        )

        wrapped_items_rows: list[list[object]] = []
        for r, row in enumerate(items_rows):
            wrapped_row: list[object] = []
            for cell in row:
                text = "" if cell is None else str(cell)
                if r == 0:
                    wrapped_row.append(Paragraph(text, items_header_style))
                else:
                    wrapped_row.append(Paragraph(text, items_cell_style))
            wrapped_items_rows.append(wrapped_row)

        # Column widths tuned to span the printable width nicely
        items_table = Table(
            wrapped_items_rows,
            colWidths=[3.5 * cm, 1.7 * cm, 1.7 * cm, 1.9 * cm, 1.9 * cm, 1.9 * cm, 1.9 * cm, 1.9 * cm],
            repeatRows=1,
        )
        items_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("BACKGROUND", (0, 1), (-1, -1), "#FFFFFF"),
                    ("GRID", (0, 0), (-1, -1), 0.4, "#BBBBBB"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
                ]
            )
        )
        story.append(items_table)
        story.append(Spacer(1, 0.6 * cm))

    # --- Section 4: IMO / ancillary criteria table (if available) ---
    criteria = getattr(results, "criteria", None)
    has_criteria = bool(criteria is not None and getattr(criteria, "lines", None))

    if has_criteria:
        # Move to a dedicated landscape page for the criteria table.
        story.append(NextPageTemplate("Landscape"))
        story.append(PageBreak())

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

        # Wrap all cell contents into Paragraphs so long text
        # breaks onto multiple lines instead of overflowing columns.
        crit_header_style = ParagraphStyle(
            "CriteriaHeader",
            parent=styles["Heading4"],
            fontSize=8,
            leading=9,
            alignment=1,  # center
            spaceBefore=0,
            spaceAfter=0,
        )
        crit_cell_style = ParagraphStyle(
            "CriteriaCell",
            parent=styles["Normal"],
            fontSize=7,
            leading=8,
            spaceBefore=0,
            spaceAfter=0,
        )

        crit_rows_wrapped: list[list[object]] = []
        for r, row in enumerate(crit_rows):
            wrapped_row: list[object] = []
            for cell in row:
                text = "" if cell is None else str(cell)
                if r == 0:
                    wrapped_row.append(Paragraph(text, crit_header_style))
                else:
                    wrapped_row.append(Paragraph(text, crit_cell_style))
            crit_rows_wrapped.append(wrapped_row)

        # Column widths tuned to use the full landscape text width.
        available_width = landscape_size[0] - doc.leftMargin - doc.rightMargin
        width_fractions = [0.09, 0.09, 0.28, 0.15, 0.11, 0.09, 0.09, 0.10]
        col_widths = [f * available_width for f in width_fractions]

        crit_table = Table(
            crit_rows_wrapped,
            colWidths=col_widths,
            repeatRows=1,
            hAlign="LEFT",
        )
        # Header and grid
        base_style = [
            ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
            ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
            ("BACKGROUND", (0, 1), (-1, -1), "#FFFFFF"),
            ("GRID", (0, 0), (-1, -1), 0.4, "#BBBBBB"),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
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

        # Prepare the next full landscape page for the GZ curve.
        story.append(NextPageTemplate("Landscape"))
        story.append(PageBreak())
    else:
        # No criteria table; still allocate a dedicated landscape page for the GZ curve.
        story.append(NextPageTemplate("Landscape"))
        story.append(PageBreak())

    # --- Final section: GZ curve plot (from KN tables, same as Curves view) ---
    story.append(_section_title("Righting Lever (GZ) Curve", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_build_gz_curve_drawing(results, width=24 * cm, height=13 * cm))

    doc.build(story)
