"""
URL5-style life-weight / condition report PDF.

Builds a multi-page PDF for a loading condition with:
- Condition / equilibrium-style text sections (using existing stability data)
- IMO / livestock criteria summary
- GZ curve page (reusing the Curves view implementation)
- Profile and deck plan pages based on DXF files (profile.dxf, deck_A..deck_H.dxf)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, Polygon, PolyLine, String

from senashipping_app.config.limits import MASS_PER_HEAD_T
from senashipping_app.config.stability_manual_ref import (
    REF_LIGHTSHIP_DISPLACEMENT_T,
)
from senashipping_app.reports.equilibrium_data import build_equilibrium_data
from senashipping_app.reports.pdf_report import _build_gz_curve_drawing
from senashipping_app.repositories import database
from senashipping_app.repositories.livestock_pen_repository import LivestockPenRepository
from senashipping_app.services.alarms import build_alarm_rows
from senashipping_app.services.dxf_tank_parser import parse_dxf_polygons

if TYPE_CHECKING:
    from senashipping_app.models import Ship, Voyage, LoadingCondition, LivestockPen
    from senashipping_app.services.stability_service import ConditionResults


# ---------------------------------------------------------------------------
# Helpers and small data structures
# ---------------------------------------------------------------------------


def _fmt(value: object, fmt: str) -> str:
    """Safely format numeric values for PDF tables."""
    if value is None:
        return ""
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return str(value)


def _get_cad_dir() -> Path:
    """Return CAD folder path (same convention as deck/profile widgets)."""
    from senashipping_app.config.settings import Settings

    return Settings.default().project_root / "cads"


def _deck_letter_from_pen(pen: "LivestockPen") -> Optional[str]:
    """Normalize pen.deck to deck letter A–H."""
    s = (getattr(pen, "deck", "") or "").strip().upper()
    if not s:
        return None
    deck_letters = ("A", "B", "C", "D", "E", "F", "G", "H")
    if s in deck_letters:
        return s
    if s.isdigit():
        n = int(s)
        if 1 <= n <= 8:
            return chr(ord("A") + n - 1)
    if s.startswith("DK") and s[2:].strip().isdigit():
        n = int(s[2:].strip())
        if 1 <= n <= 8:
            return chr(ord("A") + n - 1)
    return s if s in deck_letters else None


def _load_pens_for_ship(ship: "Ship") -> list["LivestockPen"]:
    """Load all pens for a ship using the repository (same as Results/DeckProfile)."""
    pens: list["LivestockPen"] = []
    ship_id = getattr(ship, "id", None)
    if ship_id is not None and database.SessionLocal is not None:
        with database.SessionLocal() as db:
            pens = LivestockPenRepository(db).list_for_ship(ship_id)
    return pens


# ---------------------------------------------------------------------------
# Text sections
# ---------------------------------------------------------------------------


def _build_weight_summary_rows(
    ship: "Ship",
    condition: "LoadingCondition",
    results: "ConditionResults",
) -> list[list[str]]:
    """
    Compact weight summary matching the UI Weights tab:
    Lightship, livestock, tanks, total displacement.
    """
    rows: list[list[str]] = [["Group", "Weight (t)"]]

    disp = max(0.0, float(getattr(results, "displacement_t", 0.0) or 0.0))

    lightship_mass_t = (
        max(0.0, float(getattr(ship, "lightship_displacement_t", 0.0) or 0.0))
        or REF_LIGHTSHIP_DISPLACEMENT_T
    )
    rows.append(["Lightship", _fmt(lightship_mass_t, ".1f")])

    # Livestock by deck (Livestock-DK1..DK8) using pens + pen_loadings
    pen_loadings = getattr(condition, "pen_loadings", None) or {}
    pens = _load_pens_for_ship(ship)
    pen_by_id = {p.id: p for p in pens if getattr(p, "id", None) is not None}

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
        deck_letter = _deck_letter_from_pen(pen)
        if not deck_letter:
            continue
        grp = deck_groups.setdefault(
            deck_letter,
            {"heads": 0.0, "mass": 0.0},
        )
        mass = heads_int * MASS_PER_HEAD_T
        grp["heads"] += heads_int
        grp["mass"] += mass

    total_livestock_mass = 0.0
    for deck_letter in sorted(deck_groups.keys()):
        grp = deck_groups[deck_letter]
        mass = grp["mass"]
        total_livestock_mass += mass
        # Map A..H to DK1..DK8
        dk_index = ord(deck_letter) - ord("A") + 1
        rows.append([f"Livestock-DK{dk_index}", _fmt(mass, ".2f")])

    if not deck_groups and pen_loadings:
        # Fallback single livestock total when decks cannot be resolved
        total_livestock_mass = sum(
            max(0, int(h)) * MASS_PER_HEAD_T for h in pen_loadings.values()
        )
        rows.append(["Total Livestock", _fmt(total_livestock_mass, ".2f")])
    elif deck_groups:
        rows.append(["Total Livestock", _fmt(total_livestock_mass, ".2f")])

    tank_weights = getattr(condition, "tank_weights_mt", None) or {}
    if tank_weights:
        tanks_t = sum(max(0.0, float(w)) for w in tank_weights.values())
    else:
        tanks_t = max(0.0, disp - lightship_mass_t - total_livestock_mass)
    rows.append(["Tanks (all)", _fmt(tanks_t, ".1f") if disp > 0.0 else "—"])

    rows.append(["Displacement", _fmt(disp, ".1f")])
    deadweight = max(0.0, disp - lightship_mass_t)
    rows.append(["Deadweight", _fmt(deadweight, ".1f")])
    # Available deadweight could use a limit reference; for now show same as existing alarm
    rows.append(["Avail Deadweight", _fmt(deadweight, ".1f")])

    return rows


def _build_trim_stability_rows(results: "ConditionResults") -> list[list[str]]:
    """Trim & stability summary similar to Results view."""
    draft_mid = float(getattr(results, "draft_m", 0.0) or 0.0)
    draft_aft = float(
        getattr(results, "draft_aft_m", draft_mid + getattr(results, "trim_m", 0.0) / 2.0)
        or 0.0
    )
    draft_fwd = float(
        getattr(results, "draft_fwd_m", draft_mid - getattr(results, "trim_m", 0.0) / 2.0)
        or 0.0
    )
    trim_m = float(getattr(results, "trim_m", 0.0) or 0.0)
    heel = float(getattr(results, "heel_deg", 0.0) or 0.0)

    rows: list[list[str]] = [["Parameter", "Value"]]
    rows.extend(
        [
            ["Draft mid (m)", _fmt(draft_mid, ".3f")],
            ["Draft aft (m)", _fmt(draft_aft, ".3f")],
            ["Draft fwd (m)", _fmt(draft_fwd, ".3f")],
            ["Trim (m, + stern)", _fmt(trim_m, ".3f")],
            ["Heel (deg)", _fmt(heel, ".2f")],
            ["GM (m)", _fmt(getattr(results, "gm_m", None), ".3f")],
            ["KG (m)", _fmt(getattr(results, "kg_m", None), ".3f")],
            ["KM (m)", _fmt(getattr(results, "km_m", None), ".3f")],
        ]
    )
    return rows


def _build_alarms_rows(
    results: "ConditionResults",
) -> Optional[list[list[str]]]:
    """Alarms summary table similar to the Results view."""
    validation = getattr(results, "validation", None)
    criteria = getattr(results, "criteria", None)
    alarm_rows = build_alarm_rows(results, validation, criteria)
    if not alarm_rows:
        return None
    rows: list[list[str]] = [
        ["No.", "Status", "Description", "Attained", "Pass If", "Type"]
    ]
    for ar in alarm_rows:
        rows.append(
            [
                str(getattr(ar, "no", "")),
                getattr(ar, "status", ""),
                getattr(ar, "description", ""),
                getattr(ar, "attained", ""),
                getattr(ar, "pass_if", ""),
                getattr(getattr(ar, "type", None), "value", ""),
            ]
        )
    return rows


def _build_strength_rows(results: "ConditionResults") -> Optional[list[list[str]]]:
    """Simple longitudinal strength summary (SWBM, shear, % allow)."""
    strength = getattr(results, "strength", None)
    if not strength:
        return None
    rows: list[list[str]] = [["Parameter", "Value"]]
    rows.append(
        [
            "Still water BM approx. (tm)",
            _fmt(getattr(strength, "still_water_bm_approx_tm", None), ".0f"),
        ]
    )
    rows.append(
        [
            "BM % Allow",
            _fmt(getattr(strength, "bm_pct_allow", None), ".1f") + " %",
        ]
    )
    rows.append(
        [
            "Max shear (t)",
            _fmt(getattr(strength, "shear_force_max_t", None), ".1f"),
        ]
    )
    rows.append(
        [
            "SF % Allow",
            _fmt(getattr(strength, "sf_pct_allow", None), ".1f") + " %",
        ]
    )
    return rows


def _build_criteria_rows(criteria: object | None) -> Optional[list[list[str]]]:
    """Flatten IMO / livestock / ancillary criteria into a table, if available."""
    if not criteria or not getattr(criteria, "lines", None):
        return None
    rows: list[list[str]] = [
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
        rows.append(
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
    return rows


def _style_simple_table(
    rows: list[list[str]],
    col_widths: Optional[list[float]] = None,
    header_bg: str = "#4472C4",
) -> Table:
    """Create a simple styled ReportLab table."""
    table = Table(rows, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), "black"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (-1, -1), "#F5F5F5"),
        ("GRID", (0, 0), (-1, -1), 0.5, "#333333"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


def _build_equilibrium_table(
    ship: "Ship",
    results: "ConditionResults",
) -> Table:
    """Use existing equilibrium_data builder to create a 4-column table."""
    validation = getattr(results, "validation", None)
    gm_eff = getattr(validation, "gm_effective", None) if validation else None
    eq_data = build_equilibrium_data(ship, results, gm_eff)
    rows = [["Parameter 1", "Value 1", "Parameter 2", "Value 2"]]
    for label1, val1, label2, val2 in eq_data:
        rows.append([label1, val1, label2, val2])

    page_width = A4[0] - 4.4 * cm  # match margins from doc template
    col_w = page_width / 4
    table = Table(
        rows,
        colWidths=[col_w * 1.4, col_w * 0.6, col_w * 1.4, col_w * 0.6],
    )
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
        ("TEXTCOLOR", (0, 0), (-1, 0), "black"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 13),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
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
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


# ---------------------------------------------------------------------------
# DXF-based plan drawings (profile + decks)
# ---------------------------------------------------------------------------


def _normalise_points_to_box(
    points: Iterable[Tuple[float, float]],
    width: float,
    height: float,
    padding: float = 0.05,
) -> list[Tuple[float, float]]:
    """Scale raw (x, y) points into a [0,width]x[0,height] box with padding."""
    pts = list(points)
    if not pts:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    pad_x = padding * width
    pad_y = padding * height
    usable_w = width - 2 * pad_x
    usable_h = height - 2 * pad_y
    out: list[Tuple[float, float]] = []
    for x, y in pts:
        nx = pad_x + (x - min_x) / span_x * usable_w
        ny = pad_y + (y - min_y) / span_y * usable_h
        out.append((nx, ny))
    return out


def _build_deck_plan_drawing(
    deck_letter: str,
    pens: list["LivestockPen"],
    pen_loadings: dict,
    width: float = 18 * cm,
    height: float = 10 * cm,
) -> Drawing:
    """
    Simple deck plan drawing:
    - Grey polygons from deck_{letter}.dxf (when available)
    - Coloured squares for pens on this deck, scaled by area and coloured when loaded.
    """
    d = Drawing(width, height)

    cad_dir = _get_cad_dir()
    dxf_path = cad_dir / f"deck_{deck_letter}.dxf"

    # Draw DXF geometry: first try polygons, else fall back to LINE/LWPOLYLINE/POLYLINE.
    polygons = parse_dxf_polygons(dxf_path) if dxf_path.exists() else []
    if polygons:
        for poly in polygons:
            pts = poly.get("outline_xy") or []
            if len(pts) < 3:
                continue
            norm_pts = _normalise_points_to_box(pts, width, height)
            if len(norm_pts) < 3:
                continue
            flat = [coord for xy in norm_pts for coord in xy]
            d.add(
                Polygon(
                    flat,
                    strokeColor=colors.HexColor("#999999"),
                    strokeWidth=0.5,
                    fillColor=colors.Color(0.92, 0.92, 0.92),
                )
            )
    elif dxf_path.exists():
        # Lightweight DXF reader for linework-only plans.
        try:
            import ezdxf  # type: ignore[import]
        except ImportError:
            ezdxf = None  # type: ignore[assignment]
        if ezdxf is not None:
            try:
                doc = ezdxf.readfile(str(dxf_path))
                msp = doc.modelspace()
                segments: list[tuple[Tuple[float, float], Tuple[float, float]]] = []
                for e in msp:
                    et = e.dxftype()
                    if et == "LINE":
                        x1, y1, _ = e.dxf.start
                        x2, y2, _ = e.dxf.end
                        segments.append(((float(x1), float(y1)), (float(x2), float(y2))))
                    elif et in ("LWPOLYLINE", "POLYLINE"):
                        try:
                            if et == "LWPOLYLINE":
                                with e.points("xy") as pts:
                                    pts_list = [(float(p[0]), float(p[1])) for p in pts]
                            else:
                                pts_list = [(float(p[0]), float(p[1])) for p in e.points()]
                        except Exception:
                            continue
                        for i in range(len(pts_list) - 1):
                            segments.append((pts_list[i], pts_list[i + 1]))
                if segments:
                    # Normalise all segment endpoints together to keep geometry in proportion.
                    all_pts = [p for seg in segments for p in seg]
                    norm_all = _normalise_points_to_box(all_pts, width, height)
                    # Map back to segment list
                    it = iter(norm_all)
                    norm_segments = list(zip(it, it))
                    for (x1, y1), (x2, y2) in norm_segments:
                        d.add(
                            PolyLine(
                                [x1, y1, x2, y2],
                                strokeColor=colors.HexColor("#999999"),
                                strokeWidth=0.5,
                            )
                        )
            except Exception:
                # On any DXF error, leave deck background empty.
                pass

    # Filter pens for this deck and prepare scaling for LCG/TCG layout
    deck_pens: list["LivestockPen"] = [
        p for p in pens if _deck_letter_from_pen(p) == deck_letter
    ]
    if deck_pens:
        lcg_vals = [float(getattr(p, "lcg_m", 0.0) or 0.0) for p in deck_pens]
        tcg_vals = [float(getattr(p, "tcg_m", 0.0) or 0.0) for p in deck_pens]
        l_min, l_max = min(lcg_vals), max(lcg_vals)
        t_span = max(max(abs(t) for t in tcg_vals), 1e-6)
        l_span = max(l_max - l_min, 1e-6)
        cx0 = 0.1 * width
        cx1 = 0.9 * width
        cy_mid = height / 2.0

        for p in deck_pens:
            if not getattr(p, "id", None):
                continue
            lcg = float(getattr(p, "lcg_m", 0.0) or 0.0)
            tcg = float(getattr(p, "tcg_m", 0.0) or 0.0)
            heads = int((pen_loadings or {}).get(p.id, 0) or 0)
            loaded = heads > 0

            x_center = cx0 + (lcg - l_min) / l_span * (cx1 - cx0)
            y_center = cy_mid - (tcg / t_span) * (height * 0.35)

            area_m2 = float(getattr(p, "area_m2", 10.0) or 10.0)
            size = max(area_m2 ** 0.5 * 1.0, 4.0)
            half = size / 2.0

            color = colors.Color(0.8, 0.9, 1.0) if loaded else colors.Color(0.9, 0.9, 0.9)
            border = colors.HexColor("#00507f") if loaded else colors.HexColor("#666666")
            d.add(
                Polygon(
                    [
                        x_center - half,
                        y_center - half,
                        x_center + half,
                        y_center - half,
                        x_center + half,
                        y_center + half,
                        x_center - half,
                        y_center + half,
                    ],
                    strokeColor=border,
                    strokeWidth=0.7,
                    fillColor=color,
                )
            )

    # Deck label
    d.add(
        String(
            width / 2.0,
            height - 0.6 * cm,
            f"Deck {deck_letter} plan",
            textAnchor="middle",
            fontSize=10,
            fillColor=colors.HexColor("#333333"),
        )
    )
    return d


def _build_profile_plan_drawing(
    width: float = 18 * cm,
    height: float = 6 * cm,
) -> Drawing:
    """Profile plan from profile.dxf (polygons only) as a light background shape."""
    d = Drawing(width, height)
    cad_dir = _get_cad_dir()
    dxf_path = cad_dir / "profile.dxf"
    polygons = parse_dxf_polygons(dxf_path) if dxf_path.exists() else []

    if polygons:
        for poly in polygons:
            pts = poly.get("outline_xy") or []
            if len(pts) < 3:
                continue
            norm_pts = _normalise_points_to_box(pts, width, height, padding=0.02)
            if len(norm_pts) < 3:
                continue
            flat = [coord for xy in norm_pts for coord in xy]
            d.add(
                Polygon(
                    flat,
                    strokeColor=colors.HexColor("#555555"),
                    strokeWidth=0.7,
                    fillColor=colors.Color(0.94, 0.94, 0.94),
                )
            )
    elif dxf_path.exists():
        # Fallback for line-only profile DXF: draw lines instead of filled polygons.
        try:
            import ezdxf  # type: ignore[import]
        except ImportError:
            ezdxf = None  # type: ignore[assignment]
        if ezdxf is not None:
            try:
                doc = ezdxf.readfile(str(dxf_path))
                msp = doc.modelspace()
                segments: list[tuple[Tuple[float, float], Tuple[float, float]]] = []
                for e in msp:
                    et = e.dxftype()
                    if et == "LINE":
                        x1, y1, _ = e.dxf.start
                        x2, y2, _ = e.dxf.end
                        segments.append(((float(x1), float(y1)), (float(x2), float(y2))))
                    elif et in ("LWPOLYLINE", "POLYLINE"):
                        try:
                            if et == "LWPOLYLINE":
                                with e.points("xy") as pts:
                                    pts_list = [(float(p[0]), float(p[1])) for p in pts]
                            else:
                                pts_list = [(float(p[0]), float(p[1])) for p in e.points()]
                        except Exception:
                            continue
                        for i in range(len(pts_list) - 1):
                            segments.append((pts_list[i], pts_list[i + 1]))
                if segments:
                    all_pts = [p for seg in segments for p in seg]
                    norm_all = _normalise_points_to_box(all_pts, width, height, padding=0.02)
                    it = iter(norm_all)
                    norm_segments = list(zip(it, it))
                    for (x1, y1), (x2, y2) in norm_segments:
                        d.add(
                            PolyLine(
                                [x1, y1, x2, y2],
                                strokeColor=colors.HexColor("#555555"),
                                strokeWidth=0.7,
                            )
                        )
            except Exception:
                pass
    else:
        d.add(
            String(
                width / 2.0,
                height / 2.0,
                "profile.dxf not available",
                textAnchor="middle",
                fontSize=9,
                fillColor=colors.HexColor("#777777"),
            )
        )

    d.add(
        String(
            width / 2.0,
            height - 0.5 * cm,
            "Ship profile (from profile.dxf)",
            textAnchor="middle",
            fontSize=10,
            fillColor=colors.HexColor("#333333"),
        )
    )
    return d


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def export_life_weight_report(
    filepath: Path,
    ship: "Ship",
    voyage: "Voyage",
    condition: "LoadingCondition",
    results: "ConditionResults",
) -> None:
    """
    Generate a URL5-style life-weight / condition PDF report.

    Structure:
      - Condition, weight, trim/stability, equilibrium data
      - Criteria summary (if available)
      - GZ curve page
      - Profile plan (profile.dxf)
      - Deck plans A–H (deck_A..deck_H.dxf) with coloured pens when loaded
    """
    doc = BaseDocTemplate(
        str(filepath),
        pagesize=A4,
        rightMargin=2.2 * cm,
        leftMargin=2.2 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
    )
    doc_title = f"Detailed Condition Summary - {condition.name or 'Condition'}"
    doc.title = doc_title

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LifeTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceAfter=8,
    )
    styles["Heading3"].fontSize = 13
    styles["Heading3"].leading = 16
    styles["Heading3"].spaceBefore = 8
    styles["Heading3"].spaceAfter = 4
    styles["Heading3"].alignment = 1  # center

    def _draw_page_frame(canvas, _doc) -> None:
        canvas.setTitle(doc_title)
        width, height = canvas._pagesize
        margin = 0.7 * cm
        canvas.saveState()
        canvas.setStrokeColor(colors.black)
        canvas.setLineWidth(0.7)
        canvas.rect(margin, margin, width - 2 * margin, height - 2 * margin, stroke=1, fill=0)
        canvas.restoreState()

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

    story: list = []

    # ------------------------------------------------------------------
    # Page 1: Condition summary + weight + trim & stability
    # ------------------------------------------------------------------
    story.append(Paragraph("Detailed Condition Summary (URL5-style Report)", title_style))
    story.append(Spacer(1, 0.2 * cm))
    # Show profile plan at top of first page, similar to reference report
    story.append(_build_profile_plan_drawing(width=16 * cm, height=5 * cm))
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        Paragraph(
            f"Ship: {ship.name} (IMO: {getattr(ship, 'imo_number', '') or ''})",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            f"Voyage: {voyage.name} ({voyage.departure_port} → {voyage.arrival_port})",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            f"Condition: {condition.name}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    # Weight summary table (URL5-style first section)
    w_rows = _build_weight_summary_rows(ship, condition, results)
    story.append(Paragraph("<b>Weight Summary</b>", styles["Heading3"]))
    story.append(Spacer(1, 0.15 * cm))
    story.append(_style_simple_table(w_rows, col_widths=[8 * cm, 6 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    # Trim & stability table
    ts_rows = _build_trim_stability_rows(results)
    story.append(Paragraph("<b>Trim and Stability Summary</b>", styles["Heading3"]))
    story.append(Spacer(1, 0.15 * cm))
    story.append(_style_simple_table(ts_rows, col_widths=[8 * cm, 6 * cm]))
    story.append(PageBreak())

    # ------------------------------------------------------------------
    # Page 2: Alarms summary (IACS URL5-style Alarms page)
    # ------------------------------------------------------------------
    alarms_rows = _build_alarms_rows(results)
    if alarms_rows:
        story.append(Paragraph("<b>Alarms Summary</b>", styles["Heading3"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            _style_simple_table(
                alarms_rows,
                col_widths=[1.5 * cm, 2.0 * cm, 7.0 * cm, 3.0 * cm, 3.0 * cm, 2.5 * cm],
            )
        )
        story.append(PageBreak())

    # ------------------------------------------------------------------
    # Page 3: Strength + Equilibrium data (Loading Manual style)
    # ------------------------------------------------------------------
    strength_rows = _build_strength_rows(results)
    if strength_rows:
        story.append(Paragraph("<b>Strength Summary</b>", styles["Heading3"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_style_simple_table(strength_rows, col_widths=[9 * cm, 5 * cm]))
        story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("<b>EQUILIBRIUM DATA</b>", ParagraphStyle(
        "EquilibriumTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceAfter=8,
        alignment=1,
    )))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_build_equilibrium_table(ship, results))
    story.append(PageBreak())

    # ------------------------------------------------------------------
    # Criteria summary (if any) – still follows equilibrium
    # ------------------------------------------------------------------
    criteria = getattr(results, "criteria", None)
    crit_rows = _build_criteria_rows(criteria)
    if crit_rows:
        story.append(Paragraph("<b>IMO / Livestock / Ancillary Criteria</b>", styles["Heading3"]))
        story.append(Spacer(1, 0.2 * cm))
        # Landscape page
        story.append(PageBreak())
        doc.addPageTemplates(landscape_template)
        story.append(Paragraph("<b>IMO / Livestock / Ancillary Criteria</b>", styles["Heading3"]))
        story.append(Spacer(1, 0.2 * cm))
        available_width = landscape_size[0] - doc.leftMargin - doc.rightMargin
        fracs = [0.09, 0.13, 0.28, 0.15, 0.07, 0.09, 0.09, 0.10]
        col_widths = [f * available_width for f in fracs]
        crit_table = _style_simple_table(crit_rows, col_widths=col_widths)
        # colour Result column cells by PASS/FAIL (overlay on top of base style)
        extra_cmds: list[tuple] = []
        result_col = 4
        for i in range(1, len(crit_rows)):
            text = str(crit_rows[i][result_col]).upper()
            if "PASS" in text:
                extra_cmds.append(("BACKGROUND", (result_col, i), (result_col, i), "#C6EFCE"))
            elif "FAIL" in text:
                extra_cmds.append(("BACKGROUND", (result_col, i), (result_col, i), "#FFC7CE"))
            elif "N_A" in text or "N/A" in text:
                extra_cmds.append(("BACKGROUND", (result_col, i), (result_col, i), "#E7E6E6"))
        if extra_cmds:
            crit_table.setStyle(TableStyle(extra_cmds))
        story.append(crit_table)
        story.append(PageBreak())
    else:
        # still ensure landscape template is available later
        doc.addPageTemplates(landscape_template)

    # ------------------------------------------------------------------
    # GZ curve page (landscape)
    # ------------------------------------------------------------------
    story.append(Paragraph("<b>Righting Lever (GZ) Curve</b>", styles["Heading3"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_build_gz_curve_drawing(results, width=24 * cm, height=13 * cm))
    story.append(PageBreak())

    # ------------------------------------------------------------------
    # Profile + deck plans (portrait)
    # ------------------------------------------------------------------
    # Reset to portrait for plan pages
    story.append(Paragraph("<b>Profile and Deck Plans</b>", styles["Heading3"]))
    story.append(Spacer(1, 0.3 * cm))

    # Profile
    story.append(_build_profile_plan_drawing(width=16 * cm, height=6 * cm))
    story.append(Spacer(1, 0.5 * cm))

    # Deck plans A–H
    pens = _load_pens_for_ship(ship)
    pen_loadings = getattr(condition, "pen_loadings", None) or {}
    for deck_letter in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        deck_has_pens = any(_deck_letter_from_pen(p) == deck_letter for p in pens)
        cad_path = _get_cad_dir() / f"deck_{deck_letter}.dxf"
        if not cad_path.exists() and not deck_has_pens:
            continue
        story.append(_build_deck_plan_drawing(deck_letter, pens, pen_loadings))
        story.append(Spacer(1, 0.4 * cm))

    doc.build(story)

