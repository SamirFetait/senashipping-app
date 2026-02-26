"""
PDF report generation for loading conditions.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Line, String, PolyLine

from ..config.limits import MASS_PER_HEAD_T
from ..repositories import database
from ..repositories.tank_repository import TankRepository
from ..repositories.livestock_pen_repository import LivestockPenRepository

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


def _compute_gz_curve(results) -> tuple[list[int], list[float], float]:
    """Replicate the in-app GZ curve approximation using GM and validation."""
    gm_raw = float(getattr(results, "gm_m", 0.0) or 0.0)
    validation = getattr(results, "validation", None)
    gm_eff = getattr(validation, "gm_effective", gm_raw) if validation else gm_raw

    gm_for_shape = gm_eff if gm_eff is not None else gm_raw
    if gm_for_shape is None:
        gm_for_shape = 0.0
    if gm_for_shape <= 0.0:
        gm_for_shape = abs(gm_raw) if gm_raw not in (None, 0.0) else 0.01

    gm_clamped = max(0.0, min(float(gm_for_shape), 1.5))
    phi_end_deg = 40.0 + (gm_clamped / 1.5) * 50.0  # range ≈ 40°–90°

    angles_deg = list(range(0, 91, 2))

    def _approximate_gz_curve(angles: list[int], gm: float, phi_end: float) -> list[float]:
        phi_end = max(30.0, min(float(phi_end), 90.0))
        gz_vals: list[float] = []
        span_norm = (phi_end - 30.0) / 60.0
        exponent = 2.0 + (1.2 * (1.0 - span_norm))
        for a in angles:
            phi_deg = float(a)
            phi_rad = math.radians(phi_deg)
            base = math.sin(phi_rad)
            u = phi_deg / phi_end
            envelope = max(0.0, 1.0 - (u ** exponent))
            gz = gm * base * envelope
            gz_vals.append(max(0.0, gz))
        return gz_vals

    gz_values = _approximate_gz_curve(angles_deg, gm_for_shape, phi_end_deg)
    if not gz_values or max(gz_values) <= 0.0:
        fallback_gm = gm_for_shape if gm_for_shape > 0.0 else 0.5
        gz_values = _approximate_gz_curve(angles_deg, fallback_gm, 60.0)

    gm_for_display = (
        gm_eff
        if isinstance(gm_eff, (int, float)) and gm_eff is not None and gm_eff > 0.0
        else gm_for_shape
    )
    return angles_deg, gz_values, float(gm_for_display)


def _build_gz_curve_drawing(results, width: float = 16 * cm, height: float = 9 * cm) -> Drawing:
    """Create a ReportLab drawing of the GZ curve similar to the Curves view."""
    angles_deg, gz_values, gm_eff = _compute_gz_curve(results)

    d = Drawing(width, height)

    # Plot area margins inside the drawing
    left = 1.8 * cm
    right = width - 0.8 * cm
    bottom = 1.5 * cm
    top = height - 1.0 * cm

    plot_width = right - left
    plot_height = top - bottom

    max_gz = max(gz_values) if gz_values else gm_eff
    if max_gz <= 0.0:
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

    value_max = max(max_gz, gm_eff) * 1.2

    def map_point(angle_deg: float, gz: float) -> tuple[float, float]:
        x = left + (angle_deg / 90.0) * plot_width
        y = bottom + (gz / value_max) * plot_height
        return x, y

    # Axes
    axis_color = colors.HexColor("#333333")
    d.add(Line(left, bottom, right, bottom, strokeColor=axis_color, strokeWidth=1))
    d.add(Line(left, bottom, left, top, strokeColor=axis_color, strokeWidth=1))

    # X-axis ticks and labels (angle of heel)
    for angle in (0, 10, 20, 30, 40, 50, 60, 75, 90):
        x = left + (angle / 90.0) * plot_width
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

    # GM horizontal guide
    gm_y = bottom + (gm_eff / value_max) * plot_height
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
    angle_at_max = angles_deg[max_index]

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
    x_max = left + (angle_at_max / 90.0) * plot_width
    d.add(
        Line(
            x_max,
            bottom,
            x_max,
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
            x_max,
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

    # Main GZ curve
    points = []
    for angle_deg, gz in zip(angles_deg, gz_values):
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
    doc = SimpleDocTemplate(
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
        # Column widths tuned to span the printable width nicely
        items_table = Table(
            items_rows,
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
                ]
            )
        )
        story.append(items_table)
        story.append(Spacer(1, 0.6 * cm))

    # --- Section 4: IMO / ancillary criteria table (if available) ---
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

        # Column widths tuned so the table fits the page neatly
        crit_table = Table(
            crit_rows,
            colWidths=[1.3 * cm, 1.5 * cm, 3.7 * cm, 2.0 * cm, 1.6 * cm, 1.8 * cm, 1.8 * cm, 1.7 * cm],
            repeatRows=1,
        )
        # Header and grid
        base_style = [
            ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
            ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
            # Rotate header labels vertically so long words fit
            ("ROTATE", (0, 0), (-1, 0), 90),
            ("TOPPADDING", (0, 0), (-1, 0), 2),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("BACKGROUND", (0, 1), (-1, -1), "#FFFFFF"),
            ("GRID", (0, 0), (-1, -1), 0.4, "#BBBBBB"),
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

    # --- Final section: GZ curve plot (approximate, from GM) ---
    story.append(Spacer(1, 0.8 * cm))
    story.append(_section_title("Righting Lever (GZ) Curve", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_build_gz_curve_drawing(results))

    def _on_first_page(canvas, _doc) -> None:
        # PDF Info dictionary title read by most viewers
        canvas.setTitle("OSAMA BAY")

    doc.build(story, onFirstPage=_on_first_page, onLaterPages=_on_first_page)
