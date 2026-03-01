"""
GZ curve view: matplotlib canvas embedded in PyQt.
Uses KN table from Excel (gz_curve_plot), bilinear KN; smooth curve for display; stats, grid, shaded area.
Refreshes when loading condition updates (condition_computed).
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from senashipping_app.services.gz_curve_plot import (
    compute_gz_curve_stats,
    get_kn_table_dict,
    plot_gz_curve,
)

_LOG = logging.getLogger(__name__)


def _matplotlib_canvas():
    """Lazy import to avoid pulling matplotlib at import time."""
    import matplotlib
    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    return FigureCanvasQTAgg, Figure


class CurvesView(QWidget):
    """
    GZ curve view: matplotlib canvas embedded in PyQt.
    Uses KN tables from Excel (assets/KN tables.xlsx, or legacy KZ tables.xlsx); sheet = trim.
    Shows max GZ, angle at max GZ, area under curve, range of positive stability,
    max marker, shaded positive area. Refreshes when condition_computed.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        FigureCanvasQTAgg, Figure = _matplotlib_canvas()
        self._figure = Figure(figsize=(8, 5), dpi=120)
        self._ax = self._figure.add_subplot(111)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self._draw_placeholder()

    def _draw_placeholder(self) -> None:
        self._ax.clear()
        self._ax.set_xlabel("Heel Angle (deg)")
        self._ax.set_ylabel("GZ (m)")
        self._ax.set_title("GZ curve")
        self._ax.text(0.5, 0.5, "Compute a condition to see the GZ curve.",
                      transform=self._ax.transAxes, ha="center", va="center", fontsize=12)
        self._ax.set_xlim(0, 90)
        self._ax.set_ylim(0, 1)
        self._figure.tight_layout(pad=1.0)
        self._canvas.draw_idle()

    def clear_curve(self) -> None:
        self._draw_placeholder()

    def update_curve(
        self,
        results: Any,
        ship: Any | None = None,
        condition: Any | None = None,
        voyage: Any | None = None,
    ) -> None:
        """Refresh plot when loading condition updates (condition_computed)."""
        kg_m = getattr(results, "kg_m", 0.0)
        displacement_t = getattr(results, "displacement_t", 0.0)
        trim_m = getattr(results, "trim_m", 0.0)

        if kg_m <= 0 or displacement_t <= 0:
            self._draw_placeholder()
            return

        kn_table = get_kn_table_dict(displacement_t, trim_m)
        if not kn_table:
            self._ax.clear()
            self._ax.set_xlabel("Heel Angle (deg)")
            self._ax.set_ylabel("GZ (m)")
            self._ax.set_title("GZ curve")
            self._ax.text(0.5, 0.5,
                          "No KN table for this trim/displacement.\nPut KN tables.xlsx in assets.",
                          transform=self._ax.transAxes, ha="center", va="center", fontsize=10)
            self._figure.tight_layout(pad=1.0)
            self._canvas.draw_idle()
            return

        angles, gz_values, max_gz, angle_at_max, area_m_rad, range_positive = compute_gz_curve_stats(
            kg_m, kn_table
        )
        _LOG.info(
            "GZ curve: plotting %d points (kg=%.2f m, disp=%.1f t)",
            len(angles), kg_m, getattr(results, "displacement_t", 0),
        )
        self._ax.clear()
        plot_gz_curve(
            angles,
            gz_values,
            ax=self._ax,
            xlabel="Heel Angle (deg)",
            ylabel="GZ (m)",
            title="GZ curve",
            show_grid=True,
            show_zero_line=False,
            show_max_marker=True,
            show_area_shade=True,
            smooth_display=True,
            max_gz=max_gz,
            angle_at_max_gz=angle_at_max,
            range_positive_deg=range_positive,
            area_m_rad=area_m_rad,
            show_stats=True,
        )
        self._figure.tight_layout(pad=1.0)
        self._canvas.draw_idle()
