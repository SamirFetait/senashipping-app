"""
Hydrostatic Calculator dialog.

View curves (formula-based or loaded), enter displacement, solve for draft and trim.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QGroupBox,
)
from PyQt6.QtCore import Qt

from ..services.hydrostatics import (
    RHO_SEA,
    DEFAULT_CB,
    solve_draft_from_displacement,
)
from ..services.hydrostatic_curves import build_curves_from_formulas


class HydrostaticCalculatorDialog(QDialog):
    """Dialog to solve draft and trim from displacement using hydrostatic curves."""

    def __init__(self, parent=None, ship=None):
        super().__init__(parent)
        self._ship = ship
        self.setWindowTitle("Hydrostatic Calculator")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Ship dimensions (editable; filled from ship if available)
        dim_group = QGroupBox("Ship dimensions")
        dim_form = QFormLayout()
        self._length_edit = QLineEdit(self)
        self._length_edit.setPlaceholderText("e.g. 118")
        self._breadth_edit = QLineEdit(self)
        self._breadth_edit.setPlaceholderText("e.g. 19.4")
        self._draft_edit = QLineEdit(self)
        self._draft_edit.setPlaceholderText("e.g. 7.6")
        dim_form.addRow("Length LOA (m):", self._length_edit)
        dim_form.addRow("Breadth (m):", self._breadth_edit)
        dim_form.addRow("Design draft (m):", self._draft_edit)
        dim_group.setLayout(dim_form)
        layout.addWidget(dim_group)

        # Displacement input
        input_group = QGroupBox("Input")
        input_form = QFormLayout()
        self._displacement_edit = QLineEdit(self)
        self._displacement_edit.setPlaceholderText("e.g. 5000")
        self._lcg_edit = QLineEdit(self)
        self._lcg_edit.setPlaceholderText("0.5 = amidships")
        self._lcg_edit.setText("0.5")
        input_form.addRow("Displacement (t):", self._displacement_edit)
        input_form.addRow("LCG (0–1):", self._lcg_edit)
        input_group.setLayout(input_form)
        layout.addWidget(input_group)

        # Solve button
        btn_layout = QHBoxLayout()
        self._solve_btn = QPushButton("Solve draft & trim", self)
        self._solve_btn.clicked.connect(self._on_solve)
        btn_layout.addWidget(self._solve_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Results
        result_group = QGroupBox("Results")
        result_form = QFormLayout()
        self._draft_result = QLineEdit(self)
        self._draft_result.setReadOnly(True)
        self._trim_result = QLineEdit(self)
        self._trim_result.setReadOnly(True)
        result_form.addRow("Mean draft (m):", self._draft_result)
        result_form.addRow("Trim (m, +ve stern down):", self._trim_result)
        result_group.setLayout(result_form)
        layout.addWidget(result_group)

        self._curve_info = QLabel(self)
        self._curve_info.setWordWrap(True)
        layout.addWidget(self._curve_info)

        self._fill_from_ship()

    def _fill_from_ship(self) -> None:
        if self._ship:
            L = getattr(self._ship, "length_overall_m", 0) or 0
            B = getattr(self._ship, "breadth_m", 0) or 0
            T = getattr(self._ship, "design_draft_m", 0) or 0
            if L > 0:
                self._length_edit.setText(f"{L:.2f}")
            if B > 0:
                self._breadth_edit.setText(f"{B:.2f}")
            if T > 0:
                self._draft_edit.setText(f"{T:.2f}")

    def _on_solve(self) -> None:
        try:
            L = float(self._length_edit.text().strip() or 0)
            B = float(self._breadth_edit.text().strip() or 0)
            design_draft = float(self._draft_edit.text().strip() or 1.0)
            disp = float(self._displacement_edit.text().strip() or 0)
            lcg = float(self._lcg_edit.text().strip() or 0.5)
        except ValueError:
            self._draft_result.setText("—")
            self._trim_result.setText("Invalid input")
            return
        if L <= 0 or B <= 0 or design_draft <= 0:
            self._draft_result.setText("—")
            self._trim_result.setText("L, B, design draft must be > 0")
            return
        if disp <= 0:
            self._draft_result.setText("0")
            self._trim_result.setText("0")
            self._curve_info.setText("Curves: formula-based (L, B, Cb). Enter displacement > 0 to solve.")
            return
        lcg = max(0.0, min(1.0, lcg))
        curves = build_curves_from_formulas(L, B, design_draft, cb=DEFAULT_CB, rho=RHO_SEA)
        draft_m, trim_m = solve_draft_from_displacement(
            disp, L, B, lcg, RHO_SEA, DEFAULT_CB, curves
        )
        self._draft_result.setText(f"{draft_m:.3f}")
        self._trim_result.setText(f"{trim_m:.3f}")
        self._curve_info.setText(
            f"Curves: formula-based, {len(curves.draft_m)} points, "
            f"draft 0–{design_draft:.1f} m, displacement 0–{curves.displacement_t[-1]:.0f} t."
        )
