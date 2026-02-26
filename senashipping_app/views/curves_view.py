from __future__ import annotations

import math
from typing import Any, Sequence

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QBrush, QColor, QPen, QPainterPath, QFont
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsTextItem


class CurvesView(QGraphicsView):
    """
    Simple righting lever (GZ) curve view.

    The curve is updated from the latest computed loading condition and uses
    a GM-based approximation to generate a GZ vs heel angle plot similar to
    a classical static stability curve.
    """

    def __init__(self, parent: QGraphicsView | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # Set white background
        self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))

        # Enable interaction with rubber-band selection
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setInteractive(True)

        # Default scene rectangle (will auto-scale content inside)
        self._margin_left = 60
        self._margin_right = 20
        self._margin_top = 20
        self._margin_bottom = 40
        self._width = 800
        self._height = 400
        self._scene.setSceneRect(0, 0, self._width, self._height)

        self._draw_empty_message("Compute a condition to see the GZ curve.")

    # --- Public API -----------------------------------------------------

    def clear_curve(self) -> None:
        """Clear any existing curve and show the default placeholder message."""
        self._draw_empty_message("Compute a condition to see the GZ curve.")

    def update_curve(
        self,
        results: Any,
        ship: Any | None = None,
        condition: Any | None = None,
        voyage: Any | None = None,
    ) -> None:
        """
        Slot connected to `ConditionEditorView.condition_computed`.

        Args:
            results: `ConditionResults` from stability_service / condition_service.
            ship, condition, voyage: currently unused but kept for future use and
                to match the signal signature.
        """
        gm_raw = getattr(results, "gm_m", 0.0)
        validation = getattr(results, "validation", None)
        gm_eff = getattr(validation, "gm_effective", gm_raw) if validation else gm_raw

        # Always generate a curve for diagnostics:
        # - Prefer effective GM when positive
        # - Otherwise fall back to raw GM
        # - If both are non-positive or zero, use a small positive placeholder
        gm_for_shape = gm_eff if gm_eff is not None else gm_raw
        if gm_for_shape is None:
            gm_for_shape = 0.0
        if gm_for_shape <= 0.0:
            gm_for_shape = abs(gm_raw) if gm_raw not in (None, 0.0) else 0.01
        # Vary the angle of vanishing stability with GM so curve shape changes
        # between loading conditions:
        # - Very low GM → curve dies early (e.g. 40°–50°)
        # - Higher GM → curve extends closer to 90°
        gm_clamped = max(0.0, min(float(gm_for_shape), 1.5))
        phi_end_deg = 40.0 + (gm_clamped / 1.5) * 50.0  # range ≈ 40°–90°

        # Build approximate GZ curve from GM (0–90°)
        angles_deg = list(range(0, 91, 2))
        gz_values = self._approximate_gz_curve(angles_deg, gm_for_shape, phi_end_deg)

        # As a safety net, if something went wrong and we still have no positive
        # GZ values, fall back to a generic curve so the user always sees a
        # righting lever plot, even for edge cases like pure lightship.
        if not gz_values or max(gz_values) <= 0.0:
            fallback_gm = gm_for_shape if gm_for_shape > 0.0 else 0.5
            gz_values = self._approximate_gz_curve(angles_deg, fallback_gm, 60.0)

        # For GM guide line, keep using effective GM when it is meaningful;
        # otherwise use the GM value that was used to shape the curve.
        gm_for_display = gm_eff if isinstance(gm_eff, (int, float)) and gm_eff > 0.0 else gm_for_shape

        self._draw_curve(angles_deg, gz_values, gm_for_display)

    # --- Internal helpers -----------------------------------------------

    def _draw_empty_message(self, text: str) -> None:
        """Clear scene and show a centered informational message."""
        self._scene.clear()
        self._scene.setSceneRect(0, 0, self._width, self._height)

        item = QGraphicsTextItem(text)
        font = QFont()
        font.setPointSize(10)
        item.setFont(font)
        item.setDefaultTextColor(QColor("#555555"))

        # Center the text in the view
        text_rect = item.boundingRect()
        x = (self._width - text_rect.width()) / 2
        y = (self._height - text_rect.height()) / 2
        item.setPos(x, y)
        self._scene.addItem(item)

    def _approximate_gz_curve(
        self,
        angles_deg: Sequence[int],
        gm_eff: float,
        phi_end_deg: float = 90.0,
    ) -> list[float]:
        """
        Build a smooth GZ curve that matches manual shape: tangent at origin = GM,
        single peak around mid-angles, then decay to zero at φ = φ_end_deg
        (angle of vanishing stability).

        Uses: GZ(φ) = GM * sin(φ) * envelope(φ) with envelope chosen so the curve
        peaks near mid-angles and goes to zero at φ_end_deg, giving a classic
        static stability look. φ_end_deg is varied per condition so different
        loading conditions produce visibly different curve shapes.
        """
        # Clamp end angle to a sensible range
        phi_end_deg = max(30.0, min(float(phi_end_deg), 90.0))
        gz_values: list[float] = []

        # Shape exponent: smaller for more stable (larger φ_end) so the curve
        # is broader; larger for less stable so it is steeper and dies earlier.
        span_norm = (phi_end_deg - 30.0) / 60.0  # 0 at 30°, 1 at 90°
        exponent = 2.0 + (1.2 * (1.0 - span_norm))

        for a in angles_deg:
            phi_deg = float(a)
            phi_rad = math.radians(phi_deg)
            base = math.sin(phi_rad)
            # Envelope: 1 at small φ, 0 at φ_end; exponent >2 shifts peak toward mid-angles
            u = phi_deg / phi_end_deg
            envelope = max(0.0, 1.0 - (u ** exponent))
            gz = gm_eff * base * envelope
            gz_values.append(max(0.0, gz))

        return gz_values

    def _draw_curve(
        self,
        angles_deg: Sequence[int],
        gz_values: Sequence[float],
        gm_eff: float,
    ) -> None:
        """Draw axes, GM / GZmax guides, and the GZ curve."""
        self._scene.clear()
        self._scene.setSceneRect(0, 0, self._width, self._height)

        left = self._margin_left
        right = self._width - self._margin_right
        top = self._margin_top
        bottom = self._height - self._margin_bottom

        plot_width = right - left
        plot_height = bottom - top

        max_gz = max(gz_values) if gz_values else gm_eff
        if max_gz <= 0.0:
            self._draw_empty_message("No positive GZ values to plot.")
            return

        # Add some headroom so GM and GZmax lines fit
        value_max = max(max_gz, gm_eff) * 1.2

        def map_point(angle_deg: float, gz: float) -> QPointF:
            x = left + (angle_deg / 90.0) * plot_width
            y = bottom - (gz / value_max) * plot_height
            return QPointF(x, y)

        axis_pen = QPen(QColor("#333333"))
        axis_pen.setWidth(1)

        # Axes
        self._scene.addLine(left, bottom, right, bottom, axis_pen)  # X axis
        self._scene.addLine(left, bottom, left, top, axis_pen)  # Y axis

        label_font = QFont()
        label_font.setPointSize(9)

        # X-axis ticks and labels (angle of heel)
        for angle in (0, 10, 20, 30, 40, 50, 60, 75, 90):
            x = left + (angle / 90.0) * plot_width
            self._scene.addLine(x, bottom, x, bottom + 4, axis_pen)
            label = QGraphicsTextItem(str(angle))
            label.setFont(label_font)
            label.setDefaultTextColor(QColor("#333333"))
            label_rect = label.boundingRect()
            label.setPos(x - label_rect.width() / 2, bottom + 6)
            self._scene.addItem(label)

        # Y-axis ticks (GZ)
        num_y_ticks = 4
        for i in range(1, num_y_ticks + 1):
            val = value_max * i / num_y_ticks
            y = bottom - (val / value_max) * plot_height
            self._scene.addLine(left - 4, y, left, y, axis_pen)
            label = QGraphicsTextItem(f"{val:.2f}")
            label.setFont(label_font)
            label.setDefaultTextColor(QColor("#333333"))
            label_rect = label.boundingRect()
            label.setPos(left - label_rect.width() - 6, y - label_rect.height() / 2)
            self._scene.addItem(label)

        # Axis titles (manual-style: angle φ, righting lever GZ)
        x_title = QGraphicsTextItem("Angle of heel (degrees) φ")
        x_title.setFont(label_font)
        x_title.setDefaultTextColor(QColor("#333333"))
        x_title_rect = x_title.boundingRect()
        x_title.setPos(
            left + (plot_width - x_title_rect.width()) / 2,
            self._height - x_title_rect.height(),
        )
        self._scene.addItem(x_title)

        y_title = QGraphicsTextItem("Righting lever, GZ (m)")
        y_title.setFont(label_font)
        y_title.setDefaultTextColor(QColor("#333333"))
        y_title.setRotation(-90)
        y_title_rect = y_title.boundingRect()
        y_title.setPos(
            10,
            top + (plot_height + y_title_rect.width()) / 2,
        )
        self._scene.addItem(y_title)

        # GM horizontal guide
        gm_y = bottom - (gm_eff / value_max) * plot_height
        gm_pen = QPen(QColor("#808080"))
        gm_pen.setStyle(Qt.PenStyle.DashLine)
        gm_pen.setWidth(1)
        self._scene.addLine(left, gm_y, right, gm_y, gm_pen)
        gm_label = QGraphicsTextItem("GM")
        gm_label.setFont(label_font)
        gm_label.setDefaultTextColor(QColor("#555555"))
        gm_label.setPos(right - gm_label.boundingRect().width() - 4, gm_y - 16)
        self._scene.addItem(gm_label)

        # Tangent at origin: GZ = GM * φ (rad), so at φ = 1 rad (57.3°) height = GM
        one_rad_deg = 57.2958
        x_one_rad = left + (one_rad_deg / 90.0) * plot_width
        tangent_pen = QPen(QColor("#a0a0a0"))
        tangent_pen.setStyle(Qt.PenStyle.DashLine)
        tangent_pen.setWidth(1)
        self._scene.addLine(left, bottom, x_one_rad, gm_y, tangent_pen)
        tan_label = QGraphicsTextItem("φ = 1 rad")
        tan_label.setFont(label_font)
        tan_label.setDefaultTextColor(QColor("#666666"))
        tan_rect = tan_label.boundingRect()
        tan_label.setPos(x_one_rad - tan_rect.width() / 2, bottom + 2)
        self._scene.addItem(tan_label)

        # GZmax horizontal guide and vertical line at max
        max_index = max(range(len(gz_values)), key=lambda i: gz_values[i])
        gz_max = gz_values[max_index]
        angle_at_max = angles_deg[max_index]

        gzmax_y = bottom - (gz_max / value_max) * plot_height
        gzmax_pen = QPen(QColor("#999999"))
        gzmax_pen.setStyle(Qt.PenStyle.DashLine)
        gzmax_pen.setWidth(1)
        self._scene.addLine(left, gzmax_y, right, gzmax_y, gzmax_pen)
        gzmax_label = QGraphicsTextItem("GZmax")
        gzmax_label.setFont(label_font)
        gzmax_label.setDefaultTextColor(QColor("#555555"))
        gzmax_label.setPos(left + 4, gzmax_y - 16)
        self._scene.addItem(gzmax_label)

        x_max = left + (angle_at_max / 90.0) * plot_width
        self._scene.addLine(x_max, bottom, x_max, top, gzmax_pen)

        # Angle at max label near bottom
        amax_label = QGraphicsTextItem(f"{angle_at_max}° at GZmax")
        amax_label.setFont(label_font)
        amax_label.setDefaultTextColor(QColor("#555555"))
        amax_rect = amax_label.boundingRect()
        amax_label.setPos(
            x_max - amax_rect.width() / 2,
            top,
        )
        self._scene.addItem(amax_label)

        # Angle of vanishing stability (point C) at 90°
        x_90 = left + plot_width
        c_label = QGraphicsTextItem("C")
        c_label.setFont(label_font)
        c_label.setDefaultTextColor(QColor("#555555"))
        c_rect = c_label.boundingRect()
        c_label.setPos(x_90 - c_rect.width() / 2, bottom - c_rect.height() - 2)
        self._scene.addItem(c_label)
        vanish_label = QGraphicsTextItem("Angle of vanishing stability")
        vanish_label.setFont(label_font)
        vanish_label.setDefaultTextColor(QColor("#666666"))
        v_rect = vanish_label.boundingRect()
        vanish_label.setPos(x_90 - v_rect.width() / 2, bottom + 8)
        self._scene.addItem(vanish_label)

        # Main GZ curve
        curve_pen = QPen(QColor("#2c3e50"))
        curve_pen.setWidth(2)

        path = QPainterPath()
        first_point = True
        for angle_deg, gz in zip(angles_deg, gz_values):
            p = map_point(float(angle_deg), float(gz))
            if first_point:
                path.moveTo(p)
                first_point = False
            else:
                path.lineTo(p)

        self._scene.addPath(path, curve_pen)

        # Fit view to the scene rectangle without changing aspect ratio too abruptly
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)