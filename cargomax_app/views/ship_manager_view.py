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
from ..utils.sorting import get_pen_sort_key, get_tank_sort_key
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

        # Tanks table: NAME ITEM, Category, DESCRIPTION, Volume m³, Density t/m³, Weight t, VCG m, LCG m, TCG m
        self._tanks_table = QTableWidget(self)
        self._tanks_table.setColumnCount(9)
        self._tanks_table.setHorizontalHeaderLabels(
            ["NAME ITEM", "Category", "DESCRIPTION", "Volume m³", "Density t/m³", "Weight t", "VCG m", "LCG m", "TCG m"]
        )
        self._tanks_table.horizontalHeader().setStretchLastSection(False)
        self._tanks_table.setColumnWidth(0, 150)
        self._tanks_table.setColumnWidth(1, 140)
        self._tanks_table.setColumnWidth(2, 200)
        self._tanks_table.setColumnWidth(3, 100)
        self._tanks_table.setColumnWidth(4, 100)
        self._tanks_table.setColumnWidth(5, 100)
        self._tanks_table.setColumnWidth(6, 80)
        self._tanks_table.setColumnWidth(7, 80)
        self._tanks_table.setColumnWidth(8, 80)
        self._tanks_table.setAlternatingRowColors(True)
        self._tanks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tanks_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        self._tank_add_btn = QPushButton("Add Tank", self)
        self._tank_delete_btn = QPushButton("Delete Selected Tank", self)
        self._tank_save_btn = QPushButton("Save Tanks", self)

        # Livestock pens table – simplified structure
        self._pens_table = QTableWidget(self)
        self._pens_table.setColumnCount(6)
        self._pens_table.setHorizontalHeaderLabels([
            "Pens no.",
            "Deck",
            "Area (m²)",
            "LCG (m) from Fr. 0",
            "VCG (m) from B.L.",
            "TCG (m) from C.L.",
        ])
        self._pens_table.horizontalHeader().setStretchLastSection(False)
        self._pens_table.setColumnWidth(0, 100)
        self._pens_table.setColumnWidth(1, 80)
        self._pens_table.setColumnWidth(2, 120)
        self._pens_table.setColumnWidth(3, 150)
        self._pens_table.setColumnWidth(4, 150)
        self._pens_table.setColumnWidth(5, 150)
        self._pens_table.setAlternatingRowColors(True)
        self._pens_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pens_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)
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
        self._tanks_table.itemChanged.connect(self._on_tank_data_changed)
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
        """Fill pens table with simplified structure: Pens no., Area, LCG, VCG, TCG."""
        self._pens_table.setRowCount(0)
        
        # Sort pens by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
        sorted_pens = sorted(pens, key=get_pen_sort_key)
        
        # Deck options for dropdown
        deck_options = ["A", "B", "C", "D", "E", "F", "G", "H"]
        
        for pen in sorted_pens:
            row = self._pens_table.rowCount()
            self._pens_table.insertRow(row)
            
            # Pens no. (use pen name or pen_no if available)
            pen_no = pen.name if pen.name else (str(pen.pen_no) if pen.pen_no else "")
            pen_no_item = QTableWidgetItem(pen_no)
            pen_no_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            self._pens_table.setItem(row, 0, pen_no_item)
            
            # Deck dropdown
            deck = pen.deck.strip().upper() if pen.deck else ""
            # Normalize deck to A-H format
            if deck and deck not in deck_options:
                # Try to convert DK1-DK8 or 1-8 to A-H
                if deck.startswith("DK") and len(deck) > 2:
                    try:
                        deck_num = int(deck[2:])
                        if 1 <= deck_num <= 8:
                            deck = chr(ord("A") + deck_num - 1)
                    except ValueError:
                        pass
                elif deck.isdigit():
                    try:
                        deck_num = int(deck)
                        if 1 <= deck_num <= 8:
                            deck = chr(ord("A") + deck_num - 1)
                    except ValueError:
                        pass
            
            if deck not in deck_options:
                deck = "A"  # Default to deck A
            
            deck_combo = QComboBox(self)
            deck_combo.addItems(deck_options)
            deck_combo.setCurrentText(deck)
            self._pens_table.setCellWidget(row, 1, deck_combo)
            
            # Area (m²)
            self._pens_table.setItem(row, 2, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            
            # LCG (m) from Fr. 0
            self._pens_table.setItem(row, 3, QTableWidgetItem(f"{pen.lcg_m:.2f}"))
            
            # VCG (m) from B.L.
            self._pens_table.setItem(row, 4, QTableWidgetItem(f"{pen.vcg_m:.2f}"))
            
            # TCG (m) from C.L.
            self._pens_table.setItem(row, 5, QTableWidgetItem(f"{pen.tcg_m:.2f}"))

    def _populate_tanks_table(self, tanks: list[Tank]) -> None:
        """Populate tanks table with category grouping and totals, matching the design from images."""
        self._tanks_table.setRowCount(0)
        
        if not tanks:
            return
        
        # Group tanks by category
        tanks_by_category: dict[str, list[Tank]] = {}
        for tank in tanks:
            category = getattr(tank, "category", None) or "Misc. Tanks"
            if category not in tanks_by_category:
                tanks_by_category[category] = []
            tanks_by_category[category].append(tank)
        
        # Sort categories for consistent display
        sorted_categories = sorted(tanks_by_category.keys())
        
        # Populate table with grouped tanks
        for category in sorted_categories:
            cat_tanks = tanks_by_category[category]
            
            # Sort tanks within category by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
            cat_tanks = sorted(cat_tanks, key=get_tank_sort_key)
            
            # Add tanks for this category
            for tank in cat_tanks:
                row = self._tanks_table.rowCount()
                self._tanks_table.insertRow(row)
                
                # NAME ITEM
                name_item = QTableWidgetItem(tank.name)
                name_item.setData(Qt.ItemDataRole.UserRole, tank.id)
                self._tanks_table.setItem(row, 0, name_item)
                
                # Category dropdown
                category = getattr(tank, "category", None) or "Misc. Tanks"
                if category not in TANK_CATEGORY_NAMES:
                    category = "Misc. Tanks"
                category_combo = QComboBox(self)
                category_combo.addItems(TANK_CATEGORY_NAMES)
                category_combo.setCurrentText(category)
                self._tanks_table.setCellWidget(row, 1, category_combo)
                
                # DESCRIPTION
                description = getattr(tank, "description", None) or tank.name
                self._tanks_table.setItem(row, 2, QTableWidgetItem(description))
                
                # Volume m³
                volume = tank.capacity_m3
                self._tanks_table.setItem(row, 3, QTableWidgetItem(f"{volume:.2f}"))
                
                # Density t/m³
                density = getattr(tank, "density_t_per_m3", 1.0) or 1.0
                self._tanks_table.setItem(row, 4, QTableWidgetItem(f"{density:.3f}"))
                
                # Weight t (calculated: Volume * Density)
                weight = volume * density
                weight_item = QTableWidgetItem(f"{weight:.2f}")
                weight_item.setFlags(weight_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
                self._tanks_table.setItem(row, 5, weight_item)
                
                # VCG m (kg_m)
                vcg = tank.kg_m
                self._tanks_table.setItem(row, 6, QTableWidgetItem(f"{vcg:.2f}"))
                
                # LCG m
                lcg = tank.lcg_m
                self._tanks_table.setItem(row, 7, QTableWidgetItem(f"{lcg:.2f}"))
                
                # TCG m
                tcg = tank.tcg_m
                self._tanks_table.setItem(row, 8, QTableWidgetItem(f"{tcg:.2f}"))
            
            # Add total row for this category
            if cat_tanks:
                row = self._tanks_table.rowCount()
                self._tanks_table.insertRow(row)
                
                # Calculate totals
                total_volume = sum(t.capacity_m3 for t in cat_tanks)
                total_weight = sum(t.capacity_m3 * (getattr(t, "density_t_per_m3", 1.0) or 1.0) for t in cat_tanks)
                
                # Total row styling
                total_name = QTableWidgetItem(f"{category.upper()} TOTAL")
                total_name.setFlags(total_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
                font = total_name.font()
                font.setBold(True)
                total_name.setFont(font)
                self._tanks_table.setItem(row, 0, total_name)
                
                # Empty category for total row
                total_cat_item = QTableWidgetItem("")
                total_cat_item.setFlags(total_cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tanks_table.setItem(row, 1, total_cat_item)
                
                # Empty description for total row
                total_desc = QTableWidgetItem("")
                total_desc.setFlags(total_desc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tanks_table.setItem(row, 2, total_desc)
                
                # Total Volume
                total_vol_item = QTableWidgetItem(f"{total_volume:.2f}")
                total_vol_item.setFlags(total_vol_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                total_vol_item.setFont(font)
                self._tanks_table.setItem(row, 3, total_vol_item)
                
                # Empty density for total row
                total_dens_item = QTableWidgetItem("")
                total_dens_item.setFlags(total_dens_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tanks_table.setItem(row, 4, total_dens_item)
                
                # Total Weight
                total_weight_item = QTableWidgetItem(f"{total_weight:.2f}")
                total_weight_item.setFlags(total_weight_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                total_weight_item.setFont(font)
                self._tanks_table.setItem(row, 5, total_weight_item)
                
                # Empty VCG, LCG, TCG for total row
                for col in [6, 7, 8]:
                    empty_item = QTableWidgetItem("")
                    empty_item.setFlags(empty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tanks_table.setItem(row, col, empty_item)

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
        
        # Find the last row before any total rows (or add at end)
        row = self._tanks_table.rowCount()
        
        # Check if last row is a total row, if so insert before it
        if row > 0:
            last_item = self._tanks_table.item(row - 1, 0)
            if last_item and "TOTAL" in last_item.text().upper():
                row = row - 1
        
        self._tanks_table.insertRow(row)
        
        # NAME ITEM
        name_item = QTableWidgetItem("Tank")
        self._tanks_table.setItem(row, 0, name_item)
        
        # Category dropdown
        category_combo = QComboBox(self)
        category_combo.addItems(TANK_CATEGORY_NAMES)
        category_combo.setCurrentText("Misc. Tanks")
        self._tanks_table.setCellWidget(row, 1, category_combo)
        
        # DESCRIPTION
        self._tanks_table.setItem(row, 2, QTableWidgetItem(""))
        
        # Volume m³
        self._tanks_table.setItem(row, 3, QTableWidgetItem("0.00"))
        
        # Density t/m³ (default 1.0 for fresh water)
        self._tanks_table.setItem(row, 4, QTableWidgetItem("1.000"))
        
        # Weight t (calculated, read-only)
        weight_item = QTableWidgetItem("0.00")
        weight_item.setFlags(weight_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._tanks_table.setItem(row, 5, weight_item)
        
        # VCG m
        self._tanks_table.setItem(row, 6, QTableWidgetItem("0.00"))
        
        # LCG m
        self._tanks_table.setItem(row, 7, QTableWidgetItem("0.00"))
        
        # TCG m
        self._tanks_table.setItem(row, 8, QTableWidgetItem("0.00"))
        
        # Connect to update weight when volume or density changes
        self._tanks_table.itemChanged.connect(self._on_tank_data_changed)

    def _on_delete_selected_tank_row(self) -> None:
        row = self._tanks_table.currentRow()
        if row < 0:
            return

        item = self._tanks_table.item(row, 0)
        if not item:
            return
        
        # Don't allow deleting total rows
        if "TOTAL" in item.text().upper():
            QMessageBox.information(self, "Delete", "Cannot delete total rows.")
            return
        
        tank_id = item.data(Qt.ItemDataRole.UserRole) if item else None

        if tank_id is not None and database.SessionLocal is not None:
            with database.SessionLocal() as db:
                repo = TankRepository(db)
                repo.delete(int(tank_id))

        # Refresh table to update totals
        if self._current_ship and self._current_ship.id:
            with database.SessionLocal() as db:
                tank_repo = TankRepository(db)
                tanks = tank_repo.list_for_ship(self._current_ship.id)
                self._populate_tanks_table(tanks)

    def _on_tank_data_changed(self, item: QTableWidgetItem) -> None:
        """Update weight when volume or density changes."""
        row = item.row()
        col = item.column()
        
        # Only update weight if volume (col 3) or density (col 4) changed
        if col not in [3, 4]:
            return
        
        # Skip if this is a total row
        name_item = self._tanks_table.item(row, 0)
        if name_item and "TOTAL" in name_item.text().upper():
            return
        
        # Get volume and density
        vol_item = self._tanks_table.item(row, 3)
        dens_item = self._tanks_table.item(row, 4)
        
        if not vol_item or not dens_item:
            return
        
        try:
            volume = float(vol_item.text())
            density = float(dens_item.text())
            weight = volume * density
            
            # Update weight cell
            weight_item = self._tanks_table.item(row, 5)
            if weight_item:
                weight_item.setText(f"{weight:.2f}")
        except (ValueError, TypeError):
            pass

    def _on_save_tanks(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            return

        if database.SessionLocal is None:
            raise RuntimeError("Database not initialized")

        with database.SessionLocal() as db:
            repo = TankRepository(db)

            # Track which categories we've seen to determine tank category
            category_tanks: dict[str, list[int]] = {}
            
            for row in range(self._tanks_table.rowCount()):
                name_item = self._tanks_table.item(row, 0)
                if not name_item:
                    continue
                
                # Skip total rows
                if "TOTAL" in name_item.text().upper():
                    continue

                name = name_item.text().strip()
                if not name:
                    continue
                
                # Get category from dropdown
                category_combo = self._tanks_table.cellWidget(row, 1)
                if isinstance(category_combo, QComboBox):
                    category = category_combo.currentText().strip() or "Misc. Tanks"
                else:
                    category = "Misc. Tanks"
                
                if category not in TANK_CATEGORY_NAMES:
                    category = "Misc. Tanks"
                
                desc_item = self._tanks_table.item(row, 2)
                vol_item = self._tanks_table.item(row, 3)
                dens_item = self._tanks_table.item(row, 4)
                vcg_item = self._tanks_table.item(row, 6)
                lcg_item = self._tanks_table.item(row, 7)
                tcg_item = self._tanks_table.item(row, 8)

                description = desc_item.text().strip() if desc_item else name
                
                try:
                    volume = float(vol_item.text()) if vol_item else 0.0
                except (TypeError, ValueError):
                    volume = 0.0

                try:
                    density = float(dens_item.text()) if dens_item else 1.0
                except (TypeError, ValueError):
                    density = 1.0

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
                
                allowed = TANK_CATEGORY_TYPES.get(category, [TankType.CARGO])
                tank_type = allowed[0] if allowed else TankType.CARGO

                tank_id = name_item.data(Qt.ItemDataRole.UserRole)
                tank = Tank(
                    id=int(tank_id) if tank_id is not None else None,
                    ship_id=self._current_ship.id,
                    name=name,
                    description=description,
                    tank_type=tank_type,
                    category=category,
                    capacity_m3=volume,
                    density_t_per_m3=density,
                    longitudinal_pos=lcg / (self._current_ship.length_overall_m or 1.0) if self._current_ship.length_overall_m else 0.5,
                    kg_m=vcg,
                    lcg_m=lcg,
                    tcg_m=tcg,
                )

                if tank.id is None:
                    saved = repo.create(tank)
                    name_item.setData(Qt.ItemDataRole.UserRole, saved.id)
                else:
                    repo.update(tank)

        # Refresh the table to show updated categories and totals
        with database.SessionLocal() as db:
            tank_repo = TankRepository(db)
            tanks = tank_repo.list_for_ship(self._current_ship.id)
            self._populate_tanks_table(tanks)
        
        QMessageBox.information(self, "Tanks", "Tanks saved.")

    def _on_add_pen_row(self) -> None:
        if self._current_ship is None or self._current_ship.id is None:
            QMessageBox.information(
                self, "No Ship", "Save a ship first before adding pens."
            )
            return
        row = self._pens_table.rowCount()
        self._pens_table.insertRow(row)
        
        # Pens no.
        self._pens_table.setItem(row, 0, QTableWidgetItem("PEN 1-1"))
        
        # Deck dropdown
        deck_combo = QComboBox(self)
        deck_combo.addItems(["A", "B", "C", "D", "E", "F", "G", "H"])
        deck_combo.setCurrentText("A")  # Default to deck A
        self._pens_table.setCellWidget(row, 1, deck_combo)
        
        # Area (m²)
        self._pens_table.setItem(row, 2, QTableWidgetItem("0.00"))
        
        # LCG (m) from Fr. 0
        self._pens_table.setItem(row, 3, QTableWidgetItem("0.00"))
        
        # VCG (m) from B.L.
        self._pens_table.setItem(row, 4, QTableWidgetItem("0.00"))
        
        # TCG (m) from C.L.
        self._pens_table.setItem(row, 5, QTableWidgetItem("0.00"))

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
                pen_no_item = self._pens_table.item(row, 0)
                if not pen_no_item:
                    continue
                
                # Get deck from dropdown
                deck_combo = self._pens_table.cellWidget(row, 1)
                if isinstance(deck_combo, QComboBox):
                    deck = deck_combo.currentText().strip() or "A"
                else:
                    deck = "A"
                
                pen_no = pen_no_item.text().strip() or "PEN"
                
                area_item = self._pens_table.item(row, 2)  # Area (m²)
                lcg_item = self._pens_table.item(row, 3)   # LCG (m) from Fr. 0
                vcg_item = self._pens_table.item(row, 4)   # VCG (m) from B.L.
                tcg_item = self._pens_table.item(row, 5)   # TCG (m) from C.L.
                
                try:
                    area = float(area_item.text()) if area_item else 0.0
                except (TypeError, ValueError):
                    area = 0.0
                try:
                    lcg = float(lcg_item.text()) if lcg_item else 0.0
                except (TypeError, ValueError):
                    lcg = 0.0
                try:
                    vcg = float(vcg_item.text()) if vcg_item else 0.0
                except (TypeError, ValueError):
                    vcg = 0.0
                try:
                    tcg = float(tcg_item.text()) if tcg_item else 0.0
                except (TypeError, ValueError):
                    tcg = 0.0
                
                pen = LivestockPen(
                    id=int(pen_no_item.data(Qt.ItemDataRole.UserRole)) if pen_no_item.data(Qt.ItemDataRole.UserRole) is not None else None,
                    ship_id=self._current_ship.id,
                    name=pen_no,
                    deck=deck,
                    area_m2=area,
                    vcg_m=vcg,
                    lcg_m=lcg,
                    tcg_m=tcg,
                    capacity_head=0,  # Not in simplified table
                )
                if pen.id is None:
                    saved = repo.create(pen)
                    pen_no_item.setData(Qt.ItemDataRole.UserRole, saved.id)
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


