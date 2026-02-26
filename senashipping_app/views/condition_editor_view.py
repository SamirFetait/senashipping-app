"""
Loading Condition editor view.

Single-ship mode: ship and voyage are fixed (configured once via Tools ΓåÆ Ship & data setup).
User enters cargo type; tanks/pens and ship particulars are static.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, List, Optional

# Project assets folder (sounding tables loaded automatically from here)
_assets_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


def _normalize_tank_name_for_match(name: str | None) -> str:
    """Normalize tank name for matching Excel sheet/tank column to ship tank.
    Collapses spaces, lowercases, removes periods so e.g. 'TK. 3' matches 'TK 3'.
    """
    if name is None:
        return ""
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(".", "")
    return s.strip()

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QFileDialog
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

from senashipping_app.models import Ship, Voyage, LoadingCondition, Tank, CargoType
from senashipping_app.repositories import database
from senashipping_app.repositories.ship_repository import ShipRepository
from senashipping_app.repositories.cargo_type_repository import CargoTypeRepository
from senashipping_app.services.condition_service import (
    ConditionService,
    ConditionValidationError,
    ConditionResults,
)
from senashipping_app.services.voyage_service import VoyageService, VoyageValidationError
from senashipping_app.services.sounding_import import parse_sounding_file_all_tanks
from senashipping_app.services.sounding import interpolate_cog_from_volume, interpolate_ullage_fsm_from_volume
from senashipping_app.utils.sorting import get_pen_sort_key, get_tank_sort_key
from senashipping_app.views.deck_profile_widget import DeckProfileWidget
from senashipping_app.views.results_panel import ResultsPanel
from senashipping_app.views.condition_table_widget import ConditionTableWidget
from senashipping_app.views.cargo_library_dialog import CargoLibraryDialog


class ConditionEditorView(QWidget):
    # Signal emitted when a condition has been computed:
    # args: results, ship, condition, voyage (or None for ad-hoc)
    condition_computed = pyqtSignal(object, object, object, object)
    # Emitted when user clicks Save Condition but there is no voyage (single-ship): main window should run File → Save
    save_condition_requested = pyqtSignal()

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
        self._condition_name_edit.setPlaceholderText("e.g. Ballast departure")
        self._condition_name_edit.setMinimumWidth(180)
        self._tank_table = QTableWidget(self)
        self._tank_table.setColumnCount(3)
        self._tank_table.setHorizontalHeaderLabels(
            ["Tank", "Capacity (m┬│)", "Fill %"]
        )
        self._tank_table.horizontalHeader().setStretchLastSection(True)
        self._tank_table.setAlternatingRowColors(True)
        self._tank_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tank_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        self._pen_table = QTableWidget(self)
        self._pen_table.setColumnCount(4)
        self._pen_table.setHorizontalHeaderLabels(
            ["Pen", "Deck", "Area (m┬▓)", "Head Count"]
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
        
        # Results panel (right side)
        self._results_panel = ResultsPanel(self)
        
        # Tabbed table widget (bottom)
        self._condition_table = ConditionTableWidget(self)
        
        # Store last computed results
        self._last_results: Optional[ConditionResults] = None

        # Sounding table cache: ship_id -> tank_id -> List[TankSoundingRow] (for LCG/VCG/TCG from volume)
        self._sounding_cache: Dict[int, Dict[int, list]] = {}
        # Ullage (m) and FSM (tonne.m) from Excel: ship_id -> tank_id -> (ullage_m, fsm_mt)
        self._ullage_fsm_cache: Dict[int, Dict[int, tuple]] = {}

        self._build_layout()
        self._connect_signals()
        self._save_condition_btn.setToolTip("Save condition to file (prompts for path if not saved yet)")
        # Connect deck profile widget to condition table for bidirectional synchronization
        self._condition_table.set_deck_profile_widget(self._deck_profile_widget)
        # Callback so condition table can show VCG/LCG/TCG from sounding table when weight/volume changes
        self._condition_table.set_tank_cog_callback(self._get_tank_cog_for_display)
        # Fallback when no sounding data: use tank default so VCG/LCG/TCG still update when weight changes
        self._condition_table.set_tank_default_cog_callback(self._get_tank_default_cog)
        # Callback so UII/Snd and FSt update from volume (interpolate from sounding or use Excel cache)
        self._condition_table.set_tank_ullage_fsm_callback(self._get_tank_ullage_fsm_for_display)
        # Initialize cargo types first to ensure "-- Blank --" is available
        self._refresh_cargo_types()
        self._load_ships()

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

        # Top controls – single-ship: ship read-only; condition name then cargo type
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Ship:", self))
        top.addWidget(self._ship_label, 1)
        self._ship_label.setStyleSheet("color: #555; padding: 4px;")
        top.addWidget(QLabel("Condition name:", self))
        top.addWidget(self._condition_name_edit, 1)
        top.addWidget(QLabel("Cargo type:", self))
        top.addWidget(self._cargo_type_combo, 2)
        top.addWidget(self._cargo_library_btn)
        top.addStretch()
        root.addLayout(top)
        # Hide ship/voyage/condition combos (still used internally for load_condition from file)
        self._ship_combo.hide()
        self._voyage_combo.hide()
        self._condition_combo.hide()

        # Main content area: left (profile+deck), right (results)
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._main_splitter.setChildrenCollapsible(False)
        
        # Left side: deck/profile widget
        self._main_splitter.addWidget(self._deck_profile_widget)
        
        # Right side: results panel
        self._main_splitter.addWidget(self._results_panel)
        
        # Set splitter sizes and constraints
        self._main_splitter.setSizes([600, 300])
        # Ensure results panel doesn't exceed its maximum width
        self._main_splitter.setStretchFactor(0, 1)  # Left side can stretch
        self._main_splitter.setStretchFactor(1, 0)  # Right side (results panel) cannot stretch
        root.addWidget(self._main_splitter, 2)

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
        self._cargo_type_combo.currentTextChanged.connect(self._on_cargo_type_changed)
        self._compute_btn.clicked.connect(self._on_compute)
        self._save_condition_btn.clicked.connect(self._on_save_condition)
        self._cargo_library_btn.clicked.connect(self._on_edit_cargo_library)
        self._deck_profile_widget.tank_selected.connect(self._on_tank_selected_from_view)

        # Connect table changes for real-time updates
        self._tank_table.itemChanged.connect(self._on_tank_table_changed)
        self._pen_table.itemChanged.connect(self._on_pen_table_changed)
    
    def _on_cargo_type_changed(self, cargo_text: str) -> None:
        """Handle cargo type combo change - update condition table."""
        if self._current_ship:
            with database.SessionLocal() as db:
                cond_svc = ConditionService(db)
                tanks = cond_svc.get_tanks_for_ship(self._current_ship.id)
                pens = cond_svc.get_pens_for_ship(self._current_ship.id)
            volumes = self._current_condition.tank_volumes_m3 if self._current_condition else {}
            pen_loads = getattr(self._current_condition, "pen_loadings", {}) or {} if self._current_condition else {}
            self._update_condition_table(pens, tanks, pen_loads, volumes)

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
            # Ensure cargo is set to "-- Blank --" before loading ship data
            if self._cargo_type_combo.count() > 0:
                self._cargo_type_combo.setCurrentIndex(0)  # "-- Blank --"
            self._load_voyages()
            self._set_current_ship(self._current_ship)
            self._save_condition_btn.setEnabled(True)
        else:
            self._ship_label.setText("— No ship — Add one via Tools → Ship & data setup")
            self._current_ship = None
            self._save_condition_btn.setEnabled(False)

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
            # Add "-- Blank --" as first option
            self._cargo_type_combo.addItem("-- Blank --", None)
            for ct in self._cargo_types:
                self._cargo_type_combo.addItem(ct.name, ct.id)
        # Restore previous selection if it exists, otherwise default to "-- Blank --"
        if current and current in [self._cargo_type_combo.itemText(i) for i in range(self._cargo_type_combo.count())]:
            self._cargo_type_combo.setCurrentText(current)
        else:
            self._cargo_type_combo.setCurrentIndex(0)  # Select "-- Blank --"

    def _set_cargo_type_text(self, text: str) -> None:
        """Set cargo type combo to the given name (e.g. when loading condition)."""
        self._cargo_type_combo.setCurrentText(text or "")

    def _on_edit_cargo_library(self) -> None:
        """Open Edit Cargo Library dialog; refresh combo and table dropdowns when closed."""
        dlg = CargoLibraryDialog(self)
        dlg.exec()
        self._refresh_cargo_types()
        # Update cargo types in condition table widget to sync all dropdowns
        if hasattr(self, '_condition_table') and hasattr(self._condition_table, 'update_cargo_types'):
            self._condition_table.update_cargo_types(self._cargo_types)

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
            self._voyage_combo.addItem(f"{v.name} ({v.departure_port}ΓåÆ{v.arrival_port})", v.id)
        self._voyage_combo.setCurrentIndex(0)
        # Ensure cargo is "-- Blank --" when loading voyages (first time opening)
        if self._cargo_type_combo.count() > 0:
            self._cargo_type_combo.setCurrentIndex(0)  # "-- Blank --"
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
        self._load_sounding_for_ship(ship)
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            tanks = cond_service.get_tanks_for_ship(ship.id)
            pens = cond_service.get_pens_for_ship(ship.id)

        self._current_pens = pens
        self._current_tanks = tanks

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
        # If no condition is selected, use empty pen_loadings and volumes to show blank values
        volumes = self._current_condition.tank_volumes_m3 if self._current_condition else {}
        pen_loads = getattr(self._current_condition, "pen_loadings", {}) or {} if self._current_condition else {}
        self._update_condition_table(pens, tanks, pen_loads, volumes)

    def _populate_tanks_table(
        self, tanks: List[Tank], volumes: Dict[int, float] | None = None
    ) -> None:
        volumes = volumes or {}
        self._tank_table.blockSignals(True)
        try:
            self._tank_table.setRowCount(0)
            # Sort tanks by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
            sorted_tanks = sorted(tanks, key=get_tank_sort_key)
            for tank in sorted_tanks:
                row = self._tank_table.rowCount()
                self._tank_table.insertRow(row)

                name_item = QTableWidgetItem(tank.name)
                name_item.setData(Qt.ItemDataRole.UserRole, tank.id)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only

                cap_item = QTableWidgetItem(f"{tank.capacity_m3:.2f}")
                cap_item.setFlags(cap_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only

                vol = volumes.get(tank.id or -1, 0.0)
                fill_pct = (vol / tank.capacity_m3 * 100.0) if tank.capacity_m3 > 0 else 0.0
                fill_item = QTableWidgetItem(f"{fill_pct:.1f}")
                # Fill % is editable (user can change loading)

                self._tank_table.setItem(row, 0, name_item)
                self._tank_table.setItem(row, 1, cap_item)
                self._tank_table.setItem(row, 2, fill_item)
        finally:
            self._tank_table.blockSignals(False)

    def _populate_pens_table(
        self, pens: list, pen_loadings: Dict[int, int] | None = None
    ) -> None:
        loadings = pen_loadings or {}
        self._pen_table.setRowCount(0)
        # Sort pens by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
        sorted_pens = sorted(pens, key=get_pen_sort_key)
        for pen in sorted_pens:
            row = self._pen_table.rowCount()
            self._pen_table.insertRow(row)
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
            self._pen_table.setItem(row, 0, name_item)
            
            deck_item = QTableWidgetItem(pen.deck)
            deck_item.setFlags(deck_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
            self._pen_table.setItem(row, 1, deck_item)
            
            area_item = QTableWidgetItem(f"{pen.area_m2:.2f}")
            area_item.setFlags(area_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
            self._pen_table.setItem(row, 2, area_item)
            
            heads = loadings.get(pen.id or -1, 0)
            head_item = QTableWidgetItem(str(heads))
            # Head Count is editable (user can change loading)
            self._pen_table.setItem(row, 3, head_item)

    def _tank_volumes_from_simple_table(self) -> Dict[int, float]:
        """Build tank_id -> volume from simple tank table (Fill % and capacity)."""
        tank_by_id = {t.id: t for t in self._current_tanks} if self._current_tanks else {}
        out: Dict[int, float] = {}
        for row in range(self._tank_table.rowCount()):
            name_item = self._tank_table.item(row, 0)
            fill_item = self._tank_table.item(row, 2)
            if not name_item or not fill_item:
                continue
            tank_id = name_item.data(Qt.ItemDataRole.UserRole)
            if tank_id is None:
                continue
            try:
                fill_pct = float((fill_item.text() or "0").strip())
            except (TypeError, ValueError):
                fill_pct = 0.0
            fill_pct = max(0.0, min(100.0, fill_pct))
            tank = tank_by_id.get(int(tank_id))
            if tank and tank.capacity_m3 > 0:
                out[int(tank_id)] = tank.capacity_m3 * (fill_pct / 100.0)
            else:
                out[int(tank_id)] = 0.0
        return out

    def _pen_loadings_from_pen_table(self) -> Dict[int, int]:
        """Build pen_id -> head count from pen table."""
        out: Dict[int, int] = {}
        for row in range(self._pen_table.rowCount()):
            name_item = self._pen_table.item(row, 0)
            head_item = self._pen_table.item(row, 3)
            if not name_item or not head_item:
                continue
            pen_id = name_item.data(Qt.ItemDataRole.UserRole)
            if pen_id is None:
                continue
            try:
                heads = int(float((head_item.text() or "0").strip()))
                out[int(pen_id)] = max(0, heads)
            except (TypeError, ValueError):
                out[int(pen_id)] = 0
        return out

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
        self._load_sounding_for_ship(ship)
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
            # When no voyage selected, ensure cargo is "-- Blank --" to show blank values
            if self._cargo_type_combo.count() > 0:
                self._cargo_type_combo.setCurrentIndex(0)  # "-- Blank --"
        elif index - 1 < len(self._voyages):
            self._current_voyage = self._voyages[index - 1]
            self._current_condition = None
        self._load_conditions()
        self._save_condition_btn.setEnabled(True)
        if self._current_ship:
            self._set_current_ship(self._current_ship)

    def _on_condition_changed(self, index: int) -> None:
        if index <= 0:
            self._current_condition = None
            self._condition_name_edit.clear()
            # When selecting "-- New --", ensure cargo is "-- Blank --" to show blank values
            if self._cargo_type_combo.count() > 0:
                self._cargo_type_combo.setCurrentIndex(0)  # "-- Blank --"
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

        # Reset waterline before running a new computation so it never shows stale drafts
        self._deck_profile_widget.clear_waterline()

        # Use condition name from field; fall back to cargo type when empty (saved on Compute and used in PDF/Excel)
        condition_name = self._condition_name_edit.text().strip() or self._cargo_type_combo.currentText().strip() or "Condition"
        if not self._condition_name_edit.text().strip():
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

        # Build volumes from simple table (fill % * capacity) first
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

        # Overlay volumes from condition table (Weight/Dens → Volume) so real volume drives CG
        ct_vols = self._condition_table.get_tank_volumes_from_tables()
        for tid, vol in ct_vols.items():
            tank_volumes[tid] = vol

        # Pen loadings: use condition table (Livestock-DK1..DK8) as source of truth so livestock decks affect calculations
        ct_pen_loads = self._condition_table.get_pen_loadings_from_tables()
        if ct_pen_loads:
            pen_loadings = {pid: h for pid, h in ct_pen_loads.items() if h > 0}
        else:
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
        tank_cog_override = self._build_tank_cog_override(tank_volumes)
        tank_fsm_map = self._build_tank_fsm_map(tank_volumes)
        try:
            results: ConditionResults = cond_service.compute(
                self._current_ship,
                condition,
                tank_volumes,
                cargo_type=selected_cargo,
                tank_cog_override=tank_cog_override if tank_cog_override else None,
                tank_fsm_mt=tank_fsm_map if tank_fsm_map else None,
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
        
        # Step 4 — Connect UI to engine: redraw waterline from solved draft so the drawing is meaningful
        L = getattr(self._current_ship, "length_overall_m", 0) or 0
        D = getattr(self._current_ship, "depth_m", 0) or 0
        if L > 0:
            self._deck_profile_widget.update_waterline(
                results.draft_m,
                getattr(results, "draft_aft_m", results.draft_m + results.trim_m / 2),
                getattr(results, "draft_fwd_m", results.draft_m - results.trim_m / 2),
                ship_length=L,
                ship_depth=D if D > 0 else None,
                trim_m=results.trim_m,
            )
        
        # Update condition table with current data
        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            pens = cond_service.get_pens_for_ship(self._current_ship.id)
            tanks = cond_service.get_tanks_for_ship(self._current_ship.id)
        self._update_condition_table(pens, tanks, pen_loadings, tank_volumes)
        self._populate_tanks_table(tanks, tank_volumes)
        self.condition_computed.emit(results, self._current_ship, condition, voyage)
        validation = getattr(results, "validation", None)
        if validation and getattr(validation, "has_errors", False):
            # Use non-blocking status message instead of blocking dialog
            # Try to find parent MainWindow to show status message
            parent = self.parent()
            while parent and not hasattr(parent, '_status_bar'):
                parent = parent.parent()
            if parent and hasattr(parent, '_status_bar'):
                parent._status_bar.showMessage("Computation completed - FAILED: Check Results tab for details", 5000)
            else:
                # Fallback to non-modal message box if no status bar found
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Computed – FAILED")
                msg.setText("Condition computed but fails validation. Check Results tab.")
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.setModal(False)
                msg.show()
        else:
            # Use non-blocking status message instead of blocking dialog
            parent = self.parent()
            while parent and not hasattr(parent, '_status_bar'):
                parent = parent.parent()
            if parent and hasattr(parent, '_status_bar'):
                parent._status_bar.showMessage("Computation completed successfully", 3000)
            else:
                # Fallback to non-modal message box if no status bar found
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setWindowTitle("Computed")
                msg.setText("Condition results computed.")
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.setModal(False)
                msg.show()

    def _on_save_condition(self) -> None:
        if not self._current_ship:
            QMessageBox.information(
                self, "Save", "Select a ship first (Tools → Ship & data setup)."
            )
            return
        # If we have a voyage in the DB, save to voyage; otherwise trigger file save from main window
        if not self._current_voyage or not self._current_voyage.id:
            self.save_condition_requested.emit()
            return
        if database.SessionLocal is None:
            return

        # Build condition from current form (same as compute but we need volumes)
        condition_name = self._condition_name_edit.text().strip() or self._cargo_type_combo.currentText().strip() or "Condition"
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

        ct_vols = self._condition_table.get_tank_volumes_from_tables()
        for tid, vol in ct_vols.items():
            tank_volumes[tid] = vol

        # Pen loadings: use condition table (Livestock-DK1..DK8) so livestock decks affect saved condition
        ct_pen_loads = self._condition_table.get_pen_loadings_from_tables()
        if ct_pen_loads:
            pen_loadings = {pid: h for pid, h in ct_pen_loads.items() if h > 0}
        else:
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
            tank_cog_override = self._build_tank_cog_override(tank_volumes)
            tank_fsm_map = self._build_tank_fsm_map(tank_volumes)
            try:
                results = cond_svc.compute(
                    self._current_ship,
                    condition,
                    tank_volumes,
                    cargo_type=selected_cargo,
                    tank_cog_override=tank_cog_override if tank_cog_override else None,
                    tank_fsm_mt=tank_fsm_map if tank_fsm_map else None,
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
            self._populate_tanks_table(tanks, tank_volumes)
        QMessageBox.information(self, "Saved", "Condition saved.")
        
    def _update_condition_table(
        self,
        pens: list,
        tanks: list,
        pen_loadings: Dict[int, int],
        tank_volumes: Dict[int, float],
    ) -> None:
        """Helper to update the condition table widget (uses selected cargo type for dynamic AvW/Area; Cargo column dropdown from library)."""
        self._current_pens = pens
        self._current_tanks = tanks
        current_cargo_text = self._cargo_type_combo.currentText().strip()
        # Default to "-- Blank --" if no cargo is selected or combo is empty
        if not current_cargo_text or current_cargo_text == "":
            current_cargo_text = "-- Blank --"
        
        selected_cargo = next(
            (c for c in self._cargo_types if c.name == current_cargo_text),
            None,
        )
        # If selected cargo is not found or is "-- Blank --", use None for cargo_type
        if current_cargo_text == "-- Blank --" or selected_cargo is None:
            selected_cargo = None
            default_cargo_name = "-- Blank --"
        else:
            default_cargo_name = current_cargo_text
        
        cargo_type_names = [c.name for c in self._cargo_types] if self._cargo_types else None
        tank_ullage_fsm = {}
        if self._current_ship and self._current_ship.id and self._current_ship.id in self._ullage_fsm_cache:
            tank_ullage_fsm = self._ullage_fsm_cache[self._current_ship.id]
        self._condition_table.update_data(
            pens, tanks, pen_loadings, tank_volumes,
            cargo_type=selected_cargo,
            cargo_type_names=cargo_type_names,
            cargo_types=self._cargo_types,
            ship_id=self._current_ship.id if self._current_ship else None,
            default_cargo_name=default_cargo_name,
            tank_ullage_fsm=tank_ullage_fsm,
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
        """Zoom in on profile and deck views."""
        self._deck_profile_widget._profile_view.zoom_in()
        current_deck = self._deck_profile_widget.get_current_deck()
        deck_tab = self._deck_profile_widget._deck_tab_widgets.get(current_deck)
        if deck_tab:
            deck_tab._deck_view.zoom_in()

    def zoom_out_graphics(self) -> None:
        """Zoom out on profile and deck views."""
        self._deck_profile_widget._profile_view.zoom_out()
        current_deck = self._deck_profile_widget.get_current_deck()
        deck_tab = self._deck_profile_widget._deck_tab_widgets.get(current_deck)
        if deck_tab:
            deck_tab._deck_view.zoom_out()

    def reset_zoom_graphics(self) -> None:
        """Reset zoom on profile and deck views (fit to section)."""
        self._deck_profile_widget._profile_view.fit_to_view()
        current_deck = self._deck_profile_widget.get_current_deck()
        deck_tab = self._deck_profile_widget._deck_tab_widgets.get(current_deck)
        if deck_tab:
            deck_tab._deck_view.fit_to_view()

    def set_results_panel_visible(self, visible: bool) -> None:
        """
        Show or hide the right-side results panel.

        Exposed so the main window View → Show Results Bar menu item can
        toggle this panel without reaching into private attributes.
        """
        self._results_panel.setVisible(visible)

    def set_default_view_layout(self) -> None:
        """
        Reset the Loading Condition layout to a sensible default.

        Used by View → Default view model so the main window can restore
        the usual splitter sizes and make key panels visible.
        """
        # Restore splitter balance
        if hasattr(self, "_main_splitter"):
            self._main_splitter.setOrientation(Qt.Orientation.Horizontal)
            self._main_splitter.setSizes([600, 300])
        # Ensure core panels are visible
        self._results_panel.setVisible(True)
        self._condition_table.setVisible(True)

    # ------------------------------------------------------------------
    # Public helpers for Edit menu (invoked from MainWindow)
    # ------------------------------------------------------------------

    def edit_selected_item(self) -> None:
        """Begin editing the currently selected cell in the active condition table tab."""
        self._condition_table.edit_selected_item()

    def delete_selected_items(self) -> None:
        """
        Clear load for selected items.

        On livestock tabs this zeros head counts; on tank tabs this empties
        the corresponding tanks (0% full).
        """
        self._condition_table.clear_selected_items()

    def select_all_items(self) -> None:
        """Select all rows in the active condition table tab."""
        self._condition_table.select_all_items()

    def clear_selection(self) -> None:
        """Clear selection in the active condition table tab."""
        self._condition_table.clear_selection()

    def empty_spaces(self) -> None:
        """Empty selected spaces/tanks in the current tank tab (0% full)."""
        self._condition_table.set_selected_tanks_empty()

    def fill_spaces(self) -> None:
        """Fill selected spaces/tanks in the current tank tab to 100%."""
        self._condition_table.set_selected_tanks_full()

    def fill_spaces_to(self, level_pct: float) -> None:
        """Fill selected spaces/tanks in the current tank tab to a specific percentage."""
        self._condition_table.set_selected_tanks_fill_to(level_pct)

    def search_item(self) -> None:
        """
        Prompt for a pen or tank name and select the first matching row
        in the currently active condition table tab.
        """
        from PyQt6.QtWidgets import QInputDialog

        term, ok = QInputDialog.getText(
            self,
            "Search item",
            "Enter pen or tank name (partial match):",
        )
        if not ok or not term.strip():
            return
        found = self._condition_table.search_by_name(term.strip())
        if not found:
            QMessageBox.information(self, "Search", "No matching item found in the current tab.")

    def add_new_item(self) -> None:
        """
        Trigger the same behaviour as clicking '+' in the condition table.

        In this build, that means opening Tools → Ship & data setup so the
        user can define new tanks or pens, which will then appear here.
        """
        self._condition_table.add_requested.emit()

    def _load_sounding_for_ship(self, ship: Optional[Ship]) -> None:
        """Load sounding table from project assets/ for this ship (no user import)."""
        if not ship or not ship.id:
            return
        # Try "SOUNDING <ship name>.xlsx" then any SOUNDING*.xlsx in assets/
        safe_name = (ship.name or "").strip()
        path = _assets_DIR / f"SOUNDING {safe_name}.xlsx"
        if not path.exists():
            try:
                candidates = list(_assets_DIR.glob("SOUNDING*.xlsx"))
                if not candidates:
                    return
                path = candidates[0]
            except Exception:
                return
        try:
            by_name, ullage_fsm_by_name = parse_sounding_file_all_tanks(path)
        except Exception:
            return
        if not by_name and not ullage_fsm_by_name:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            tanks = cond_service.get_tanks_for_ship(ship.id)
        ship_id = ship.id
        if ship_id not in self._sounding_cache:
            self._sounding_cache[ship_id] = {}
        if ship_id not in self._ullage_fsm_cache:
            self._ullage_fsm_cache[ship_id] = {}
        for key, rows in by_name.items():
            key_norm = _normalize_tank_name_for_match(key)
            tank = next(
                (t for t in tanks if _normalize_tank_name_for_match(t.name) == key_norm),
                None,
            )
            if tank and tank.id is not None:
                self._sounding_cache[ship_id][tank.id] = rows
                if key in ullage_fsm_by_name:
                    self._ullage_fsm_cache[ship_id][int(tank.id)] = ullage_fsm_by_name[key]
        for key in ullage_fsm_by_name:
            if key in by_name:
                continue
            key_norm = _normalize_tank_name_for_match(key)
            tank = next(
                (t for t in tanks if _normalize_tank_name_for_match(t.name) == key_norm),
                None,
            )
            if tank and tank.id is not None:
                self._ullage_fsm_cache[ship_id][int(tank.id)] = ullage_fsm_by_name[key]

    def _get_tank_cog_for_display(self, tank_id: int, volume_m3: float) -> Optional[tuple]:
        """Return (vcg_m, lcg_m, tcg_m) from sounding table for display, or None if no sounding data."""
        if not self._current_ship or not self._current_ship.id:
            return None
        ship_cache = self._sounding_cache.get(self._current_ship.id)
        if not ship_cache:
            return None
        rows = ship_cache.get(tank_id)
        if not rows:
            return None
        cog = interpolate_cog_from_volume(volume_m3, rows)
        if cog is None:
            return None
        vcg, lcg, tcg = cog
        # Guard against NaN from bad sounding data so UI never shows "nan"
        vcg = 0.0 if math.isnan(vcg) else vcg
        lcg = 0.0 if math.isnan(lcg) else lcg
        tcg = 0.0 if math.isnan(tcg) else tcg
        return (vcg, lcg, tcg)

    def _get_tank_ullage_fsm_for_display(self, tank_id: int, volume_m3: float) -> tuple:
        """Return (ullage_m, fsm_mt) from sounding table (interpolated by volume) or Excel cache, so UII/Snd and FSt update like VCG/LCG/TCG."""
        out: tuple = (None, None)
        if self._current_ship and self._current_ship.id:
            ship_cache = self._sounding_cache.get(self._current_ship.id)
            if ship_cache:
                rows = ship_cache.get(tank_id)
                if rows:
                    uf = interpolate_ullage_fsm_from_volume(volume_m3, rows)
                    if uf is not None:
                        ull, fsm = uf
                        ull = 0.0 if math.isnan(ull) else ull
                        fsm = 0.0 if math.isnan(fsm) else fsm
                        return (ull, fsm)
            # Fallback: static Ullage/FSM from Excel (first row or summary)
            ullage_cache = self._ullage_fsm_cache.get(self._current_ship.id, {})
            if tank_id in ullage_cache:
                uf = ullage_cache[tank_id]
                if uf and (uf[0] is not None or (len(uf) > 1 and uf[1] is not None)):
                    return (uf[0] or 0.0, (uf[1] if len(uf) > 1 else 0.0) or 0.0)
        return out

    def _get_tank_default_cog(self, tank_id: int) -> tuple:
        """Return (vcg_m, lcg_m, tcg_m) from tank defaults when no sounding data. Used so VCG/LCG/TCG still update when weight changes."""
        tank = next((t for t in (self._current_tanks or []) if (t.id or -1) == tank_id), None)
        if tank is None:
            return (0.0, 0.0, 0.0)
        vcg = getattr(tank, "kg_m", 0.0)
        lcg = getattr(tank, "lcg_m", 0.0)
        tcg = getattr(tank, "tcg_m", 0.0)
        # Coerce NaN/None (e.g. SILO with unset kg_m or NULL from DB) so UI never shows "nan"
        def _safe_float(x) -> float:
            if x is None:
                return 0.0
            try:
                return 0.0 if math.isnan(float(x)) else float(x)
            except (TypeError, ValueError):
                return 0.0
        return (_safe_float(vcg), _safe_float(lcg), _safe_float(tcg))

    def _build_tank_fsm_map(self, tank_volumes: Dict[int, float]) -> Dict[int, float]:
        """
        Build tank_id -> FSM (tonne·m) for the current volumes using sounding tables
        or cached Ullage/FSM data. Used to compute real free surface correction.
        """
        fsm_map: Dict[int, float] = {}
        if not self._current_ship or not self._current_ship.id:
            return fsm_map
        for tank_id, vol in tank_volumes.items():
            try:
                ull, fsm = self._get_tank_ullage_fsm_for_display(tank_id, vol)
            except Exception:
                ull, fsm = (None, None)
            if fsm is not None:
                try:
                    fsm_val = float(fsm)
                except (TypeError, ValueError):
                    fsm_val = 0.0
                if fsm_val > 0.0:
                    fsm_map[int(tank_id)] = fsm_val
        return fsm_map

    def _build_tank_cog_override(self, tank_volumes: Dict[int, float]) -> Dict[int, tuple]:
        """Build tank_id -> (vcg_m, lcg_m, tcg_m) from sounding cache and tank_volumes."""
        override: Dict[int, tuple] = {}
        if not self._current_ship or not self._current_ship.id:
            return override
        ship_cache = self._sounding_cache.get(self._current_ship.id)
        if not ship_cache:
            return override
        for tank_id, vol in tank_volumes.items():
            rows = ship_cache.get(tank_id)
            if not rows:
                continue
            cog = interpolate_cog_from_volume(vol, rows)
            if cog is not None:
                vcg, lcg, tcg = cog
                override[tank_id] = (
                    0.0 if (vcg is None or (isinstance(vcg, float) and math.isnan(vcg))) else float(vcg),
                    0.0 if (lcg is None or (isinstance(lcg, float) and math.isnan(lcg))) else float(lcg),
                    0.0 if (tcg is None or (isinstance(tcg, float) and math.isnan(tcg))) else float(tcg),
                )
        return override

    def import_sounding_table(self) -> None:
        """Import tank sounding tables from Excel; match by tank name and cache for current ship."""
        if not self._current_ship or not self._current_ship.id:
            QMessageBox.information(
                self, "Import sounding", "Select a ship first."
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import sounding table",
            str(Path.home()),
            "Excel Files (*.xlsx *.xls);;CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            by_name, ullage_fsm_by_name = parse_sounding_file_all_tanks(path)
        except Exception as e:
            QMessageBox.warning(
                self, "Import sounding", f"Could not parse file: {e}"
            )
            return
        if not by_name and not ullage_fsm_by_name:
            QMessageBox.information(
                self, "Import sounding", "No valid sounding tables or Ullage/FSM data found in the file."
            )
            return
        with database.SessionLocal() as db:
            cond_service = ConditionService(db)
            tanks = cond_service.get_tanks_for_ship(self._current_ship.id)
        ship_id = self._current_ship.id
        if ship_id not in self._sounding_cache:
            self._sounding_cache[ship_id] = {}
        if ship_id not in self._ullage_fsm_cache:
            self._ullage_fsm_cache[ship_id] = {}
        matched = 0
        matched_ullage = 0
        unmatched: List[str] = []
        for key, rows in by_name.items():
            key_norm = _normalize_tank_name_for_match(key)
            tank = next(
                (t for t in tanks if _normalize_tank_name_for_match(t.name) == key_norm),
                None,
            )
            if tank and tank.id is not None:
                self._sounding_cache[ship_id][tank.id] = rows
                if key in ullage_fsm_by_name:
                    self._ullage_fsm_cache[ship_id][int(tank.id)] = ullage_fsm_by_name[key]
                    matched_ullage += 1
                matched += 1
            elif key_norm:
                unmatched.append(key)
        for key in ullage_fsm_by_name:
            if key in by_name:
                continue
            key_norm = _normalize_tank_name_for_match(key)
            tank = next(
                (t for t in tanks if _normalize_tank_name_for_match(t.name) == key_norm),
                None,
            )
            if tank and tank.id is not None:
                self._ullage_fsm_cache[ship_id][int(tank.id)] = ullage_fsm_by_name[key]
                matched_ullage += 1
            elif key_norm:
                unmatched.append(key)
        msg = f"Imported soundings for {matched} tank(s)."
        if matched_ullage > 0:
            msg += f" Ullage/FSM for {matched_ullage} tank(s)."
        if unmatched:
            msg += f" Not matched: {', '.join(unmatched[:10])}"
            if len(unmatched) > 10:
                msg += f" ... and {len(unmatched) - 10} more"
        QMessageBox.information(self, "Import sounding", msg)
        if matched > 0 or matched_ullage > 0:
            self._update_condition_table(
                self._current_pens or [],
                self._current_tanks or [],
                getattr(self._current_condition, "pen_loadings", {}) or {},
                getattr(self._current_condition, "tank_volumes_m3", {}) or {},
            )

    def _on_tank_table_changed(self, item: QTableWidgetItem) -> None:
        """Called when a tank table cell is edited. When Fill % changes, refresh condition table so Volume/Weight/VCG/LCG/TCG update immediately."""
        if item.column() == 2:  # Fill % column
            try:
                value = float(item.text())
                if value < 0 or value > 100:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor(200, 0, 0))
                else:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor(0, 0, 0))
            except ValueError:
                from PyQt6.QtGui import QColor
                item.setForeground(QColor(200, 0, 0))
            # Refresh condition table immediately so Volume, Weight, VCG/LCG/TCG update from new volumes
            if self._current_ship and self._current_tanks:
                tank_volumes = self._tank_volumes_from_simple_table()
                pen_loads = self._pen_loadings_from_pen_table()
                self._update_condition_table(self._current_pens, self._current_tanks, pen_loads, tank_volumes)
                
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


