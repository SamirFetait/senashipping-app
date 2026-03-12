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
from senashipping_app.config.stability_manual_ref import (
    REF_LIGHTSHIP_DISPLACEMENT_T,
    REF_LIGHTSHIP_KG_M,
    REF_LIGHTSHIP_LCG_NORM,
    REF_LIGHTSHIP_TCG_M,
)
from senashipping_app.reports.equilibrium_data import build_equilibrium_data
from senashipping_app.repositories import database
from senashipping_app.repositories.tank_repository import TankRepository
from senashipping_app.repositories.livestock_pen_repository import LivestockPenRepository
from senashipping_app.services.gz_curve_plot import (
    compute_gz_curve_stats,
    get_kn_table_dict,
    prepare_gz_curve_display_points,
    estimate_gm_from_gz_curve,
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
    pen_mass_per_head_overrides = getattr(condition, "pen_mass_per_head_t", None) or {}
    tank_volumes = getattr(condition, "tank_volumes_m3", None) or {}
    raw_tank_fsm_map = getattr(condition, "tank_fsm_mt", None) or {}
    # Normalise tank FSM map so keys are integers and values are floats.
    tank_fsm_map: dict[int, float] = {}
    for key, value in raw_tank_fsm_map.items():
        try:
            tid_key = int(key)
        except (TypeError, ValueError):
            # If key is already an int or cannot be parsed, skip non-int keys.
            if isinstance(key, int):
                tid_key = key
            else:
                continue
        try:
            fsm_val = float(value)
        except (TypeError, ValueError):
            continue
        tank_fsm_map[tid_key] = fsm_val
    if not pen_loadings and not tank_volumes:
        # Lightship-only condition: still show a single Lightship row.
        lightship_mass_t = max(
            0.0,
            float(getattr(ship, "lightship_displacement_t", 0.0) or 0.0),
        ) or REF_LIGHTSHIP_DISPLACEMENT_T
        L = float(getattr(ship, "length_overall_m", 0.0) or 0.0)
        lcg_m = REF_LIGHTSHIP_LCG_NORM * L if L > 0.0 else 0.0
        tcg_m = REF_LIGHTSHIP_TCG_M
        vcg_m = REF_LIGHTSHIP_KG_M
        headers = [
            "Item",
            "Quantity",
            "Unit mass (t)",
            "Total mass (t)",
            "Long. arm (m)",
            "Trans. arm (m)",
            "Vert. arm (m)",
            "Total FSM (t·m)",
            "FSM Type",
        ]
        return [
            headers,
            [
                "Lightship",
                "1",
                _fmt(lightship_mass_t, ".1f"),
                _fmt(lightship_mass_t, ".1f"),
                _fmt(lcg_m, ".3f") if lcg_m else "",
                _fmt(tcg_m, ".3f") if tcg_m else "",
                _fmt(vcg_m, ".3f") if vcg_m else "",
                "",
                "User Specified",
            ],
        ]

    headers = [
        "Item",
        "Quantity",
        "Unit mass (t)",
        "Total mass (t)",
        "Long. arm (m)",
        "Trans. arm (m)",
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

    # --- Lightship row (always first) -----------------------------------------
    lightship_mass_t = max(
        0.0,
        float(getattr(ship, "lightship_displacement_t", 0.0) or 0.0),
    ) or REF_LIGHTSHIP_DISPLACEMENT_T
    L_ship = float(getattr(ship, "length_overall_m", 0.0) or 0.0)
    lightship_lcg_m = REF_LIGHTSHIP_LCG_NORM * L_ship if L_ship > 0.0 else 0.0
    lightship_vcg_m = REF_LIGHTSHIP_KG_M
    lightship_tcg_m = REF_LIGHTSHIP_TCG_M
    rows.append(
        [
            "Lightship",
            "1",
            _fmt(lightship_mass_t, ".1f"),
            _fmt(lightship_mass_t, ".1f"),
            _fmt(lightship_lcg_m, ".3f"),
            _fmt(lightship_tcg_m if lightship_tcg_m is not None else 0.0, ".3f"),
            _fmt(lightship_vcg_m, ".3f"),
            "",
            "User Specified",
        ]
    )

    # --- Pens (livestock) rows -----------------------------------------------
    if pens and pen_loadings:
        pen_by_id = {p.id: p for p in pens if p.id is not None}
        deck_groups: dict[str, dict[str, float]] = {}
        deck_h_rows: list[list[str]] = []
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
            per_head_mass = pen_mass_per_head_overrides.get(pen_id, MASS_PER_HEAD_T)
            mass = heads_int * per_head_mass
            long_arm_pen = float(getattr(pen, "lcg_m", 0.0) or 0.0)
            trans_arm_pen = float(getattr(pen, "tcg_m", 0.0) or 0.0)
            vert_arm_pen = float(getattr(pen, "vcg_m", 0.0) or 0.0)
            if deck_letter == "H":
                # Deck H (8): show each item as its own row directly under Lightship.
                deck_h_rows.append(
                    [
                        getattr(pen, "name", f"Deck H item {pen_id}"),
                        "1",
                        _fmt(mass, ".2f"),  # Unit mass column shows total weight for deck items
                        _fmt(mass, ".2f"),
                        _fmt(long_arm_pen, ".2f") if long_arm_pen else "",
                        _fmt(trans_arm_pen if trans_arm_pen is not None else 0.0, ".3f"),
                        _fmt(vert_arm_pen, ".2f") if vert_arm_pen else "",
                        "0.000",
                        "User Specified",
                    ]
                )
            else:
                grp = deck_groups.setdefault(
                    deck_letter,
                    {"heads": 0.0, "mass": 0.0, "lcg_moment": 0.0, "vcg_moment": 0.0},
                )
                grp["heads"] += heads_int
                grp["mass"] += mass
                grp["lcg_moment"] += mass * long_arm_pen
                grp["vcg_moment"] += mass * vert_arm_pen

        # Insert Deck H item rows directly after Lightship.
        rows.extend(sorted(deck_h_rows, key=lambda r: r[0]))

        # Then append aggregated rows for all other decks.
        for deck_key in sorted(k for k in deck_groups.keys() if k != "H"):
            grp = deck_groups[deck_key]
            mass = grp["mass"]
            heads_total = int(grp["heads"])
            if heads_total <= 0:
                continue
            long_arm = grp["lcg_moment"] / mass if mass > 0 else 0.0
            # For aggregated decks, transverse arm is not stored; show 0.000.
            trans_arm = 0.0
            vert_arm = grp["vcg_moment"] / mass if mass > 0 else 0.0
            rows.append(
                [
                    f"DECK {deck_key}",
                    "1",
                    _fmt(mass, ".2f"),  # Unit mass column shows total weight for deck items
                    _fmt(mass, ".2f"),
                    _fmt(long_arm, ".2f") if mass > 0 else "",
                    _fmt(trans_arm if trans_arm is not None else 0.0, ".3f"),
                    _fmt(vert_arm, ".2f") if mass > 0 else "",
                    "0.000",
                    "User Specified",
                ]
            )
    elif pen_loadings:
        # Fallback: aggregate pens when we cannot resolve decks (no DB).
        total_heads = sum(max(0, int(h)) for h in pen_loadings.values())
        if total_heads > 0:
            total_mass = total_heads * MASS_PER_HEAD_T
            rows.append(
                [
                    "Livestock (pens)",
                    "1",
                    _fmt(total_mass, ".2f"),  # Unit mass column shows total weight for deck items
                    _fmt(total_mass, ".2f"),
                    "0.000",
                    "",
                    "",
                    "",
                    "User Specified",
                ]
            )

    # --- Tanks rows (one per tank) -------------------------------------------
    snapshot = getattr(results, "snapshot", None)
    inputs = getattr(snapshot, "inputs", {}) if snapshot else {}
    cargo_density = float(inputs.get("cargo_density_t_per_m3", 1.0) or 1.0)

    total_tank_mass = 0.0
    total_tank_lcg_moment = 0.0
    total_tank_vcg_moment = 0.0
    total_tank_tcg_moment = 0.0
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
            tcg_m = float(getattr(tank, "tcg_m", 0.0) or 0.0) if tank else 0.0
            total_tank_lcg_moment += mass_t * lcg_m
            total_tank_vcg_moment += mass_t * vcg_m
            total_tank_tcg_moment += mass_t * tcg_m

            # Quantity / Fill: show percentage fill when capacity is known, otherwise volume.
            if tank and getattr(tank, "capacity_m3", None):
                try:
                    cap_m3 = float(getattr(tank, "capacity_m3", 0.0) or 0.0)
                except (TypeError, ValueError):
                    cap_m3 = 0.0
            else:
                cap_m3 = 0.0
            if cap_m3 > 0.0:
                fill_pct = max(0.0, min(200.0, (vol / cap_m3) * 100.0))
                quantity_cell = f"{fill_pct:.0f}%"
            else:
                quantity_cell = _fmt(vol, ".1f") + " m³"

            # Unit mass column: show tank capacity (in tonnes) when known, otherwise current mass.
            if cap_m3 > 0.0:
                unit_mass_t = cap_m3 * cargo_density
            else:
                unit_mass_t = mass_t

            # Per-tank FSM: use exact value from condition when available; otherwise 0.000.
            fsm_val = tank_fsm_map.get(tid, 0.0)

            rows.append(
                [
                    item_label,
                    quantity_cell,
                    _fmt(unit_mass_t, ".2f"),
                    _fmt(mass_t, ".2f"),
                    _fmt(lcg_m, ".2f") if lcg_m else "",
                    _fmt(tcg_m if tcg_m is not None else 0.0, ".3f"),
                    _fmt(vcg_m, ".2f") if vcg_m else "",
                    _fmt(fsm_val, ".3f"),
                    "Maximum",
                ]
            )

    # --- Summary rows: totals for tanks and full loadcase ---------------------
    # Compute overall totals for tanks (using accumulated mass and moments).
    total_fsm_tanks = sum(tank_fsm_map.values()) if tank_fsm_map else 0.0
    if total_tank_mass > 0.0:
        tanks_lcg = total_tank_lcg_moment / total_tank_mass
        tanks_tcg = total_tank_tcg_moment / total_tank_mass if total_tank_tcg_moment else 0.0
        tanks_vcg = total_tank_vcg_moment / total_tank_mass
    else:
        tanks_lcg = tanks_tcg = tanks_vcg = 0.0

    # Approximate livestock totals from the table rows (all non-tank, non-header rows).
    livestock_mass = 0.0
    livestock_lcg_moment = 0.0
    livestock_tcg_moment = 0.0
    livestock_vcg_moment = 0.0
    for row in rows[1:]:
        label = str(row[0])
        if "Tank" in label or label in ("FSM total (all tanks)",):
            continue
        try:
            mass_val = float(row[3]) if row[3] not in ("", None) else 0.0
            lcg_val = float(row[4]) if row[4] not in ("", None) else 0.0
            tcg_val = float(row[5]) if row[5] not in ("", None) else 0.0
            vcg_val = float(row[6]) if row[6] not in ("", None) else 0.0
        except (TypeError, ValueError):
            continue
        livestock_mass += mass_val
        livestock_lcg_moment += mass_val * lcg_val
        livestock_tcg_moment += mass_val * tcg_val
        livestock_vcg_moment += mass_val * vcg_val

    if livestock_mass > 0.0:
        livestock_lcg = livestock_lcg_moment / livestock_mass
        livestock_tcg = livestock_tcg_moment / livestock_mass if livestock_tcg_moment else 0.0
        livestock_vcg = livestock_vcg_moment / livestock_mass
    else:
        livestock_lcg = livestock_tcg = livestock_vcg = 0.0

    # Total loadcase: use displacement so Total Mass equals reported displacement.
    table_mass = livestock_mass + total_tank_mass
    displacement_t = float(getattr(results, "displacement_t", 0.0) or 0.0)
    total_mass = displacement_t if displacement_t > 0.0 else table_mass
    if total_mass > 0.0:
        total_lcg = (livestock_lcg_moment + total_tank_lcg_moment) / table_mass if table_mass > 0.0 else 0.0
        total_tcg = (livestock_tcg_moment + total_tank_tcg_moment) / table_mass if table_mass > 0.0 and (livestock_tcg_moment + total_tank_tcg_moment) else 0.0
        total_vcg = (livestock_vcg_moment + total_tank_vcg_moment) / table_mass if table_mass > 0.0 else 0.0
    else:
        total_lcg = total_tcg = total_vcg = 0.0
    total_fsm_loadcase = total_fsm_tanks

    # Append summary row at the end (overall loadcase totals).
    rows.append(
        [
            "Total Loadcase",
            "",
            "",
            _fmt(total_mass, ".2f"),
            _fmt(total_lcg, ".2f") if total_mass > 0.0 else "",
            _fmt(total_tcg, ".3f") if total_mass > 0.0 else "0.000",
            _fmt(total_vcg, ".2f") if total_mass > 0.0 else "",
            _fmt(total_fsm_loadcase, ".3f"),
            "",
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
    displacement_t = float(getattr(results, "displacement_t", 0.0) or 0.0)
    draft_m = float(getattr(results, "draft_m", 0.0) or 0.0)
    trim_m = float(getattr(results, "trim_m", 0.0) or 0.0)

    if displacement_t <= 0.0:
        return [], [], 0.0, 0.0, 0.0, 0.0

    kg_m = float(getattr(results, "kg_m", 0.0) or 0.0)
    if kg_m <= 0.0:
        return [], [], 0.0, 0.0, 0.0, 0.0

    kn_table = get_kn_table_dict(displacement_t, draft_m, trim_m)
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

    # GM for plotting: prefer the GM from the condition (same value shown in
    # the Results view) so the graphical construction lines up with the GMt
    # reported elsewhere. Only fall back to the graphical GM estimated from
    # the GZ curve when the condition has no positive GM.
    gm_raw = float(getattr(results, "gm_m", 0.0) or 0.0)
    gm_graph = estimate_gm_from_gz_curve(angles_deg, gz_values)
    if gm_raw > 0.0:
        gm_plot = gm_raw
    else:
        gm_plot = gm_graph if gm_graph is not None and gm_graph > 0.0 else 0.0

    # Match Curves view display: use the same smoothing and zero-cross handling
    # as the on-screen Matplotlib plot so the PDF curve has the same shape.
    plot_angles, plot_gz = prepare_gz_curve_display_points(angles_deg, gz_values)
    if not plot_angles or not plot_gz:
        # Fallback to raw data if smoothing could not be applied.
        plot_angles = [float(a) for a in angles_deg]
        plot_gz = [float(g) for g in gz_values]

    x_max = max(plot_angles) if plot_angles else (max(angles_deg) if angles_deg else 90.0)

    # Match Curves view Y‑scaling: base it on the plotted GZ values, then
    # ensure the GM level is comfortably inside the range.
    if plot_gz:
        y_max_val = max(plot_gz)
    else:
        y_max_val = max(gz_values) if gz_values else 1.0
    value_max = max(0.5, y_max_val * 1.20)
    if gm_plot > 0.0:
        value_max = max(value_max, gm_plot * 1.25)

    def map_point(angle_deg: float, gz: float) -> tuple[float, float]:
        x = left + (angle_deg / x_max) * plot_width
        y = bottom + (gz / value_max) * plot_height
        return x, y

    # Axes
    axis_color = colors.HexColor("#333333")
    d.add(Line(left, bottom, right, bottom, strokeColor=axis_color, strokeWidth=1))
    d.add(Line(left, bottom, left, top, strokeColor=axis_color, strokeWidth=1))

    # X-axis ticks and labels (angle of heel) – cover the full range of the curve,
    # aligned with the KN table angles (10° spacing, capped at 180°).
    max_tick_angle = min(180, int(math.ceil(x_max / 10.0)) * 10)
    for angle in range(0, max_tick_angle + 1, 10):
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

    # Additional geometric guides (GM and φ = 1 radian) to mirror the Curves view,
    # using the GM derived from the GZ curve where possible.
    # Use the plot rectangle so these guides align with the displayed GZ curve.
    if x_max > 0:
        # Vertical guide at φ = 1 radian (≈57.3°), clamped into the plot area.
        angle_guide = min(math.degrees(1.0), x_max)
        x_guide = left + (angle_guide / x_max) * plot_width

        # GM level, clamped into the visible Y‑range
        gm_clamped = max(0.0, min(gm_plot, value_max))
        if gm_clamped > 0.0:
            gm_y = bottom + (gm_clamped / value_max) * plot_height
            guide_color2 = colors.HexColor("#AAAAAA")

            # Vertical dotted line from GZ = 0 up to GM at φ = 1 radian (or to the right edge).
            d.add(
                Line(
                    x_guide,
                    bottom,
                    x_guide,
                    gm_y,
                    strokeColor=guide_color2,
                    strokeWidth=0.7,
                    strokeDashArray=[2, 2],
                )
            )

            # Horizontal GM line from heel = 0 to the 1‑radian guide.
            d.add(
                Line(
                    left,
                    gm_y,
                    x_guide,
                    gm_y,
                    strokeColor=guide_color2,
                    strokeWidth=0.7,
                    strokeDashArray=[2, 2],
                )
            )

            # Diagonal from origin (0, 0) to the intersection of the vertical and GM lines.
            d.add(
                Line(
                    left,
                    bottom,
                    x_guide,
                    gm_y,
                    strokeColor=guide_color2,
                    strokeWidth=0.7,
                    strokeDashArray=[2, 2],
                )
            )

            # Label GM just above the horizontal GM line near the guide, including its value.
            d.add(
                String(
                    x_guide - 2,
                    gm_y + 4,
                    f"GM = {gm_plot:.3f} m",
                    textAnchor="end",
                    fontSize=8,
                    fillColor=guide_color2,
                )
            )

            # Label φ = 1 radian on the X‑axis directly under the guide.
            d.add(
                String(
                    x_guide,
                    bottom - 14,
                    "φ = 1 radian",
                    textAnchor="middle",
                    fontSize=8,
                    fillColor=guide_color2,
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
    # Set document-level title metadata from filename (e.g. "Load Case NO.01")
    doc_title = filepath.stem or "Loading Condition Report"
    doc.title = doc_title
    cell_pad = 10  # Padding for report tables (except equilibrium)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceAfter=8,
    )
    # Make section headers larger, centered, and with a bit more spacing
    styles["Heading3"].fontSize = 13
    styles["Heading3"].leading = 16
    styles["Heading3"].spaceBefore = 8
    styles["Heading3"].spaceAfter = 4
    styles["Heading3"].alignment = 1  # center
    styles["Normal"].spaceAfter = 2

    def _draw_page_frame(canvas, _doc) -> None:
        # Apply document title metadata and draw a border frame on every page.
        canvas.setTitle(doc_title)
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
    story.append(Paragraph("SenaShipping - Loading Condition Report", title_style))
    story.append(Spacer(1, 0.3 * cm))

    # Header info (ship / condition)
    story.append(
        Paragraph(
            f"Ship: {ship.name} (IMO: {getattr(ship, 'imo_number', '') or ''})",
            styles["Normal"],
        )
    )
    story.append(Paragraph(f"Voyage: {voyage.name} ({voyage.departure_port} -> {voyage.arrival_port})", styles["Normal"]))
    story.append(Paragraph(f"Date: {condition.created_at.strftime('%Y-%m-%d')}", styles["Normal"]))
    # Use estimated voyage time from the loading condition instead of a Voyage.eta field.
    est_days = getattr(condition, "estimated_time_days", 0.0) or 0.0
    if est_days > 0:
        story.append(Paragraph(f"Est. time: {est_days:.2f} days", styles["Normal"]))
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
                ("TEXTCOLOR", (0, 0), (-1, 0), "black"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 13),
                ("FONTSIZE", (0, 1), (-1, -1), 11),
                ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
                ("GRID", (0, 0), (-1, -1), 0.5, "#333333"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), cell_pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), cell_pad),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.5 * cm))

    # Force the Weight Items and Free Surface Summary onto a fresh page
    # so it is visually separated from the condition summary.
    story.append(PageBreak())

    # --- Section 2: Items / FSM-style summary ---
    items_rows = _build_items_table(ship, condition, results)
    if items_rows:
        story.append(_section_title("Weight Items and Free Surface Summary", styles))
        story.append(Spacer(1, 0.2 * cm))

        # Wrap cell contents so long text stays within column width.
        items_header_style = ParagraphStyle(
            "ItemsHeader",
            parent=styles["Heading4"],
            fontSize=10,
            leading=11,
            alignment=1,  # center
            spaceBefore=0,
            spaceAfter=0,
        )
        items_cell_style = ParagraphStyle(
            "ItemsCell",
            parent=styles["Normal"],
            fontSize=9,
            leading=10,
            alignment=1,  # center
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
        items_page_width = A4[0] - doc.leftMargin - doc.rightMargin
        items_col_widths = [
            items_page_width * 0.15,  # Item (slightly narrower)
            items_page_width * 0.10,  # Quantity
            items_page_width * 0.11,  # Unit mass
            items_page_width * 0.12,  # Total mass
            items_page_width * 0.11,  # Long. arm
            items_page_width * 0.11,  # Trans. arm
            items_page_width * 0.11,  # Vert. arm
            items_page_width * 0.07,  # Total FSM
            items_page_width * 0.12,  # FSM Type (wider)
        ]
        # Increase the row height specifically for tank rows in the
        # "Weight Items and Free Surface Summary" table so they stand
        # out more and occupy more vertical space. We treat any row
        # whose first cell label contains "Tank" as a tank row and
        # give it 25% extra height compared to the base height. Also
        # make the header row a little taller for readability.
        base_row_height = 0.7 * cm
        row_heights: list[float] = []
        for idx in range(len(wrapped_items_rows)):
            if idx == 0:
                # Header row slightly taller than body rows.
                row_heights.append(base_row_height * 1.35)
                continue
            label = ""
            if idx < len(items_rows) and items_rows[idx]:
                label = str(items_rows[idx][0])
            if "Tank" in label:
                row_heights.append(base_row_height * 1.25)
            else:
                row_heights.append(base_row_height)

        items_table = Table(
            wrapped_items_rows,
            colWidths=items_col_widths,
            rowHeights=row_heights,
            repeatRows=1,
            hAlign="LEFT",
        )
        items_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), "black"),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
                    ("GRID", (0, 0), (-1, -1), 0.5, "#333333"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    # Make the final summary row taller for emphasis.
                    ("TOPPADDING", (0, -1), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 3),
                    ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
                ]
            )
        )
        story.append(items_table)
        story.append(Spacer(1, 0.6 * cm))

    # --- Section 3: EQUILIBRIUM DATA on separate page (Loading Manual style) ---
    story.append(NextPageTemplate("Portrait"))
    story.append(PageBreak())
    story.append(Paragraph("<b>EQUILIBRIUM DATA</b>", ParagraphStyle(
        "EquilibriumTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceAfter=8,
        alignment=1,  # center
    )))
    story.append(Spacer(1, 0.2 * cm))

    eq_data = build_equilibrium_data(ship, results, gm_eff)
    eq_rows_flat: list[list[str]] = []
    for label1, val1, label2, val2 in eq_data:
        eq_rows_flat.append([label1, val1, label2, val2])

    # Column widths: full page width, two pairs of (label, value)
    page_width = A4[0] - doc.leftMargin - doc.rightMargin
    col_w = page_width / 4
    eq_table = Table(eq_rows_flat, colWidths=[col_w * 1.4, col_w * 0.6, col_w * 1.4, col_w * 0.6])
    eq_cell_pad = 12  # Equilibrium table: generous padding to fill page
    eq_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
                ("TEXTCOLOR", (0, 0), (-1, 0), "black"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 13),
                ("BOTTOMPADDING", (0, 0), (-1, 0), eq_cell_pad),
                ("TOPPADDING", (0, 0), (-1, 0), eq_cell_pad),
                ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
                ("GRID", (0, 0), (-1, -1), 0.5, "#333333"),
                ("FONTSIZE", (0, 1), (-1, -1), 11),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (2, 0), (2, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 1), (-1, -1), eq_cell_pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), eq_cell_pad),
            ]
        )
    )
    story.append(eq_table)
    story.append(Spacer(1, 0.5 * cm))

    # --- Section 4: IMO / ancillary criteria table (if available) ---
    criteria = getattr(results, "criteria", None)
    has_criteria = bool(criteria is not None and getattr(criteria, "lines", None))

    if has_criteria:
        # Move to a dedicated landscape page for the criteria table.
        story.append(NextPageTemplate("Landscape"))
        story.append(PageBreak())
        # Add extra top spacing so the criteria block sits closer to
        # the vertical middle of the landscape page.
        story.append(Spacer(1, 0.3 * cm))
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
            fontSize=10,
            leading=11,
            alignment=1,  # center
            spaceBefore=0,
            spaceAfter=0,
        )
        crit_cell_style = ParagraphStyle(
            "CriteriaCell",
            parent=styles["Normal"],
            fontSize=9,
            leading=10,
            alignment=1,  # 
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
        # Group, Code, Name, Reference, Result, Value, Limit, Margin
        width_fractions = [0.09, 0.13, 0.28, 0.15, 0.07, 0.09, 0.09, 0.10]
        col_widths = [f * available_width for f in width_fractions]

        # Make the IMO / Livestock / Ancillary Criteria rows tall enough to
        # visually occupy (almost) the full landscape page height.
        #
        # We approximate the vertical space already used on this page
        # (section title + spacers) and distribute the remaining height
        # evenly across all table rows.
        criteria_frame_height = landscape_size[1] - doc.topMargin - doc.bottomMargin
        # Spacers on the page: 0.3 cm (before title) + 0.2 cm (after title),
        # plus an extra ~0.7 cm to account for the title line itself.
        approx_used_height = (0.3 + 0.2 + 0.7) * cm
        available_height_for_table = max(
            4 * cm,  # sensible minimum so rows never collapse
            criteria_frame_height - approx_used_height,
        )
        row_count = max(1, len(crit_rows_wrapped))
        # Slightly reduce the theoretical height so that, once padding and
        # grid lines are taken into account, the full table is more likely
        # to fit on a single page.
        base_row_height = (available_height_for_table / row_count) * 0.95
        # Do not let excessively small row heights slip through.
        base_row_height = max(0.65 * cm, base_row_height)
        row_heights = [base_row_height for _ in range(row_count)]

        crit_table = Table(
            crit_rows_wrapped,
            colWidths=col_widths,
            rowHeights=row_heights,
            repeatRows=1,
            hAlign="CENTER",
        )
        # Header and grid (same style as equilibrium table)
        base_style = [
            ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
            ("TEXTCOLOR", (0, 0), (-1, 0), "black"),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, 0), 11),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ALIGN", (0, 1), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
            ("GRID", (0, 0), (-1, -1), 0.5, "#333333"),
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
