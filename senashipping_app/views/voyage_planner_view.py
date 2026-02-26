"""
Voyage Planner view.

Voyage CRUD linked to ships. Conditions per voyage with edit/delete.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QPushButton,
    QLabel,
    QGroupBox,
    QMessageBox,
)

from senashipping_app.models import Ship, Voyage, LoadingCondition
from senashipping_app.repositories import database
from senashipping_app.repositories.ship_repository import ShipRepository
from senashipping_app.services.voyage_service import VoyageService, VoyageValidationError


class VoyagePlannerView(QWidget):
    """Signal: (voyage_id, condition_id) when user wants to edit a condition."""
    condition_selected = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        if database.SessionLocal is None:
            raise RuntimeError("Database not initialized")

        self._ships: List[Ship] = []
        self._voyages: List[Voyage] = []
        self._current_ship: Optional[Ship] = None
        self._current_voyage: Optional[Voyage] = None

        self._ship_combo = QComboBox(self)
        self._voyages_list = QListWidget(self)

        self._voyage_name_edit = QLineEdit(self)
        self._departure_edit = QLineEdit(self)
        self._arrival_edit = QLineEdit(self)
        self._voyage_new_btn = QPushButton("New Voyage", self)
        self._voyage_save_btn = QPushButton("Save Voyage", self)
        self._voyage_delete_btn = QPushButton("Delete Voyage", self)

        self._conditions_list = QListWidget(self)
        self._condition_new_btn = QPushButton("New Condition", self)
        self._condition_edit_btn = QPushButton("Edit Condition", self)
        self._condition_delete_btn = QPushButton("Delete Condition", self)

        self._build_layout()
        self._connect_signals()
        self._load_ships()

    def _build_layout(self) -> None:
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("Ship:", self))
        left.addWidget(self._ship_combo)
        left.addWidget(QLabel("Voyages", self))
        left.addWidget(self._voyages_list, 1)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        voyage_group = QGroupBox("Voyage Details", self)
        voyage_form = QFormLayout(voyage_group)
        voyage_form.addRow("Name:", self._voyage_name_edit)
        voyage_form.addRow("Departure Port:", self._departure_edit)
        voyage_form.addRow("Arrival Port:", self._arrival_edit)
        voyage_btns = QHBoxLayout()
        voyage_btns.addWidget(self._voyage_new_btn)
        voyage_btns.addWidget(self._voyage_save_btn)
        voyage_btns.addWidget(self._voyage_delete_btn)
        voyage_form.addRow(voyage_btns)
        right.addWidget(voyage_group)

        cond_group = QGroupBox("Conditions for Selected Voyage", self)
        cond_layout = QVBoxLayout(cond_group)
        cond_layout.addWidget(self._conditions_list, 1)
        cond_btns = QHBoxLayout()
        cond_btns.addWidget(self._condition_new_btn)
        cond_btns.addWidget(self._condition_edit_btn)
        cond_btns.addWidget(self._condition_delete_btn)
        cond_layout.addLayout(cond_btns)
        right.addWidget(cond_group, 1)

        root.addLayout(right, 2)

    def _connect_signals(self) -> None:
        self._ship_combo.currentIndexChanged.connect(self._on_ship_changed)
        self._voyages_list.currentItemChanged.connect(self._on_voyage_selection_changed)
        self._voyage_new_btn.clicked.connect(self._on_new_voyage)
        self._voyage_save_btn.clicked.connect(self._on_save_voyage)
        self._voyage_delete_btn.clicked.connect(self._on_delete_voyage)
        self._condition_new_btn.clicked.connect(self._on_new_condition)
        self._condition_edit_btn.clicked.connect(self._on_edit_condition)
        self._condition_delete_btn.clicked.connect(self._on_delete_condition)

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

        if self._ships:
            self._ship_combo.setCurrentIndex(0)
            self._on_ship_changed(0)

    def _load_voyages(self) -> None:
        self._voyages_list.clear()
        self._voyages = []
        if not self._current_ship or not self._current_ship.id:
            self._clear_voyage_form()
            self._conditions_list.clear()
            return

        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            svc = VoyageService(db)
            self._voyages = svc.list_voyages_for_ship(self._current_ship.id)

        for v in self._voyages:
            item = QListWidgetItem(f"{v.name} ({v.departure_port} → {v.arrival_port})")
            item.setData(Qt.ItemDataRole.UserRole, v.id)
            self._voyages_list.addItem(item)

    def _load_conditions(self) -> None:
        self._conditions_list.clear()
        if not self._current_voyage or not self._current_voyage.id:
            return

        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            svc = VoyageService(db)
            conditions = svc.list_conditions_for_voyage(self._current_voyage.id)

        for c in conditions:
            item = QListWidgetItem(f"{c.name} (Δ={c.displacement_t:.0f}t, GM={c.gm_m:.2f}m)")
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self._conditions_list.addItem(item)

    def _on_ship_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._ships):
            self._current_ship = None
        else:
            self._current_ship = self._ships[index]
        self._load_voyages()
        self._current_voyage = None
        self._clear_voyage_form()
        self._conditions_list.clear()

    def _on_voyage_selection_changed(
        self, current: QListWidgetItem | None, _prev: QListWidgetItem | None
    ) -> None:
        if current is None:
            self._current_voyage = None
            self._clear_voyage_form()
            self._conditions_list.clear()
            return
        vid = current.data(Qt.ItemDataRole.UserRole)
        if vid is None:
            return
        voyage_id = int(vid)
        self._current_voyage = next((v for v in self._voyages if v.id == voyage_id), None)
        if self._current_voyage:
            self._voyage_name_edit.setText(self._current_voyage.name)
            self._departure_edit.setText(self._current_voyage.departure_port)
            self._arrival_edit.setText(self._current_voyage.arrival_port)
            self._load_conditions()
        else:
            self._clear_voyage_form()
            self._conditions_list.clear()

    def _on_new_voyage(self) -> None:
        self._current_voyage = None
        self._clear_voyage_form()
        self._voyages_list.clearSelection()
        self._conditions_list.clear()

    def _on_save_voyage(self) -> None:
        if not self._current_ship or not self._current_ship.id:
            QMessageBox.information(self, "No Ship", "Select a ship first.")
            return
        if database.SessionLocal is None:
            return

        voyage = self._current_voyage or Voyage()
        voyage.ship_id = self._current_ship.id
        voyage.name = self._voyage_name_edit.text().strip()
        voyage.departure_port = self._departure_edit.text().strip()
        voyage.arrival_port = self._arrival_edit.text().strip()

        with database.SessionLocal() as db:
            svc = VoyageService(db)
            try:
                voyage = svc.save_voyage(voyage)
            except VoyageValidationError as e:
                QMessageBox.warning(self, "Validation", str(e))
                return

        self._current_voyage = voyage
        self._load_voyages()
        self._select_voyage_in_list(voyage.id)

    def _select_voyage_in_list(self, voyage_id: int | None) -> None:
        if voyage_id is None:
            return
        for i in range(self._voyages_list.count()):
            item = self._voyages_list.item(i)
            if int(item.data(Qt.ItemDataRole.UserRole)) == voyage_id:
                self._voyages_list.setCurrentItem(item)
                break

    def _on_delete_voyage(self) -> None:
        if not self._current_voyage or not self._current_voyage.id:
            return
        r = QMessageBox.question(
            self,
            "Delete Voyage",
            f"Delete voyage '{self._current_voyage.name}' and its conditions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return

        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            VoyageService(db).delete_voyage(self._current_voyage.id)

        self._current_voyage = None
        self._clear_voyage_form()
        self._load_voyages()
        self._conditions_list.clear()

    def _on_new_condition(self) -> None:
        if not self._current_voyage or not self._current_voyage.id:
            QMessageBox.information(self, "No Voyage", "Select or create a voyage first.")
            return

        name = f"Condition {len(self._conditions_list) + 1}"
        cond = LoadingCondition(voyage_id=self._current_voyage.id, name=name)

        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            VoyageService(db).save_condition(cond)

        self._load_conditions()
        if cond.id:
            self.condition_selected.emit(self._current_voyage.id, cond.id)

    def _on_edit_condition(self) -> None:
        item = self._conditions_list.currentItem()
        if not item or not self._current_voyage:
            QMessageBox.information(self, "No Selection", "Select a condition to edit.")
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid is None:
            return
        self.condition_selected.emit(self._current_voyage.id, int(cid))

    def _on_delete_condition(self) -> None:
        item = self._conditions_list.currentItem()
        if not item:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid is None:
            return

        r = QMessageBox.question(
            self,
            "Delete Condition",
            "Delete this condition?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return

        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            VoyageService(db).delete_condition(int(cid))

        self._load_conditions()

    def _clear_voyage_form(self) -> None:
        self._voyage_name_edit.clear()
        self._departure_edit.clear()
        self._arrival_edit.clear()
