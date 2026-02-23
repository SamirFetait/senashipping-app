"""
Hydrostatic Curves page: displays app-generated curves (displacement, KB, LCB, I_T, I_L).

Curves are built from the current ship dimensions using build_curves_from_formulas.
No import of external curve data; this page shows what the app uses for calculations.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
)
from PyQt6.QtCore import Qt

from ..services.hydrostatic_curves import (
    build_curves_from_formulas,
    HydrostaticCurves,
    RHO_SEA,
)
from ..services.hydrostatics import DEFAULT_CB

# Matplotlib: use QtAgg backend for embedding in PyQt6
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class HydrostaticCurvesView(QWidget):
    """Page after Results that shows generated hydrostatic curves."""

    def __init__(self, parent: Optional[QWidget] = None, get_current_ship: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._get_current_ship = get_current_ship  # callable() -> ship or None
        self._curves: Optional[HydrostaticCurves] = None
        self._canvas: Optional[FigureCanvasQTAgg] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._title = QLabel("Hydrostatic Curves", self)
        self._title.setStyleSheet("font-weight: bold; font-size: 14pt; color: #2c3e50;")
        layout.addWidget(self._title)

        self._subtitle = QLabel(
            "Curves are generated from the current ship dimensions (L, B, design draft). "
            "They are used for draft and trim in stability calculations.",
            self,
        )
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("color: #555; margin-bottom: 8px;")
        layout.addWidget(self._subtitle)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chart_container = QWidget(self)
        self._chart_layout = QVBoxLayout(self._chart_container)
        self._chart_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._chart_container)
        layout.addWidget(scroll, 1)

        self._no_data_label = QLabel("No ship loaded. Add a ship in Tools → Ship & data setup, then open Loading Condition.", self)
        self._no_data_label.setWordWrap(True)
        self._no_data_label.setStyleSheet("color: #888; padding: 24px;")
        self._chart_layout.addWidget(self._no_data_label)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._refresh_curves()

    def _get_ship(self) -> Any:
        if self._get_current_ship is not None:
            return self._get_current_ship()
        # Fallback: find main window and condition editor from parent chain
        p = self.parent()
        while p and not hasattr(p, "_page_indexes"):
            p = p.parent()
        if p and hasattr(p, "_stack") and hasattr(p, "_page_indexes"):
            cond_editor = p._stack.widget(p._page_indexes.condition_editor)
            return getattr(cond_editor, "_current_ship", None)
        return None

    def _refresh_curves(self) -> None:
        ship = self._get_ship()
        if not ship:
            self._curves = None
            self._draw_empty()
            return
        L = max(0.0, getattr(ship, "length_overall_m", 0) or 0)
        B = max(0.0, getattr(ship, "breadth_m", 0) or 0)
        T = max(0.1, getattr(ship, "design_draft_m", 0) or 1.0)
        if L <= 0 or B <= 0:
            self._curves = None
            self._draw_empty()
            return
        self._curves = build_curves_from_formulas(L, B, T, cb=DEFAULT_CB, rho=RHO_SEA)
        self._draw_curves()

    def _draw_empty(self) -> None:
        if self._canvas:
            self._chart_layout.removeWidget(self._canvas)
            self._canvas.deleteLater()
            self._canvas = None
        self._no_data_label.setVisible(True)

    def _draw_curves(self) -> None:
        self._no_data_label.setVisible(False)
        if self._canvas:
            self._chart_layout.removeWidget(self._canvas)
            self._canvas.deleteLater()
        if not self._curves or not self._curves.is_valid():
            self._no_data_label.setVisible(True)
            return
        c = self._curves
        fig = Figure(figsize=(10, 10), dpi=100)
        axes = fig.subplots(2, 2)
        fig.suptitle("Generated hydrostatic curves (from ship dimensions)", fontsize=11)

        # 1. Displacement vs draft
        ax = axes[0, 0]
        ax.plot(c.draft_m, c.displacement_t, "b-", linewidth=1.5)
        ax.set_xlabel("Draft (m)")
        ax.set_ylabel("Displacement (t)")
        ax.set_title("Displacement vs draft")
        ax.grid(True, alpha=0.3)

        # 2. KB vs draft
        ax = axes[0, 1]
        if c.kb_m and len(c.kb_m) == len(c.draft_m):
            ax.plot(c.draft_m, c.kb_m, "g-", linewidth=1.5)
        ax.set_xlabel("Draft (m)")
        ax.set_ylabel("KB (m)")
        ax.set_title("KB vs draft")
        ax.grid(True, alpha=0.3)

        # 3. LCB (norm) vs draft
        ax = axes[1, 0]
        if c.lcb_norm and len(c.lcb_norm) == len(c.draft_m):
            ax.plot(c.draft_m, c.lcb_norm, "m-", linewidth=1.5)
        ax.set_xlabel("Draft (m)")
        ax.set_ylabel("LCB (0–1)")
        ax.set_title("LCB vs draft")
        ax.grid(True, alpha=0.3)

        # 4. Waterplane inertia I_T, I_L vs draft
        ax = axes[1, 1]
        if c.i_t_m4 and c.i_l_m4:
            ax.plot(c.draft_m, c.i_t_m4, "c-", linewidth=1.5, label="I_T (transverse)")
            ax.plot(c.draft_m, c.i_l_m4, "orange", linewidth=1.5, label="I_L (longitudinal)")
            ax.legend(loc="upper right", fontsize=8)
        ax.set_xlabel("Draft (m)")
        ax.set_ylabel("Moment of inertia (m⁴)")
        ax.set_title("Waterplane I_T & I_L vs draft")
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        self._canvas = FigureCanvasQTAgg(fig)
        self._chart_layout.insertWidget(0, self._canvas, 1)
