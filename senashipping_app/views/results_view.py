"""
Results view.

Displays basic calculated results for a loading condition and a simple
text report generated from the reports module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTabWidget,
    QSplitter,
    QGroupBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ..models import Voyage
from ..repositories import database
from ..services.condition_service import ConditionService
from ..config.stability_manual_ref import (
    MANUAL_VESSEL_NAME,
    MANUAL_IMO,
    MANUAL_REF,
    MANUAL_SOURCE,
    OPERATING_RESTRICTIONS,
)
from ..reports import build_condition_summary_text, export_condition_to_pdf, export_condition_to_excel
from ..services.stability_service import ConditionResults
from ..services.validation import ValidationResult
from ..services.criteria_rules import CriterionResult
from ..services.alarms import build_alarm_rows, AlarmStatus
from ..config.limits import MASS_PER_HEAD_T


# Fixed height and style for Condition Results section headers (tabs and main sections)
SECTION_HEADER_HEIGHT = 28
SECTION_HEADER_STYLE = "font-weight: bold; color: #2c3e50;"


class ResultsView(QWidget):
    @staticmethod
    def _section_header(parent: QWidget, text: str, *, is_main: bool = False) -> QLabel:
        """Return a consistent section header label with fixed height and style."""
        label = QLabel(text, parent)
        label.setFixedHeight(SECTION_HEADER_HEIGHT)
        label.setStyleSheet(SECTION_HEADER_STYLE)
        font = label.font()
        font.setWeight(QFont.Weight.Bold)
        if is_main:
            font.setPointSize(max(11, font.pointSize() + 1))
        label.setFont(font)
        return label

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._ship_name = QLineEdit(self)
        self._condition_name = QLineEdit(self)
        self._disp_edit = QLineEdit(self)
        self._draft_edit = QLineEdit(self)
        self._draft_aft_edit = QLineEdit(self)
        self._draft_fwd_edit = QLineEdit(self)
        self._trim_edit = QLineEdit(self)
        self._heel_edit = QLineEdit(self)
        self._gm_edit = QLineEdit(self)
        self._kg_edit = QLineEdit(self)
        self._km_edit = QLineEdit(self)
        self._swbm_edit = QLineEdit(self)
        self._bm_pct_edit = QLineEdit(self)
        self._sf_pct_edit = QLineEdit(self)
        self._prop_imm_edit = QLineEdit(self)
        self._visibility_edit = QLineEdit(self)
        self._air_draft_edit = QLineEdit(self)
        for w in (
            self._ship_name,
            self._condition_name,
            self._disp_edit,
            self._draft_edit,
            self._draft_aft_edit,
            self._draft_fwd_edit,
            self._trim_edit,
            self._heel_edit,
            self._gm_edit,
            self._kg_edit,
            self._km_edit,
            self._swbm_edit,
            self._bm_pct_edit,
            self._sf_pct_edit,
            self._prop_imm_edit,
            self._visibility_edit,
            self._air_draft_edit,
        ):
            w.setReadOnly(True)

        self._alarms_table = QTableWidget(self)
        self._alarms_table.setColumnCount(6)
        self._alarms_table.setHorizontalHeaderLabels(
            ["No", "Status", "Description", "Attained", "Pass If", "Type"]
        )
        self._alarms_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._alarms_table.setMaximumHeight(200)
        self._alarms_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._alarms_tab_widget = QWidget(self)
        alarms_layout = QVBoxLayout(self._alarms_tab_widget)
        alarms_layout.setContentsMargins(8, 10, 8, 8)
        alarms_layout.addWidget(self._section_header(self._alarms_tab_widget, "Alarm messages"))
        alarms_layout.addSpacing(4)
        alarms_layout.addWidget(self._alarms_table)

        # Weights tab: table Item | Weight (t)
        self._weights_table = QTableWidget(self)
        self._weights_table.setColumnCount(2)
        self._weights_table.setHorizontalHeaderLabels(["Item", "Weight (t)"])
        self._weights_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._weights_table.setMaximumHeight(220)
        self._weights_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._weights_tab_widget = QWidget(self)
        weights_layout = QVBoxLayout(self._weights_tab_widget)
        weights_layout.setContentsMargins(8, 10, 8, 8)
        weights_layout.addWidget(self._section_header(self._weights_tab_widget, "Weight breakdown"))
        weights_layout.addSpacing(4)
        weights_layout.addWidget(self._weights_table)

        # Trim & Stability tab: form layout
        self._trim_draft_aft = QLineEdit(self)
        self._trim_draft_mid = QLineEdit(self)
        self._trim_draft_fwd = QLineEdit(self)
        self._trim_trim = QLineEdit(self)
        self._trim_heel = QLineEdit(self)
        self._trim_gm = QLineEdit(self)
        self._trim_kg = QLineEdit(self)
        self._trim_km = QLineEdit(self)
        for w in (
            self._trim_draft_aft,
            self._trim_draft_mid,
            self._trim_draft_fwd,
            self._trim_trim,
            self._trim_heel,
            self._trim_gm,
            self._trim_kg,
            self._trim_km,
        ):
            w.setReadOnly(True)
        trim_form = QFormLayout()
        trim_form.addRow("Draft Aft (m):", self._trim_draft_aft)
        trim_form.addRow("Draft Mid (m):", self._trim_draft_mid)
        trim_form.addRow("Draft Fwd (m):", self._trim_draft_fwd)
        trim_form.addRow("Trim (m):", self._trim_trim)
        trim_form.addRow("Heel (°):", self._trim_heel)
        trim_form.addRow("GM (m):", self._trim_gm)
        trim_form.addRow("KG (m):", self._trim_kg)
        trim_form.addRow("KM (m):", self._trim_km)
        self._trim_stability_tab_widget = QWidget(self)
        trim_stability_layout = QVBoxLayout(self._trim_stability_tab_widget)
        trim_stability_layout.setContentsMargins(8, 10, 8, 8)
        trim_stability_layout.addWidget(self._section_header(self._trim_stability_tab_widget, "Trim & stability parameters"))
        trim_stability_layout.addSpacing(4)
        trim_stability_layout.addLayout(trim_form)

        # Strength tab: table / form
        self._strength_swbm = QLineEdit(self)
        self._strength_bm_pct = QLineEdit(self)
        self._strength_sf_pct = QLineEdit(self)
        self._strength_sf_max = QLineEdit(self)
        for w in (self._strength_swbm, self._strength_bm_pct, self._strength_sf_pct, self._strength_sf_max):
            w.setReadOnly(True)
        strength_form = QFormLayout()
        strength_form.addRow("Still water BM (tm):", self._strength_swbm)
        strength_form.addRow("BM % Allow:", self._strength_bm_pct)
        strength_form.addRow("Max shear (t):", self._strength_sf_max)
        strength_form.addRow("SF % Allow:", self._strength_sf_pct)
        self._strength_tab_widget = QWidget(self)
        strength_layout = QVBoxLayout(self._strength_tab_widget)
        strength_layout.setContentsMargins(8, 10, 8, 8)
        strength_layout.addWidget(self._section_header(self._strength_tab_widget, "Longitudinal strength"))
        strength_layout.addSpacing(4)
        strength_layout.addLayout(strength_form)

        # Cargo tab: livestock table Pen name | Pen deck | Head count | Weight (t)
        self._cargo_table = QTableWidget(self)
        self._cargo_table.setColumnCount(4)
        self._cargo_table.setHorizontalHeaderLabels(["Pen name", "Pen deck", "Head count", "Weight (t)"])
        self._cargo_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._cargo_table.setMaximumHeight(220)
        self._cargo_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._cargo_tab_widget = QWidget(self)
        cargo_layout = QVBoxLayout(self._cargo_tab_widget)
        cargo_layout.setContentsMargins(8, 10, 8, 8)
        cargo_layout.addWidget(self._section_header(self._cargo_tab_widget, "Livestock / cargo summary"))
        cargo_layout.addSpacing(4)
        cargo_layout.addWidget(self._cargo_table)

        self._report_view = QPlainTextEdit(self)
        self._report_view.setReadOnly(True)

        self._status_label = QLabel(self)
        self._status_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self._warnings_edit = QPlainTextEdit(self)
        self._warnings_edit.setReadOnly(True)
        self._warnings_edit.setMaximumHeight(80)

        self._criteria_table = QTableWidget(self)
        self._criteria_table.setColumnCount(7)
        self._criteria_table.setHorizontalHeaderLabels(
            ["Rule Set", "Code", "Name", "Result", "Value", "Limit", "Margin"]
        )
        self._criteria_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._criteria_table.setMaximumHeight(180)
        self._criteria_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self._trace_label = QLabel(self)
        self._trace_label.setWordWrap(True)

        # Stability manual reference (from Loading Manual – operating restrictions)
        self._manual_ref_group = QGroupBox("Stability manual reference")
        self._manual_ref_text = QPlainTextEdit(self)
        self._manual_ref_text.setReadOnly(True)
        self._manual_ref_text.setMaximumHeight(120)
        self._manual_ref_text.setPlaceholderText("Loading Manual reference and operating restrictions.")
        _manual_lines = [
            f"Source: {MANUAL_SOURCE}  |  {MANUAL_VESSEL_NAME}  IMO {MANUAL_IMO}",
            f"Criteria: {MANUAL_REF}",
            "",
            "Operating restrictions:",
        ] + [f"  • {r}" for r in OPERATING_RESTRICTIONS]
        self._manual_ref_text.setPlainText("\n".join(_manual_lines))
        manual_layout = QVBoxLayout()
        manual_layout.addWidget(self._manual_ref_text)
        self._manual_ref_group.setLayout(manual_layout)
        
        self._export_pdf_btn = QPushButton("Export PDF", self)
        self._export_excel_btn = QPushButton("Export Excel", self)
        self._export_text_btn = QPushButton("Export Text", self)

        self._last_results: ConditionResults | None = None
        self._last_ship: Any = None
        self._last_condition: Any = None
        self._last_voyage: Voyage | None = None

        self._build_layout()
        self._connect_signals()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(self._section_header(self, "Condition Results", is_main=True))
        root.addSpacing(4)

        # Top split: Alarms (left) | Calculation Summary (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Alarms panel with tabs
        alarms_tabs = QTabWidget()
        alarms_tabs.addTab(self._alarms_tab_widget, "Alarms")
        alarms_tabs.addTab(self._weights_tab_widget, "Weights")
        alarms_tabs.addTab(self._trim_stability_tab_widget, "Trim & Stability")
        alarms_tabs.addTab(self._strength_tab_widget, "Strength")
        alarms_tabs.addTab(self._cargo_tab_widget, "Cargo")
        splitter.addWidget(alarms_tabs)

        # Calculation summary group – enhanced styling
        summary_group = QGroupBox("Calculation Summary")
        summary_group.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #2c3e50; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 2px 6px; }"
        )
        summary_group.setMinimumWidth(260)
        summary_form = QFormLayout()
        summary_form.setSpacing(6)
        summary_form.addRow("Ship:", self._ship_name)
        summary_form.addRow("Condition:", self._condition_name)
        summary_form.addRow("Displacement (t):", self._disp_edit)
        summary_form.addRow("Draft Mid (m):", self._draft_edit)
        summary_form.addRow("Draft Aft (m):", self._draft_aft_edit)
        summary_form.addRow("Draft Fwd (m):", self._draft_fwd_edit)
        summary_form.addRow("Trim (m):", self._trim_edit)
        summary_form.addRow("Heel (°):", self._heel_edit)
        summary_form.addRow("GM (m):", self._gm_edit)
        summary_form.addRow("KG (m):", self._kg_edit)
        summary_form.addRow("KM (m):", self._km_edit)
        summary_form.addRow("SWBM (tm):", self._swbm_edit)
        summary_form.addRow("BM % Allow:", self._bm_pct_edit)
        summary_form.addRow("SF % Allow:", self._sf_pct_edit)
        summary_form.addRow("Prop immersion %:", self._prop_imm_edit)
        summary_form.addRow("Visibility (m):", self._visibility_edit)
        summary_form.addRow("Air draft (m):", self._air_draft_edit)
        summary_group.setLayout(summary_form)
        splitter.addWidget(summary_group)
        splitter.setSizes([400, 280])
        root.addWidget(splitter)

        root.addWidget(self._status_label)
        root.addWidget(self._section_header(self, "Validation messages"))
        root.addSpacing(2)
        root.addWidget(self._warnings_edit)
        root.addWidget(self._section_header(self, "IMO & Livestock Criteria Checklist"))
        root.addSpacing(2)
        root.addWidget(self._criteria_table)
        root.addWidget(self._section_header(self, "Calculation traceability"))
        root.addSpacing(2)
        root.addWidget(self._trace_label)
        root.addWidget(self._manual_ref_group)
        root.addWidget(self._section_header(self, "Text Report"))
        root.addSpacing(2)
        root.addWidget(self._report_view, 1)

        export_row = QHBoxLayout()
        export_row.addWidget(self._export_pdf_btn)
        export_row.addWidget(self._export_excel_btn)
        export_row.addWidget(self._export_text_btn)
        root.addLayout(export_row)

    def _connect_signals(self) -> None:
        self._export_pdf_btn.clicked.connect(self._on_export_pdf)
        self._export_excel_btn.clicked.connect(self._on_export_excel)
        self._export_text_btn.clicked.connect(self._on_export_text)

    def _populate_alarms_table(
        self,
        results: ConditionResults,
        validation: ValidationResult | None,
        criteria: object | None,
    ) -> None:
        rows = build_alarm_rows(results, validation, criteria)
        self._alarms_table.setRowCount(len(rows))
        for row, ar in enumerate(rows):
            self._alarms_table.setItem(row, 0, QTableWidgetItem(str(ar.no)))
            status_item = QTableWidgetItem(ar.status.value)
            if ar.status == AlarmStatus.PASS:
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            elif ar.status == AlarmStatus.FAIL:
                status_item.setForeground(Qt.GlobalColor.darkRed)
            elif ar.status == AlarmStatus.WARN:
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            self._alarms_table.setItem(row, 1, status_item)
            self._alarms_table.setItem(row, 2, QTableWidgetItem(ar.description))
            self._alarms_table.setItem(row, 3, QTableWidgetItem(ar.attained))
            self._alarms_table.setItem(row, 4, QTableWidgetItem(ar.pass_if))
            self._alarms_table.setItem(row, 5, QTableWidgetItem(ar.type.value))

    def _populate_criteria_table(self, criteria: object | None) -> None:
        self._criteria_table.setRowCount(0)
        if not criteria or not hasattr(criteria, "lines"):
            return
        for row, line in enumerate(criteria.lines):
            self._criteria_table.insertRow(row)
            self._criteria_table.setItem(row, 0, QTableWidgetItem(line.parent_code or ""))
            self._criteria_table.setItem(row, 1, QTableWidgetItem(line.code))
            self._criteria_table.setItem(row, 2, QTableWidgetItem(line.name))
            result_item = QTableWidgetItem(line.result.value)
            if line.result == CriterionResult.PASS:
                result_item.setForeground(Qt.GlobalColor.darkGreen)
            elif line.result == CriterionResult.FAIL:
                result_item.setForeground(Qt.GlobalColor.darkRed)
            self._criteria_table.setItem(row, 3, result_item)
            val_str = f"{line.value:.3f}" if line.value is not None else "—"
            self._criteria_table.setItem(row, 4, QTableWidgetItem(val_str))
            lim_str = f"{line.limit:.3f}" if line.limit is not None else "—"
            self._criteria_table.setItem(row, 5, QTableWidgetItem(lim_str))
            marg_str = f"{line.margin:+.3f}" if line.margin is not None else "—"
            self._criteria_table.setItem(row, 6, QTableWidgetItem(marg_str))

    def _populate_traceability(self, snapshot: object | None) -> None:
        if not snapshot:
            self._trace_label.setText("")
            return
        ts = getattr(snapshot, "timestamp", None)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(ts, "strftime") else str(ts)
        summary = getattr(snapshot, "criteria_summary", "")
        ship = getattr(snapshot, "ship_name", "")
        cond = getattr(snapshot, "condition_name", "")
        self._trace_label.setText(
            f"Calculated: {ts_str} | Ship: {ship} | Condition: {cond} | {summary}"
        )

    def _populate_weights_tab(self, results: ConditionResults, condition: Any) -> None:
        """Fill Weights tab: displacement and optional breakdown (livestock, tanks & other)."""
        self._weights_table.setRowCount(0)
        disp = results.displacement_t
        pen_loadings = getattr(condition, "pen_loadings", None) or {}
        livestock_t = sum(h * MASS_PER_HEAD_T for h in pen_loadings.values())
        tank_other = disp - livestock_t if disp >= 0 else 0.0
        rows = [
            ("Total displacement", f"{disp:,.1f}"),
            ("Livestock (from head count)", f"{livestock_t:,.1f}" if pen_loadings else "—"),
            ("Tanks & other", f"{tank_other:,.1f}"),
        ]
        for i, (item, weight) in enumerate(rows):
            self._weights_table.insertRow(i)
            self._weights_table.setItem(i, 0, QTableWidgetItem(item))
            self._weights_table.setItem(i, 1, QTableWidgetItem(weight))

    def _populate_trim_stability_tab(
        self, results: ConditionResults, validation: ValidationResult | None
    ) -> None:
        """Fill Trim & Stability tab from results."""
        draft_aft = getattr(results, "draft_aft_m", results.draft_m + results.trim_m / 2)
        draft_fwd = getattr(results, "draft_fwd_m", results.draft_m - results.trim_m / 2)
        heel = getattr(results, "heel_deg", 0.0)
        gm_display = validation.gm_effective if validation else results.gm_m
        self._trim_draft_aft.setText(f"{draft_aft:.3f}")
        self._trim_draft_mid.setText(f"{results.draft_m:.3f}")
        self._trim_draft_fwd.setText(f"{draft_fwd:.3f}")
        self._trim_trim.setText(f"{results.trim_m:.3f}")
        self._trim_heel.setText(f"{heel:.2f}")
        self._trim_gm.setText(f"{gm_display:.3f}")
        self._trim_kg.setText(f"{results.kg_m:.3f}")
        self._trim_km.setText(f"{results.km_m:.3f}")

    def _populate_strength_tab(self, results: ConditionResults) -> None:
        """Fill Strength tab from results.strength."""
        strength = getattr(results, "strength", None)
        if not strength:
            self._strength_swbm.setText("")
            self._strength_bm_pct.setText("")
            self._strength_sf_pct.setText("")
            self._strength_sf_max.setText("")
            return

        # Show the approximate SWBM and shear, but mark %Allow as N/A when no real design limits exist.
        self._strength_swbm.setText(f"{getattr(strength, 'still_water_bm_approx_tm', 0):,.0f}")
        if getattr(strength, "design_bm_tm", 0.0) > 0:
            self._strength_bm_pct.setText(f"{getattr(strength, 'bm_pct_allow', 0):.1f}%")
        else:
            self._strength_bm_pct.setText("N/A")

        if getattr(strength, "design_sf_t", 0.0) > 0:
            self._strength_sf_pct.setText(f"{getattr(strength, 'sf_pct_allow', 0):.1f}%")
        else:
            self._strength_sf_pct.setText("N/A")

        self._strength_sf_max.setText(f"{getattr(strength, 'shear_force_max_t', 0):,.1f}")

    def _populate_cargo_tab(self, condition: Any, ship: Any) -> None:
        """Fill Cargo tab from condition.pen_loadings; show pen name and deck instead of pen ID."""
        self._cargo_table.setRowCount(0)
        pen_loadings = getattr(condition, "pen_loadings", None) or {}
        if not pen_loadings:
            self._cargo_table.insertRow(0)
            self._cargo_table.setItem(0, 0, QTableWidgetItem("—"))
            self._cargo_table.setItem(0, 1, QTableWidgetItem("—"))
            self._cargo_table.setItem(0, 2, QTableWidgetItem("No livestock loaded"))
            self._cargo_table.setItem(0, 3, QTableWidgetItem("—"))
            return
        # Resolve pen_id -> (name, deck) from DB
        pen_by_id: dict[int, Any] = {}
        if ship and getattr(ship, "id", None) and database.SessionLocal:
            with database.SessionLocal() as db:
                pens = ConditionService(db).get_pens_for_ship(ship.id)
                pen_by_id = {p.id: p for p in pens if p.id is not None}
        total_heads = 0
        total_weight = 0.0
        # Sort by (deck, name) for display
        def sort_key(item: tuple) -> tuple:
            pen_id, heads = item
            p = pen_by_id.get(pen_id)
            return (p.deck if p else "", p.name if p else str(pen_id), pen_id)
        for pen_id, heads in sorted(pen_loadings.items(), key=sort_key):
            if heads <= 0:
                continue
            w_t = heads * MASS_PER_HEAD_T
            total_heads += heads
            total_weight += w_t
            p = pen_by_id.get(pen_id)
            pen_name = p.name if p else str(pen_id)
            pen_deck = p.deck if p else ""
            self._cargo_table.insertRow(self._cargo_table.rowCount())
            r = self._cargo_table.rowCount() - 1
            self._cargo_table.setItem(r, 0, QTableWidgetItem(pen_name))
            self._cargo_table.setItem(r, 1, QTableWidgetItem(pen_deck))
            self._cargo_table.setItem(r, 2, QTableWidgetItem(str(heads)))
            self._cargo_table.setItem(r, 3, QTableWidgetItem(f"{w_t:,.1f}"))
        self._cargo_table.insertRow(self._cargo_table.rowCount())
        r = self._cargo_table.rowCount() - 1
        self._cargo_table.setItem(r, 0, QTableWidgetItem("Total"))
        self._cargo_table.setItem(r, 1, QTableWidgetItem(""))
        self._cargo_table.setItem(r, 2, QTableWidgetItem(str(total_heads)))
        self._cargo_table.setItem(r, 3, QTableWidgetItem(f"{total_weight:,.1f}"))

    def update_results(
        self,
        results: ConditionResults,
        ship: Any,
        condition: Any,
        voyage: Voyage | None = None,
    ) -> None:
        """Slot called when a condition has been computed."""
        self._last_results = results
        self._last_ship = ship
        self._last_condition = condition
        self._last_voyage = voyage or Voyage(
            id=None,
            ship_id=getattr(ship, "id", None),
            name="Ad-hoc",
            departure_port="",
            arrival_port="",
        )

        self._ship_name.setText(getattr(ship, "name", ""))
        self._condition_name.setText(getattr(condition, "name", ""))

        self._disp_edit.setText(f"{results.displacement_t:.1f}")
        self._draft_edit.setText(f"{results.draft_m:.2f}")
        draft_aft = getattr(results, "draft_aft_m", results.draft_m + results.trim_m / 2)
        draft_fwd = getattr(results, "draft_fwd_m", results.draft_m - results.trim_m / 2)
        heel = getattr(results, "heel_deg", 0.0)
        self._draft_aft_edit.setText(f"{draft_aft:.2f}")
        self._draft_fwd_edit.setText(f"{draft_fwd:.2f}")
        self._trim_edit.setText(f"{results.trim_m:.2f}")
        self._heel_edit.setText(f"{heel:.2f}")
        validation: ValidationResult | None = getattr(results, "validation", None)
        gm_display = validation.gm_effective if validation else results.gm_m
        self._gm_edit.setText(f"{gm_display:.2f}")

        if validation:
            if validation.has_errors:
                self._status_label.setText("FAILED – Condition does not meet limits")
                self._status_label.setStyleSheet(
                    "font-weight: bold; font-size: 11pt; color: #c0392b;"
                )
            elif validation.has_warnings:
                self._status_label.setText("WARNING – Review before approval")
                self._status_label.setStyleSheet(
                    "font-weight: bold; font-size: 11pt; color: #d35400;"
                )
            else:
                self._status_label.setText("OK – Within limits")
                self._status_label.setStyleSheet(
                    "font-weight: bold; font-size: 11pt; color: #27ae60;"
                )
            lines = [f"[{i.severity.value.upper()}] {i.message}" for i in validation.issues]
            self._warnings_edit.setPlainText("\n".join(lines) if lines else "No issues.")
        else:
            self._status_label.setText("OK")
            self._status_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
            self._warnings_edit.setPlainText("")
        self._kg_edit.setText(f"{results.kg_m:.2f}")
        self._km_edit.setText(f"{results.km_m:.2f}")
        strength = getattr(results, "strength", None)
        swbm = strength.still_water_bm_approx_tm if strength else 0.0
        bm_pct = getattr(strength, "bm_pct_allow", 0.0) if strength else 0.0
        sf_pct = getattr(strength, "sf_pct_allow", 0.0) if strength else 0.0
        self._swbm_edit.setText(f"{swbm:.0f}")
        self._bm_pct_edit.setText(f"{bm_pct:.1f}%")
        self._sf_pct_edit.setText(f"{sf_pct:.1f}%")

        anc = getattr(results, "ancillary", None)
        if anc:
            self._prop_imm_edit.setText(f"{getattr(anc, 'prop_immersion_pct', 0):.1f}%")
            self._visibility_edit.setText(f"{getattr(anc, 'visibility_m', 0):.1f}")
            self._air_draft_edit.setText(f"{getattr(anc, 'air_draft_m', 0):.1f}")
        else:
            self._prop_imm_edit.setText("")
            self._visibility_edit.setText("")
            self._air_draft_edit.setText("")

        voyage = self._last_voyage

        # Populate alarms table
        self._populate_alarms_table(results, validation, getattr(results, "criteria", None))

        # Populate Weights, Trim & Stability, Strength, Cargo tabs
        self._populate_weights_tab(results, condition)
        self._populate_trim_stability_tab(results, validation)
        self._populate_strength_tab(results)
        self._populate_cargo_tab(condition, ship)

        # Populate criteria checklist
        self._populate_criteria_table(getattr(results, "criteria", None))

        # Populate traceability
        self._populate_traceability(getattr(results, "snapshot", None))

        strength = getattr(results, "strength", None)
        swbm = strength.still_water_bm_approx_tm if strength else 0.0
        snapshot = getattr(results, "snapshot", None)
        criteria = getattr(results, "criteria", None)
        crit_sum = ""
        if criteria and hasattr(criteria, "passed") and hasattr(criteria, "failed"):
            crit_sum = f"{criteria.passed} passed, {criteria.failed} failed"
        ts_str = ""
        if snapshot and hasattr(snapshot, "timestamp"):
            ts_str = snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        text = build_condition_summary_text(
            ship, voyage, condition,
            kg_m=results.kg_m,
            km_m=results.km_m,
            swbm_tm=swbm,
            criteria_summary=crit_sum,
            trace_timestamp=ts_str,
        )
        self._report_view.setPlainText(text)

    def _on_export_pdf(self) -> None:
        if not all([self._last_results, self._last_ship, self._last_condition, self._last_voyage]):
            QMessageBox.information(
                self,
                "Export",
                "Compute a condition first to export.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export PDF",
            str(Path.home()),
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            export_condition_to_pdf(
                Path(path),
                self._last_ship,
                self._last_voyage,
                self._last_condition,
                self._last_results,
            )
            QMessageBox.information(self, "Export", f"Saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))


    def _on_export_excel(self) -> None:
        if not all([self._last_results, self._last_ship, self._last_condition, self._last_voyage]):
            QMessageBox.information(
                self,
                "Export",
                "Compute a condition first to export.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Excel",
            str(Path.home()),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_condition_to_excel(
                Path(path),
                self._last_ship,
                self._last_voyage,
                self._last_condition,
                self._last_results,
            )
            QMessageBox.information(self, "Export", f"Saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))


