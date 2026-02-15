"""
Loading Condition editor view.

Single-ship mode: ship and voyage are fixed (configured once via Tools → Ship & data setup).
User enters cargo type; tanks/pens and ship particulars are static.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QMessageBox,
    QSplitter,
)

from ..models import Ship, Voyage, LoadingCondition, Tank, CargoType
from ..repositories import database
from ..repositories.ship_repository import ShipRepository
from ..repositories.cargo_type_repository import CargoTypeRepository
from ..services.condition_service import (
    ConditionService,
    ConditionValidationError,
    ConditionResults,
)
from ..services.voyage_service import VoyageService, VoyageValidationError
from .deck_profile_widget import DeckProfileWidget
from .results_panel import ResultsPanel
from .condition_table_widget import ConditionTableWidget
from .cargo_library_dialog import CargoLibraryDialog


class ConditionEditorView(QWidget):
    # Signal emitted when a condition has been computed:
    # args: results, ship, condition, voyage (or None for ad-hoc)
    condition_computed = pyqtSignal(object, object, object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        if database.SessionLocal is None:
            raise RuntimeError("Database not initialized")

        self._ships: List[Ship] = []
        self._voyages: List[Voyage] = []
        self._conditions: List[LoadingCondition] = []
        self._cargo_types: List[CargoType] = []
        self._current_ship: Optional[Ship] = None
        self._current_voyage: Optional[Voyage] = None
        self._current_condition: Optional[LoadingCondition] = None

        self._ship_combo = QComboBox(self)
        self._voyage_combo = QComboBox(self)
        self._condition_combo = QComboBox(self)
        self._ship_label = QLabel(self)  # read-only ship name (single-ship mode)
        self._cargo_type_combo = QComboBox(self)  # from cargo library
        self._cargo_type_combo.setEditable(True)  # allow typing if not in library
        self._cargo_type_combo.setMinimumWidth(180)
        self._cargo_library_btn = QPushButton("Edit library...", self)
        self._condition_name_edit = QLineEdit(self)
        self._tank_table = QTableWidget(self)
        self._tank_table.setColumnCount(3)
        self._tank_table.setHorizontalHeaderLabels(
            ["Tank", "Capacity (m³)", "Fill %"]
        )
        self._tank_table.horizontalHeader().setStretchLastSection(True)
        self._tank_table.setAlternatingRowColors(True)
        self._tank_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tank_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        self._pen_table = QTableWidget(self)
        self._pen_table.setColumnCount(4)
        self._pen_table.setHorizontalHeaderLabels(
            ["Pen", "Deck", "Area (m²)", "Head Count"]
        )
        self._pen_table.horizontalHeader().setStretchLastSection(True)
        self._pen_table.setMaximumHeight(120)
        self._pen_table.setAlternatingRowColors(True)
        self._pen_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pen_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        self._compute_btn = QPushButton("Compute Results", self)
        self._save_condition_btn = QPushButton("Save Condition", self)

        # Graphical deck/profile view (left side)
        self._deck_profile_widget = DeckProfileWidget(self)
        
        # Cross-section widget (middle, between profile and results)
        # self._cross_section_widget = CrossSectionWidget(self)
        
        # Results panel (right side)
        self._results_panel = ResultsPanel(self)
        
        # Tabbed table widget (bottom)
        self._condition_table = ConditionTableWidget(self)
        
        # Store last computed results
        self._last_results: Optional[ConditionResults] = None

        self._build_layout()
        self._connect_signals()
        # Single-ship: save to voyage disabled; user saves via File → Save
        self._save_condition_btn.setEnabled(False)
        self._save_condition_btn.setToolTip("Save to file via File → Save")
        self._load_ships()
        self._refresh_cargo_types()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        
        # Apply modern styling
        self.setStyleSheet("""
            QComboBox {
                padding: 4px;
                border: 1px solid #ccc;
                border-radius: 3px;
                background-color: white;
            }
            QComboBox:hover {
                border: 1px solid #999;
            }
            QLineEdit {
                padding: 4px;
                border: 1px solid #ccc;
                border-radius: 3px;
            }
            QLineEdit:focus {
                border: 2px solid #4A90E2;
            }
            QPushButton {
                padding: 6px 16px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #f0f0f0;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
            QTableWidget {
                border: 1px solid #ddd;
                gridline-color: #e0e0e0;
                background-color: white;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #4A90E2;
                color: white;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 6px;
                border: 1px solid #ddd;
                font-weight: bold;
            }
        """)

        # Top controls – single-ship: ship is read-only, user only enters cargo type
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(QLabel("Ship:", self))
        top.addWidget(self._ship_label, 1)
        self._ship_label.setStyleSheet("color: #555; padding: 4px;")
        top.addWidget(QLabel("Cargo type:", self))
        top.addWidget(self._cargo_type_combo, 2)
        top.addWidget(self._cargo_library_btn)
        top.addStretch()
        root.addLayout(top)
        # Hide ship/voyage/condition combos (still used internally for load_condition from file)
        self._ship_combo.hide()
        self._voyage_combo.hide()
        self._condition_combo.hide()
        self._condition_name_edit.hide()

        # Main content area: left (profile+deck), middle (cross-section), right (results)
        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setChildrenCollapsible(False)
        
        # Left side: deck/profile widget
        main_splitter.addWidget(self._deck_profile_widget)
        
        # Middle: cross-section widget
        
        # Right side: results panel
        main_splitter.addWidget(self._results_panel)
        
        # Set splitter sizes
        main_splitter.setSizes([600, 200, 300])
        root.addWidget(main_splitter, 2)

        # Bottom: tabbed table widget
        root.addWidget(self._condition_table, 1)

        # Buttons at bottom
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        btn_row.addWidget(self._compute_btn)
        btn_row.addWidget(self._save_condition_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        
        # Hide legacy tables (they're still used for data but not displayed)
        self._tank_table.hide()
        self._pen_table.hide()

    def _connect_signals(self) -> None:
        self._ship_combo.currentIndexChanged.connect(self._on_ship_changed)
        self._voyage_combo.currentIndexChanged.connect(self._on_voyage_changed)
        self._condition_combo.currentIndexChanged.connect(self._on_condition_changed)
        self._compute_btn.clicked.connect(self._on_compute)
        self._save_condition_btn.clicked.connect(self._on_save_condition)
        self._cargo_library_btn.clicked.connect(self._on_edit_cargo_library)
        self._deck_profile_widget.tank_selected.connect(self._on_tank_selected_from_view)

        # Connect table changes for real-time updates
        self._tank_table.itemChanged.connect(self._on_tank_table_changed)
        self._pen_table.itemChanged.connect(self._on_pen_table_changed)

    def _load_ships(self) -> None:
        self._ship_combo.clear()
        self._ships = []
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            repo = ShipRepository(db)
            self._ships = repo.list()

        for ship in self._ships:
            self._ship_combo.addItem(ship.name, ship.id)

        # Single-ship: use first ship only, show name in read-only label
        if self._ships:
            self._current_ship = self._ships[0]
            self._ship_label.setText(self._current_ship.name or "— No ship —")
            self._ship_combo.setCurrentIndex(0)
            self._load_voyages()
            self._set_current_ship(self._current_ship)
        else:
            self._ship_label.setText("— No ship — Add one via Tools → Ship & data setup")
            self._current_ship = None

    def showEvent(self, event: QShowEvent) -> None:
        """Refresh pens and tanks from DB when view is shown (e.g. returning from Ship Manager)."""
        super().showEvent(event)
        if self._current_ship and self._current_ship.id:
            self._set_current_ship(self._current_ship)

    def _refresh_cargo_types(self) -> None:
        """Reload cargo type combo from library and keep list for dynamic calculations."""
        current = self._cargo_type_combo.currentText().strip()
        self._cargo_type_combo.clear()
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            self._cargo_types = CargoTypeRepository(db).list_all()
            for ct in self._cargo_types:
                self._cargo_type_combo.addItem(ct.name, ct.id)
        self._cargo_type_combo.setCurrentText(current)

    def _set_cargo_type_text(self, text: str) -> None:
        """Set cargo type combo to the given name (e.g. when loading condition)."""
        self._cargo_type_combo.setCurrentText(text or "")

    def _on_edit_cargo_library(self) -> None:
        """Open Edit Cargo Library dialog; refresh combo when closed."""
        dlg = CargoLibraryDialog(self)
        dlg.exec()
        self._refresh_cargo_types()

    def _on_tank_selected_from_view(self, tank_id: int) -> None:
        """When user selects a tank polygon in deck view, focus that tank row in data (for calculation)."""
        for row in range(self._tank_table.rowCount()):
            item = self._tank_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == tank_id:
                self._tank_table.setCurrentCell(row, 0)
                self._tank_table.scrollToItem(item)
                return

    def _load_voyages(self) -> None:
        self._voyage_combo.clear()
        self._voyages = []
        if not self._current_ship or not self._current_ship.id:
            self._condition_combo.clear()
            self._conditions = []
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            svc = VoyageService(db)
            self._voyages = svc.list_voyages_for_ship(self._current_ship.id)

        self._voyage_combo.addItem("-- None (ad-hoc) --", None)
        for v in self._voyages:
            self._voyage_combo.addItem(f"{v.name} ({v.departure_port}→{v.arrival_port})", v.id)
        self._voyage_combo.setCurrentIndex(0)
        self._on_voyage_changed(0)

    def _load_conditions(self) -> None:
        self._condition_combo.clear()
        self._conditions = []
        if not self._current_voyage or not self._current_voyage.id:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            svc = VoyageService(db)
            self._conditions = svc.list_conditions_for_voyage(self._current_voyage.id)

        self._condition_combo.addItem("-- New --", None)
        for c in self._conditions:
            self._condition_combo.addItem(c.name, c.id)
        self._condition_combo.setCurrentIndex(0)
        self._on_condition_changed(0)

    def _set_current_ship(self, ship: Ship) -> None:
        self._current_ship = ship
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            tanks = cond_service.get_tanks_for_ship(ship.id)
            pens = cond_service.get_pens_for_ship(ship.id)

        volumes: Dict[int, float] = {}
        pen_loadings: Dict[int, int] = {}
        if self._current_condition:
            volumes = self._current_condition.tank_volumes_m3
            pen_loadings = getattr(self._current_condition, "pen_loadings", {}) or {}
        self._populate_tanks_table(tanks, volumes)
        self._populate_pens_table(pens, pen_loadings)
        
        # Update deck tabs with pens/tanks data
        self._deck_profile_widget.update_tables(pens, tanks)
        
        # Update condition table widget
        volumes = self._current_condition.tank_volumes_m3 if self._current_condition else {}
        pen_loads = getattr(self._current_condition, "pen_loadings", {}) or {} if self._current_condition else {}
        self._update_condition_table(pens, tanks, pen_loads, volumes)

    def _populate_tanks_table(
        self, tanks: List[Tank], volumes: Dict[int, float] | None = None
    ) -> None:
        volumes = volumes or {}
        self._tank_table.setRowCount(0)
        for tank in tanks:
            row = self._tank_table.rowCount()
            self._tank_table.insertRow(row)

            name_item = QTableWidgetItem(tank.name)
            name_item.setData(Qt.ItemDataRole.UserRole, tank.id)

            cap_item = QTableWidgetItem(f"{tank.capacity_m3:.2f}")
            vol = volumes.get(tank.id or -1, 0.0)
            fill_pct = (vol / tank.capacity_m3 * 100.0) if tank.capacity_m3 > 0 else 0.0
            fill_item = QTableWidgetItem(f"{fill_pct:.1f}")

            self._tank_table.setItem(row, 0, name_item)
            self._tank_table.setItem(row, 1, cap_item)
            self._tank_table.setItem(row, 2, fill_item)

    def _populate_pens_table(
        self, pens: list, pen_loadings: Dict[int, int] | None = None
    ) -> None:
        loadings = pen_loadings or {}
        self._pen_table.setRowCount(0)
        for pen in pens:
            row = self._pen_table.rowCount()
            self._pen_table.insertRow(row)
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            self._pen_table.setItem(row, 0, name_item)
            self._pen_table.setItem(row, 1, QTableWidgetItem(pen.deck))
            self._pen_table.setItem(row, 2, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            heads = loadings.get(pen.id or -1, 0)
            self._pen_table.setItem(row, 3, QTableWidgetItem(str(heads)))

    def load_condition(self, voyage_id: int, condition_id: int) -> None:
        """Load a stored condition for editing. Called when user clicks Edit in Voyage Planner."""
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            svc = VoyageService(db)
            voyage = svc.get_voyage(voyage_id)
            condition = svc.get_condition(condition_id)
        if not voyage or not condition:
            return

        ship = next((s for s in self._ships if s.id == voyage.ship_id), None)
        if not ship:
            with database.SessionLocal() as db:
                ship = ShipRepository(db).get(voyage.ship_id)
            if ship:
                self._ships.append(ship)
                self._ship_combo.addItem(ship.name, ship.id)

        self._current_ship = ship
        self._current_voyage = voyage
        self._current_condition = condition

        self._ship_combo.blockSignals(True)
        idx = self._ship_combo.findData(voyage.ship_id)
        if idx >= 0:
            self._ship_combo.setCurrentIndex(idx)
        self._ship_combo.blockSignals(False)

        self._load_voyages()

        self._voyage_combo.blockSignals(True)
        idx = self._voyage_combo.findData(voyage_id)
        if idx >= 0:
            self._voyage_combo.setCurrentIndex(idx)
        self._voyage_combo.blockSignals(False)

        self._load_conditions()

        self._condition_combo.blockSignals(True)
        idx = self._condition_combo.findData(condition_id)
        if idx >= 0:
            self._condition_combo.setCurrentIndex(idx)
        self._condition_combo.blockSignals(False)

        self._condition_name_edit.setText(condition.name)
        self._set_cargo_type_text(condition.name)
        self._ship_label.setText(ship.name if ship else "—")
        self._save_condition_btn.setEnabled(True)
        if ship:
            with database.SessionLocal() as db:
                cond_svc = ConditionService(db)
                tanks = cond_svc.get_tanks_for_ship(ship.id)
                pens = cond_svc.get_pens_for_ship(ship.id)
            self._populate_tanks_table(tanks, condition.tank_volumes_m3)
            pen_loads = getattr(condition, "pen_loadings", {}) or {}
            self._populate_pens_table(pens, pen_loads)
            # Update deck tabs
            self._deck_profile_widget.update_tables(pens, tanks)
            # Update condition table
            self._update_condition_table(pens, tanks, pen_loads, condition.tank_volumes_m3)

    def _on_ship_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._ships):
            self._current_ship = None
            self._voyage_combo.clear()
            self._condition_combo.clear()
            self._tank_table.setRowCount(0)
            return
        self._current_ship = self._ships[index]
        self._current_voyage = None
        self._current_condition = None
        self._load_voyages()
        self._set_current_ship(self._current_ship)

    def _on_voyage_changed(self, index: int) -> None:
        if index <= 0:
            self._current_voyage = None
            self._current_condition = None
        elif index - 1 < len(self._voyages):
            self._current_voyage = self._voyages[index - 1]
            self._current_condition = None
        self._load_conditions()
        self._save_condition_btn.setEnabled(self._current_voyage is not None)
        if self._current_ship:
            self._set_current_ship(self._current_ship)

    def _on_condition_changed(self, index: int) -> None:
        if index <= 0:
            self._current_condition = None
            self._condition_name_edit.clear()
        elif index - 1 < len(self._conditions):
            self._current_condition = self._conditions[index - 1]
            self._condition_name_edit.setText(self._current_condition.name)
        self._save_condition_btn.setEnabled(self._current_voyage is not None)
        if self._current_ship:
            self._set_current_ship(self._current_ship)

    def _on_compute(self) -> None:
        if not self._current_ship or self._current_ship.id is None:
            QMessageBox.information(
                self, "No ship",
                "Add a ship first via Tools → Ship & data setup.",
            )
            return

        condition_name = self._cargo_type_combo.currentText().strip() or "Condition"
        self._condition_name_edit.setText(condition_name)

        condition = LoadingCondition(
            id=self._current_condition.id if self._current_condition else None,
            voyage_id=self._current_voyage.id if self._current_voyage else None,
            name=condition_name,
        )

        tank_volumes: Dict[int, float] = {}
        pen_loadings: Dict[int, int] = {}

        if database.SessionLocal is None:
            QMessageBox.critical(self, "Error", "Database not initialized.")
            return

        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            tanks = cond_service.get_tanks_for_ship(self._current_ship.id)
            tank_by_id = {t.id: t for t in tanks}

        for row in range(self._tank_table.rowCount()):
            name_item = self._tank_table.item(row, 0)
            fill_item = self._tank_table.item(row, 2)
            if not name_item or not fill_item:
                continue

            tank_id = name_item.data(Qt.ItemDataRole.UserRole)
            if tank_id is None:
                continue

            try:
                fill_pct = float(fill_item.text())
            except (TypeError, ValueError):
                fill_pct = 0.0

            fill_pct = max(0.0, min(100.0, fill_pct))
            tank = tank_by_id.get(int(tank_id))
            if not tank:
                continue

            vol = tank.capacity_m3 * (fill_pct / 100.0)
            tank_volumes[int(tank_id)] = vol

        for row in range(self._pen_table.rowCount()):
            name_item = self._pen_table.item(row, 0)
            head_item = self._pen_table.item(row, 3)
            if not name_item or not head_item:
                continue
            pen_id = name_item.data(Qt.ItemDataRole.UserRole)
            if pen_id is None:
                continue
            try:
                heads = int(float(head_item.text()))
            except (TypeError, ValueError):
                heads = 0
            heads = max(0, heads)
            if heads > 0:
                pen_loadings[int(pen_id)] = heads

        condition.tank_volumes_m3 = tank_volumes
        condition.pen_loadings = pen_loadings

        selected_cargo = next(
            (c for c in self._cargo_types if c.name == self._cargo_type_combo.currentText().strip()),
            None,
        )
        try:
            results: ConditionResults = cond_service.compute(
                self._current_ship, condition, tank_volumes,
                cargo_type=selected_cargo,
            )
        except ConditionValidationError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
            return

        self._current_condition = condition
        self._last_results = results
        voyage = self._current_voyage
        
        # Update results panel
        ship_dwt = getattr(self._current_ship, "deadweight_t", 0.0) if self._current_ship else 0.0
        self._results_panel.update_results(results, ship_dwt)
        
        # Update waterline visualization
        draft_aft = getattr(results, "draft_aft_m", results.draft_m + results.trim_m / 2)
        draft_fwd = getattr(results, "draft_fwd_m", results.draft_m - results.trim_m / 2)
        ship_length = getattr(self._current_ship, "length_overall_m", 0.0) if self._current_ship else 0.0
        ship_breadth = getattr(self._current_ship, "breadth_m", 0.0) if self._current_ship else 0.0
        
        self._deck_profile_widget.update_waterline(
            results.draft_m, draft_aft, draft_fwd, ship_length
        )
        self._cross_section_widget.update_waterline(results.draft_m, ship_breadth)
        
        # Update condition table with current data
        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            pens = cond_service.get_pens_for_ship(self._current_ship.id)
            tanks = cond_service.get_tanks_for_ship(self._current_ship.id)
        self._update_condition_table(pens, tanks, pen_loadings, tank_volumes)
        
        self.condition_computed.emit(results, self._current_ship, condition, voyage)
        validation = getattr(results, "validation", None)
        if validation and getattr(validation, "has_errors", False):
            QMessageBox.warning(
                self,
                "Computed – FAILED",
                "Condition computed but fails validation. Check Results tab.",
            )
        else:
            QMessageBox.information(self, "Computed", "Condition results computed.")

    def _on_save_condition(self) -> None:
        if not self._current_voyage or not self._current_voyage.id:
            QMessageBox.information(
                self, "Save", "Select a voyage first to save a condition."
            )
            return
        if not self._current_ship:
            return
        if database.SessionLocal is None:
            return

        # Build condition from current form (same as compute but we need volumes)
        condition_name = self._condition_name_edit.text().strip() or "Condition"
        tank_volumes: Dict[int, float] = {}
        pen_loadings: Dict[int, int] = {}

        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            tanks = cond_service.get_tanks_for_ship(self._current_ship.id)
            tank_by_id = {t.id: t for t in tanks}

        for row in range(self._tank_table.rowCount()):
            name_item = self._tank_table.item(row, 0)
            fill_item = self._tank_table.item(row, 2)
            if not name_item or not fill_item:
                continue
            tank_id = name_item.data(Qt.ItemDataRole.UserRole)
            if tank_id is None:
                continue
            try:
                fill_pct = float(fill_item.text())
            except (TypeError, ValueError):
                fill_pct = 0.0
            fill_pct = max(0.0, min(100.0, fill_pct))
            tank = tank_by_id.get(int(tank_id))
            if not tank:
                continue
            tank_volumes[int(tank_id)] = tank.capacity_m3 * (fill_pct / 100.0)

        for row in range(self._pen_table.rowCount()):
            name_item = self._pen_table.item(row, 0)
            head_item = self._pen_table.item(row, 3)
            if not name_item or not head_item:
                continue
            pen_id = name_item.data(Qt.ItemDataRole.UserRole)
            if pen_id is None:
                continue
            try:
                heads = int(float(head_item.text()))
            except (TypeError, ValueError):
                heads = 0
            if heads > 0:
                pen_loadings[int(pen_id)] = heads

        condition = LoadingCondition(
            id=self._current_condition.id if self._current_condition else None,
            voyage_id=self._current_voyage.id,
            name=condition_name,
            tank_volumes_m3=tank_volumes,
            pen_loadings=pen_loadings,
        )

        with database.SessionLocal() as db:
            svc = VoyageService(db)
            cond_svc = ConditionService(db)
            selected_cargo = next(
                (c for c in self._cargo_types if c.name == self._cargo_type_combo.currentText().strip()),
                None,
            )
            try:
                results = cond_svc.compute(
                    self._current_ship, condition, tank_volumes,
                    cargo_type=selected_cargo,
                )
                condition.displacement_t = results.displacement_t
                condition.draft_m = results.draft_m
                condition.trim_m = results.trim_m
                condition.gm_m = results.gm_m
                condition = svc.save_condition(condition)
            except (ConditionValidationError, VoyageValidationError) as exc:
                QMessageBox.warning(self, "Validation", str(exc))
                return

        self._current_condition = condition
        self._load_conditions()
        
        # Update tables after save
        if self._current_ship:
            with database.SessionLocal() as db:
                cond_service = ConditionService(db)
                pens = cond_service.get_pens_for_ship(self._current_ship.id)
                tanks = cond_service.get_tanks_for_ship(self._current_ship.id)
            self._update_condition_table(pens, tanks, pen_loadings, tank_volumes)
        
        QMessageBox.information(self, "Saved", "Condition saved.")
        
    def _update_condition_table(
        self,
        pens: list,
        tanks: list,
        pen_loadings: Dict[int, int],
        tank_volumes: Dict[int, float],
    ) -> None:
        """Helper to update the condition table widget (uses selected cargo type for dynamic AvW/Area; Cargo column dropdown from library)."""
        selected_cargo = next(
            (c for c in self._cargo_types if c.name == self._cargo_type_combo.currentText().strip()),
            None,
        )
        cargo_type_names = [c.name for c in self._cargo_types] if self._cargo_types else None
        self._condition_table.update_data(
            pens, tanks, pen_loadings, tank_volumes,
            cargo_type=selected_cargo,
            cargo_type_names=cargo_type_names,
        )
        
    # Public methods for toolbar access
    def compute_condition(self) -> bool:
        """
        Compute the current condition. Called from toolbar.
        
        Returns:
            True if computation succeeded, False otherwise
        """
        self._on_compute()
        return self._last_results is not None
        
    def save_current_condition(self) -> bool:
        """
        Save the current condition. Called from toolbar.
        
        Returns:
            True if save succeeded, False otherwise
        """
        if not self._current_voyage:
            QMessageBox.information(
                self, "Save", "Select a voyage first to save a condition."
            )
            return False
        self._on_save_condition()
        return self._current_condition is not None
        
    def new_condition(self) -> None:
        """Create a new condition. Called from toolbar."""
        self._current_condition = None
        self._cargo_type_combo.setCurrentText("")
        self._condition_name_edit.clear()
        if self._current_ship:
            self._set_current_ship(self._current_ship)
        
    def zoom_in_graphics(self) -> None:
        """Zoom in on graphics views."""
        # Zoom profile view
        profile_view = self._deck_profile_widget._profile_view
        profile_view.zoom_in()
        
        # Zoom deck view
        current_deck = self._deck_profile_widget.get_current_deck()
        deck_tab = self._deck_profile_widget._deck_tab_widgets.get(current_deck)
        if deck_tab:
            deck_tab._deck_view.zoom_in()
            
        # Zoom cross-section
        self._cross_section_widget._view.zoom_in()
        
    def zoom_out_graphics(self) -> None:
        """Zoom out on graphics views."""
        # Zoom profile view
        profile_view = self._deck_profile_widget._profile_view
        profile_view.zoom_out()
        
        # Zoom deck view
        current_deck = self._deck_profile_widget.get_current_deck()
        deck_tab = self._deck_profile_widget._deck_tab_widgets.get(current_deck)
        if deck_tab:
            deck_tab._deck_view.zoom_out()
            
        # Zoom cross-section
        self._cross_section_widget._view.zoom_out()
        
    def reset_zoom_graphics(self) -> None:
        """Reset zoom on graphics views."""
        # Reset profile view
        profile_view = self._deck_profile_widget._profile_view
        profile_view.fit_to_view()
        
        # Reset deck view
        current_deck = self._deck_profile_widget.get_current_deck()
        deck_tab = self._deck_profile_widget._deck_tab_widgets.get(current_deck)
        if deck_tab:
            deck_tab._deck_view.fit_to_view()
            
        # Reset cross-section
        self._cross_section_widget._view.fit_to_view()
        
    def _on_tank_table_changed(self, item: QTableWidgetItem) -> None:
        """Called when a tank table cell is edited."""
        if item.column() == 2:  # Fill % column
            try:
                value = float(item.text())
                if value < 0 or value > 100:
                    # Highlight invalid values
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor(200, 0, 0))
                else:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor(0, 0, 0))
            except ValueError:
                from PyQt6.QtGui import QColor
                item.setForeground(QColor(200, 0, 0))
                
    def _on_pen_table_changed(self, item: QTableWidgetItem) -> None:
        """Called when a pen table cell is edited."""
        if item.column() == 3:  # Head Count column
            try:
                value = int(float(item.text()))
                from PyQt6.QtGui import QColor
                if value < 0:
                    item.setForeground(QColor(200, 0, 0))
                else:
                    item.setForeground(QColor(0, 0, 0))
            except ValueError:
                from PyQt6.QtGui import QColor
                item.setForeground(QColor(200, 0, 0))


