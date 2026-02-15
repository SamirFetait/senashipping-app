"""
Ship Manager view.

Provides simple CRUD for ships and their tanks.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QPushButton,
    QLabel,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QMessageBox,
)

from ..models import Ship, Tank, TankType, LivestockPen
from ..repositories import database
from ..repositories.tank_repository import TankRepository
from ..repositories.livestock_pen_repository import LivestockPenRepository
from ..services.ship_service import ShipService, ShipValidationError
from .condition_table_widget import TANK_CATEGORY_NAMES, TANK_CATEGORY_TYPES


class ShipManagerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        if database.SessionLocal is None:
            raise RuntimeError("Database not initialized")

        self._current_ship: Optional[Ship] = None
        self._ships_list = QListWidget(self)

        # Ship form
        self._name_edit = QLineEdit(self)
        self._imo_edit = QLineEdit(self)
        self._flag_edit = QLineEdit(self)
        self._loa_spin = QDoubleSpinBox(self)
        self._loa_spin.setRange(0.0, 1000.0)
        self._breadth_spin = QDoubleSpinBox(self)
        self._breadth_spin.setRange(0.0, 200.0)
        self._depth_spin = QDoubleSpinBox(self)
        self._depth_spin.setRange(0.0, 200.0)
        self._design_draft_spin = QDoubleSpinBox(self)
        self._design_draft_spin.setRange(0.0, 50.0)
        self._design_draft_spin.setDecimals(2)

        self._ship_new_btn = QPushButton("New Ship", self)
        self._ship_save_btn = QPushButton("Save Ship", self)
        self._ship_delete_btn = QPushButton("Delete Ship", self)

        # Tanks table: Name, Storing (dropdown), Capacity (m³), Long. pos
        self._tanks_table = QTableWidget(self)
        self._tanks_table.setColumnCount(4)
        self._tanks_table.setHorizontalHeaderLabels(
            ["Name", "Storing", "Capacity (m³)", "Long. pos"]
        )
        self._tanks_table.horizontalHeader().setStretchLastSection(False)
        self._tanks_table.setColumnWidth(0, 180)
        self._tanks_table.setColumnWidth(1, 140)

        self._tank_add_btn = QPushButton("Add Tank", self)
        self._tank_delete_btn = QPushButton("Delete Selected Tank", self)
        self._tank_save_btn = QPushButton("Save Tanks", self)

        # Livestock pens table – same columns as loading condition (Livestock-DK tabs)
        self._pens_table = QTableWidget(self)
        self._pens_table.setColumnCount(14)
        self._pens_table.setHorizontalHeaderLabels([
            "Name",
            "Deck",
            "# Head",
            "Head %Full",
            "Head Capacity",
            "Used Area m2",
            "Total Area m2",
            "Area/Head",
            "AvW/Head MT",
            "Weight MT",
            "VCG m-BL",
            "LCG m-[FR]",
            "TCG m-CL",
            "LS Moment m-MT",
        ])
        self._pens_table.horizontalHeader().setStretchLastSection(True)
        self._pen_add_btn = QPushButton("Add Pen", self)
        self._pen_delete_btn = QPushButton("Delete Selected Pen", self)
        self._pen_save_btn = QPushButton("Save Pens", self)

        self._build_layout()
        self._connect_signals()
        self._load_ships()

    # Layout -----------------------------------------------------------------
    def _build_layout(self) -> None:
        root = QHBoxLayout(self)

        # Left: ship list
        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("Ships", self))
        left_box.addWidget(self._ships_list)
        root.addLayout(left_box, 1)

        # Right: ship form + tanks
        right_box = QVBoxLayout()

        ship_group = QGroupBox("Ship Details", self)
        ship_form = QFormLayout(ship_group)
        ship_form.addRow("Name:", self._name_edit)
        ship_form.addRow("IMO:", self._imo_edit)
        ship_form.addRow("Flag:", self._flag_edit)
        ship_form.addRow("Length OA (m):", self._loa_spin)
        ship_form.addRow("Breadth (m):", self._breadth_spin)
        ship_form.addRow("Depth (m):", self._depth_spin)
        ship_form.addRow("Design Draft (m):", self._design_draft_spin)

        ship_btns = QHBoxLayout()
        ship_btns.addWidget(self._ship_new_btn)
        ship_btns.addWidget(self._ship_save_btn)
        ship_btns.addWidget(self._ship_delete_btn)
        ship_form.addRow(ship_btns)

        right_box.addWidget(ship_group)

        tank_group = QGroupBox("Tanks for Selected Ship", self)
        tank_layout = QVBoxLayout(tank_group)
        tank_layout.addWidget(self._tanks_table)

        tank_btns = QHBoxLayout()
        tank_btns.addWidget(self._tank_add_btn)
        tank_btns.addWidget(self._tank_save_btn)
        tank_btns.addWidget(self._tank_delete_btn)
        tank_layout.addLayout(tank_btns)

        right_box.addWidget(tank_group, 1)

        pen_group = QGroupBox("Livestock Pens for Selected Ship", self)
        pen_layout = QVBoxLayout(pen_group)
        pen_layout.addWidget(self._pens_table)
        pen_btns = QHBoxLayout()
        pen_btns.addWidget(self._pen_add_btn)
        pen_btns.addWidget(self._pen_save_btn)
        pen_btns.addWidget(self._pen_delete_btn)
        pen_layout.addLayout(pen_btns)
        right_box.addWidget(pen_group, 1)

        root.addLayout(right_box, 2)
    


    def _connect_signals(self) -> None:
        self._ships_list.currentItemChanged.connect(
            self._on_ship_selection_changed
        )
        self._ship_new_btn.clicked.connect(self._on_new_ship)
        self._ship_save_btn.clicked.connect(self._on_save_ship)
        self._ship_delete_btn.clicked.connect(self._on_delete_ship)

        self._tank_add_btn.clicked.connect(self._on_add_tank_row)
        self._tank_delete_btn.clicked.connect(self._on_delete_selected_tank_row)
        self._tank_save_btn.clicked.connect(self._on_save_tanks)
        self._pen_add_btn.clicked.connect(self._on_add_pen_row)
        self._pen_delete_btn.clicked.connect(self._on_delete_selected_pen_row)
        self._pen_save_btn.clicked.connect(self._on_save_pens)

    # Data loading -----------------------------------------------------------
    def _load_ships(self) -> None:
        self._ships_list.clear()
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            service = ShipService(db)
            for ship in service.list_ships():
                item = QListWidgetItem(ship.name)
                item.setData(Qt.ItemDataRole.UserRole, ship.id)
                self._ships_list.addItem(item)

    def _load_ship(self, ship_id: int) -> None:
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            ship_service = ShipService(db)
            tank_repo = TankRepository(db)
            ship = ship_service.get_ship(ship_id)
            if ship is None:
                return
            self._current_ship = ship

            self._name_edit.setText(ship.name)
            self._imo_edit.setText(ship.imo_number)
            self._flag_edit.setText(ship.flag)
            self._loa_spin.setValue(ship.length_overall_m)
            self._breadth_spin.setValue(ship.breadth_m)
            self._depth_spin.setValue(ship.depth_m)
            self._design_draft_spin.setValue(ship.design_draft_m)

            tanks = tank_repo.list_for_ship(ship.id)
            pens = LivestockPenRepository(db).list_for_ship(ship.id)
            self._populate_tanks_table(tanks)
            self._populate_pens_table(pens)

    def _populate_pens_table(self, pens: list[LivestockPen]) -> None:
        """Fill pens table with same column layout as loading condition (Livestock-DK)."""
        self._pens_table.setRowCount(0)
        for pen in pens:
            row = self._pens_table.rowCount()
            self._pens_table.insertRow(row)
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            self._pens_table.setItem(row, 0, name_item)
            self._pens_table.setItem(row, 1, QTableWidgetItem(pen.deck))
            self._pens_table.setItem(row, 2, QTableWidgetItem("0"))       # # Head (set in condition)
            self._pens_table.setItem(row, 3, QTableWidgetItem("0.0"))   # Head %Full
            self._pens_table.setItem(row, 4, QTableWidgetItem(str(pen.capacity_head)))
            self._pens_table.setItem(row, 5, QTableWidgetItem("0.00"))   # Used Area (from condition)
            self._pens_table.setItem(row, 6, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            self._pens_table.setItem(row, 7, QTableWidgetItem(""))       # Area/Head
            self._pens_table.setItem(row, 8, QTableWidgetItem("0.50"))   # AvW/Head MT
            self._pens_table.setItem(row, 9, QTableWidgetItem("0.00"))   # Weight MT
            self._pens_table.setItem(row, 10, QTableWidgetItem(f"{pen.vcg_m:.3f}"))
            self._pens_table.setItem(row, 11, QTableWidgetItem(f"{pen.lcg_m:.3f}"))
            self._pens_table.setItem(row, 12, QTableWidgetItem(f"{pen.tcg_m:.3f}"))
            self._pens_table.setItem(row, 13, QTableWidgetItem(""))      # LS Moment

    def _populate_tanks_table(self, tanks: list[Tank]) -> None:
        self._tanks_table.setRowCount(0)
        for tank in tanks:
            row = self._tanks_table.rowCount()
            self._tanks_table.insertRow(row)

            name_item = QTableWidgetItem(tank.name)
            name_item.setData(Qt.ItemDataRole.UserRole, tank.id)
            self._tanks_table.setItem(row, 0, name_item)

            category = getattr(tank, "category", None) or "Misc. Tanks"
            if category not in TANK_CATEGORY_NAMES:
                category = "Misc. Tanks"
            combo = QComboBox(self)
            combo.addItems(TANK_CATEGORY_NAMES)
            combo.setCurrentText(category)
            self._tanks_table.setCellWidget(row, 1, combo)

            self._tanks_table.setItem(
                row, 2, QTableWidgetItem(f"{tank.capacity_m3:.2f}")
            )
            self._tanks_table.setItem(
                row, 3, QTableWidgetItem(f"{tank.longitudinal_pos:.3f}")
            )

    # Event handlers ---------------------------------------------------------
    def _on_ship_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self._current_ship = None
            self._clear_ship_form()
            self._tanks_table.setRowCount(0)
            self._pens_table.setRowCount(0)
            return
        ship_id = current.data(Qt.ItemDataRole.UserRole)
        if ship_id is not None:
            self._load_ship(int(ship_id))

    def _on_new_ship(self) -> None:
        self._current_ship = None
        self._clear_ship_form()
        self._tanks_table.setRowCount(0)
        self._pens_table.setRowCount(0)
        self._ships_list.clearSelection()

    def _on_save_ship(self) -> None:
        if database.SessionLocal is None:
            QMessageBox.critical(self, "Error", "Database not initialized.")
            return

        with database.SessionLocal() as db:
            service = ShipService(db)

            ship = self._current_ship or Ship()
            ship.name = self._name_edit.text().strip()
            ship.imo_number = self._imo_edit.text().strip()
            ship.flag = self._flag_edit.text().strip()
            ship.length_overall_m = float(self._loa_spin.value())
            ship.breadth_m = float(self._breadth_spin.value())
            ship.depth_m = float(self._depth_spin.value())
            ship.design_draft_m = float(self._design_draft_spin.value())

            try:
                ship = service.save_ship(ship)
            except ShipValidationError as exc:
                QMessageBox.warning(self, "Validation", str(exc))
                return

            self._current_ship = ship

        self._load_ships()
        self._select_ship_in_list(ship.id)

    def _select_ship_in_list(self, ship_id: int | None) -> None:
        if ship_id is None:
            return
        for i in range(self._ships_list.count()):
            item = self._ships_list.item(i)
            if int(item.data(Qt.ItemDataRole.UserRole)) == ship_id:
                self._ships_list.setCurrentItem(item)
                break

    def _on_delete_ship(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Ship",
            f"Delete ship '{self._current_ship.name}' and its tanks?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        if database.SessionLocal is None:
            QMessageBox.critical(self, "Error", "Database not initialized.")
            return

        with database.SessionLocal() as db:
            ship_service = ShipService(db)
            tank_repo = TankRepository(db)
            pen_repo = LivestockPenRepository(db)
            for pen in pen_repo.list_for_ship(self._current_ship.id):
                if pen.id is not None:
                    pen_repo.delete(pen.id)
            for tank in tank_repo.list_for_ship(self._current_ship.id):
                if tank.id is not None:
                    tank_repo.delete(tank.id)
            ship_service.delete_ship(self._current_ship.id)

        self._current_ship = None
        self._clear_ship_form()
        self._tanks_table.setRowCount(0)
        self._pens_table.setRowCount(0)
        self._load_ships()

    def _on_add_tank_row(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            QMessageBox.information(
                self,
                "No Ship",
                "Save a ship first before adding tanks.",
            )
            return
        row = self._tanks_table.rowCount()
        self._tanks_table.insertRow(row)
        self._tanks_table.setItem(row, 0, QTableWidgetItem("Tank"))
        combo = QComboBox(self)
        combo.addItems(TANK_CATEGORY_NAMES)
        combo.setCurrentText("Misc. Tanks")
        self._tanks_table.setCellWidget(row, 1, combo)
        self._tanks_table.setItem(row, 2, QTableWidgetItem("0.0"))
        self._tanks_table.setItem(row, 3, QTableWidgetItem("0.5"))

    def _on_delete_selected_tank_row(self) -> None:
        row = self._tanks_table.currentRow()
        if row < 0:
            return

        item = self._tanks_table.item(row, 0)
        tank_id = item.data(Qt.ItemDataRole.UserRole) if item else None

        if tank_id is not None and database.SessionLocal is not None:
            with database.SessionLocal() as db:
                repo = TankRepository(db)
                repo.delete(int(tank_id))

        self._tanks_table.removeRow(row)

    def _on_save_tanks(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            return

        if database.SessionLocal is None:
            raise RuntimeError("Database not initialized")

        with database.SessionLocal() as db:
            repo = TankRepository(db)

            for row in range(self._tanks_table.rowCount()):
                name_item = self._tanks_table.item(row, 0)
                cap_item = self._tanks_table.item(row, 2)
                pos_item = self._tanks_table.item(row, 3)

                if not name_item:
                    continue

                name = name_item.text().strip()
                category = "Misc. Tanks"
                combo = self._tanks_table.cellWidget(row, 1)
                if isinstance(combo, QComboBox):
                    category = combo.currentText().strip() or "Misc. Tanks"
                if category not in TANK_CATEGORY_NAMES:
                    category = "Misc. Tanks"
                allowed = TANK_CATEGORY_TYPES.get(category, [TankType.CARGO])
                tank_type = allowed[0] if allowed else TankType.CARGO

                try:
                    capacity = float(cap_item.text()) if cap_item else 0.0
                except (TypeError, ValueError):
                    capacity = 0.0

                try:
                    pos = float(pos_item.text()) if pos_item else 0.5
                except (TypeError, ValueError):
                    pos = 0.5

                tank_id = name_item.data(Qt.ItemDataRole.UserRole)
                tank = Tank(
                    id=int(tank_id) if tank_id is not None else None,
                    ship_id=self._current_ship.id,
                    name=name,
                    tank_type=tank_type,
                    category=category,
                    capacity_m3=capacity,
                    longitudinal_pos=pos,
                )

                if tank.id is None:
                    saved = repo.create(tank)
                    name_item.setData(Qt.ItemDataRole.UserRole, saved.id)
                else:
                    repo.update(tank)

        QMessageBox.information(self, "Tanks", "Tanks saved.")

    def _on_add_pen_row(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            QMessageBox.information(
                self, "No Ship", "Save a ship first before adding pens."
            )
            return
        row = self._pens_table.rowCount()
        self._pens_table.insertRow(row)
        self._pens_table.setItem(row, 0, QTableWidgetItem("PEN 1-1"))
        self._pens_table.setItem(row, 1, QTableWidgetItem("A"))
        self._pens_table.setItem(row, 2, QTableWidgetItem("0"))
        self._pens_table.setItem(row, 3, QTableWidgetItem("0.0"))
        self._pens_table.setItem(row, 4, QTableWidgetItem("0"))
        self._pens_table.setItem(row, 5, QTableWidgetItem("0.00"))
        self._pens_table.setItem(row, 6, QTableWidgetItem("0.00"))
        self._pens_table.setItem(row, 7, QTableWidgetItem(""))
        self._pens_table.setItem(row, 8, QTableWidgetItem("0.50"))
        self._pens_table.setItem(row, 9, QTableWidgetItem("0.00"))
        self._pens_table.setItem(row, 10, QTableWidgetItem("0.000"))
        self._pens_table.setItem(row, 11, QTableWidgetItem("0.000"))
        self._pens_table.setItem(row, 12, QTableWidgetItem("0.000"))
        self._pens_table.setItem(row, 13, QTableWidgetItem(""))

    def _on_delete_selected_pen_row(self) -> None:
        row = self._pens_table.currentRow()
        if row < 0:
            return
        item = self._pens_table.item(row, 0)
        pen_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if pen_id is not None and database.SessionLocal is not None:
            with database.SessionLocal() as db:
                LivestockPenRepository(db).delete(int(pen_id))
        self._pens_table.removeRow(row)

    def _on_save_pens(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            return
        if database.SessionLocal is None:
            raise RuntimeError("Database not initialized")
        with database.SessionLocal() as db:
            repo = LivestockPenRepository(db)
            for row in range(self._pens_table.rowCount()):
                name_item = self._pens_table.item(row, 0)
                deck_item = self._pens_table.item(row, 1)
                cap_item = self._pens_table.item(row, 4)   # Head Capacity
                area_item = self._pens_table.item(row, 6)  # Total Area m2
                vcg_item = self._pens_table.item(row, 10)
                lcg_item = self._pens_table.item(row, 11)
                tcg_item = self._pens_table.item(row, 12)
                if not name_item:
                    continue
                try:
                    area = float(area_item.text()) if area_item else 0.0
                except (TypeError, ValueError):
                    area = 0.0
                try:
                    vcg = float(vcg_item.text()) if vcg_item else 0.0
                except (TypeError, ValueError):
                    vcg = 0.0
                try:
                    lcg = float(lcg_item.text()) if lcg_item else 0.0
                except (TypeError, ValueError):
                    lcg = 0.0
                try:
                    tcg = float(tcg_item.text()) if tcg_item else 0.0
                except (TypeError, ValueError):
                    tcg = 0.0
                try:
                    cap = int(float(cap_item.text())) if cap_item else 0
                except (TypeError, ValueError):
                    cap = 0
                pen = LivestockPen(
                    id=int(name_item.data(Qt.ItemDataRole.UserRole)) if name_item.data(Qt.ItemDataRole.UserRole) is not None else None,
                    ship_id=self._current_ship.id,
                    name=name_item.text().strip() or "PEN",
                    deck=deck_item.text().strip() if deck_item else "",
                    area_m2=area,
                    vcg_m=vcg,
                    lcg_m=lcg,
                    tcg_m=tcg,
                    capacity_head=cap,
                )
                if pen.id is None:
                    saved = repo.create(pen)
                    name_item.setData(Qt.ItemDataRole.UserRole, saved.id)
                else:
                    repo.update(pen)
        QMessageBox.information(self, "Pens", "Livestock pens saved.")

    # Helpers ----------------------------------------------------------------
    def _clear_ship_form(self) -> None:
        self._name_edit.clear()
        self._imo_edit.clear()
        self._flag_edit.clear()
        self._loa_spin.setValue(0.0)
        self._breadth_spin.setValue(0.0)
        self._depth_spin.setValue(0.0)
        self._design_draft_spin.setValue(0.0)


