"""
Edit Cargo Library dialog.

Table: No., Color, Pattern, Used?, Cargo Name, Description.
Actions: Add New, Edit, Delete, Move Up, Move Down. OK / Cancel.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QMessageBox,
    QMenuBar,
    QMenu,
    QWidget,
    QAbstractItemView,
    QFileDialog,
    QDialogButtonBox,
)
from ..models.cargo_type import CargoType
from ..repositories import database
from ..repositories.cargo_type_repository import CargoTypeRepository


# Default palette for color picker
COLOR_OPTIONS = [
    "#8844aa", "#4477aa", "#44aa77", "#aa8844", "#aa4444",
    "#aa44aa", "#4444aa", "#44aaaa", "#888888", "#000000",
]


def _edit_cargo_type_dialog(
    parent: QWidget,
    cargo: CargoType,
    title: str = "Edit Cargo",
) -> Optional[CargoType]:
    """Edit Cargo dialog: Name, Color, Pattern, Method, Type, Avg W/head, VCG from Deck, Deck Area/head, Dung %/day."""
    from PyQt6.QtWidgets import (
        QFormLayout,
        QLineEdit,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QLabel,
        QFrame,
        QGridLayout,
    )
    from PyQt6.QtWidgets import QColorDialog

    d = QDialog(parent)
    d.setWindowTitle(title)
    layout = QFormLayout(d)

    name_edit = QLineEdit(d)
    name_edit.setText(cargo.name)
    name_edit.setPlaceholderText("e.g. cattle 520kg")
    layout.addRow("Name:", name_edit)

    # Color: swatch + "..." button
    def _hex_from_qcolor(c: QColor) -> str:
        return c.name()

    color_hex = cargo.color_hex
    try:
        color = QColor(cargo.color_hex)
    except Exception:
        color = QColor("#8844aa")

    color_frame = QFrame(d)
    color_frame.setFixedSize(80, 24)
    color_frame.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
    color_btn = QPushButton("...", d)
    color_btn.setFixedWidth(32)

    def _pick_color() -> None:
        nonlocal color_hex
        chosen = QColorDialog.getColor(QColor(color_hex), d, "Choose color")
        if chosen.isValid():
            color_hex = chosen.name()
            color_frame.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #888;")

    color_btn.clicked.connect(_pick_color)
    color_row = QHBoxLayout()
    color_row.addWidget(color_frame)
    color_row.addWidget(color_btn)
    color_row.addStretch()
    layout.addRow("Color:", color_row)

    pattern_combo = QComboBox(d)
    pattern_combo.addItems(["Solid", "Hatched", "Dotted", "Cross"])
    idx = pattern_combo.findText(cargo.pattern)
    if idx >= 0:
        pattern_combo.setCurrentIndex(idx)
    layout.addRow("Pattern:", pattern_combo)

    method_combo = QComboBox(d)
    method_combo.addItems(["Livestock", "General Cargo", "Bulk"])
    idx = method_combo.findText(getattr(cargo, "method", "Livestock"))
    if idx >= 0:
        method_combo.setCurrentIndex(idx)
    layout.addRow("Method:", method_combo)

    type_combo = QComboBox(d)
    type_combo.addItems([
        "Walk-On, Walk-Off",
        "Lift-On, Lift-Off",
        "Drive-On, Drive-Off",
        "Other",
    ])
    idx = type_combo.findText(getattr(cargo, "cargo_subtype", "Walk-On, Walk-Off"))
    if idx >= 0:
        type_combo.setCurrentIndex(idx)
    layout.addRow("Type:", type_combo)

    avg_kg_spin = QDoubleSpinBox(d)
    avg_kg_spin.setRange(0.0, 10000.0)
    avg_kg_spin.setDecimals(2)
    avg_kg_spin.setValue(getattr(cargo, "avg_weight_per_head_kg", 520.0))
    avg_kg_spin.setSuffix(" Kg")
    layout.addRow("Avg Weight Per Head:", avg_kg_spin)

    vcg_spin = QDoubleSpinBox(d)
    vcg_spin.setRange(0.0, 20.0)
    vcg_spin.setDecimals(3)
    vcg_spin.setValue(getattr(cargo, "vcg_from_deck_m", 1.5))
    vcg_spin.setSuffix(" m")
    layout.addRow("VCG from Deck:", vcg_spin)

    area_spin = QDoubleSpinBox(d)
    area_spin.setRange(0.0, 100.0)
    area_spin.setDecimals(3)
    area_spin.setValue(getattr(cargo, "deck_area_per_head_m2", 1.85))
    area_spin.setSuffix(" m²/head")
    layout.addRow("Deck Area per Head:", area_spin)

    dung_spin = QDoubleSpinBox(d)
    dung_spin.setRange(0.0, 100.0)
    dung_spin.setDecimals(2)
    dung_spin.setValue(getattr(cargo, "dung_weight_pct_per_day", 1.5))
    layout.addRow("Dung Weight %/day:", dung_spin)

    desc_edit = QLineEdit(d)
    desc_edit.setText(cargo.description)
    desc_edit.setPlaceholderText("Optional notes")
    layout.addRow("Description:", desc_edit)

    used_cb = QCheckBox(d)
    used_cb.setChecked(cargo.in_use)
    layout.addRow("Used?", used_cb)

    bbox = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        d,
    )
    bbox.accepted.connect(d.accept)
    bbox.rejected.connect(d.reject)
    layout.addRow(bbox)

    if d.exec() != QDialog.DialogCode.Accepted:
        return None

    return CargoType(
        id=cargo.id,
        display_order=cargo.display_order,
        color_hex=color_hex,
        pattern=pattern_combo.currentText(),
        in_use=used_cb.isChecked(),
        name=name_edit.text().strip() or cargo.name,
        description=desc_edit.text().strip(),
        method=method_combo.currentText(),
        cargo_subtype=type_combo.currentText(),
        avg_weight_per_head_kg=avg_kg_spin.value(),
        vcg_from_deck_m=vcg_spin.value(),
        deck_area_per_head_m2=area_spin.value(),
        dung_weight_pct_per_day=dung_spin.value(),
    )


class CargoLibraryDialog(QDialog):
    """Edit Cargo Library: table + Add/Edit/Delete/Move Up/Down, OK/Cancel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Cargo Library")
        self.setMinimumSize(720, 400)
        self.resize(820, 450)

        self._items: List[CargoType] = []
        self._table = QTableWidget(self)
        self._table.setColumnCount(10)
        self._table.setHorizontalHeaderLabels([
            "No.", "Color", "Pattern", "Used?", "Cargo Name",
            "Method", "Type", "Avg W/head (kg)", "VCG (m)", "Area/head (m²)",
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)

        # Buttons
        add_btn = QPushButton("Add New...", self)
        edit_btn = QPushButton("Edit...", self)
        delete_btn = QPushButton("Delete", self)
        move_up_btn = QPushButton("Move Up", self)
        move_down_btn = QPushButton("Move Down", self)
        add_btn.clicked.connect(self._on_add)
        edit_btn.clicked.connect(self._on_edit)
        delete_btn.clicked.connect(self._on_delete)
        move_up_btn.clicked.connect(self._on_move_up)
        move_down_btn.clicked.connect(self._on_move_down)

        btn_layout = QVBoxLayout()
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addSpacing(16)
        btn_layout.addWidget(move_up_btn)
        btn_layout.addWidget(move_down_btn)
        btn_layout.addStretch()

        main = QHBoxLayout()
        main.addWidget(self._table, 1)
        main.addLayout(btn_layout)

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        bbox.accepted.connect(self._on_ok)
        bbox.rejected.connect(self.reject)

        # File menu
        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("File")
        import_act = file_menu.addAction("Import library...")
        import_act.triggered.connect(self._on_import)
        export_act = file_menu.addAction("Export library...")
        export_act.triggered.connect(self._on_export)

        root = QVBoxLayout(self)
        root.addWidget(menubar)
        root.addLayout(main)
        root.addWidget(bbox)

        self._load_from_db()

    def _load_from_db(self) -> None:
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            repo = CargoTypeRepository(db)
            self._items = repo.list_all()
        self._fill_table()

    def _fill_table(self) -> None:
        self._table.setRowCount(len(self._items))
        for row, ct in enumerate(self._items):
            no_item = QTableWidgetItem(str(row + 1))
            no_item.setData(Qt.ItemDataRole.UserRole, ct.id)
            self._table.setItem(row, 0, no_item)
            color_item = QTableWidgetItem("")
            try:
                color_item.setBackground(QColor(ct.color_hex))
            except Exception:
                color_item.setBackground(QColor("#8844aa"))
            self._table.setItem(row, 1, color_item)
            self._table.setItem(row, 2, QTableWidgetItem(ct.pattern))
            self._table.setItem(row, 3, QTableWidgetItem("Y" if ct.in_use else "N"))
            self._table.setItem(row, 4, QTableWidgetItem(ct.name))
            self._table.setItem(row, 5, QTableWidgetItem(getattr(ct, "method", "Livestock")))
            self._table.setItem(row, 6, QTableWidgetItem(getattr(ct, "cargo_subtype", "Walk-On, Walk-Off")))
            self._table.setItem(row, 7, QTableWidgetItem(f"{getattr(ct, 'avg_weight_per_head_kg', 520):.2f}"))
            self._table.setItem(row, 8, QTableWidgetItem(f"{getattr(ct, 'vcg_from_deck_m', 1.5):.3f}"))
            self._table.setItem(row, 9, QTableWidgetItem(f"{getattr(ct, 'deck_area_per_head_m2', 1.85):.3f}"))

    def _selected_id(self) -> Optional[int]:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row].id

    def _on_add(self) -> None:
        new_ct = CargoType(
            display_order=len(self._items),
            name="New cargo",
            description="",
        )
        edited = _edit_cargo_type_dialog(self, new_ct, "Add New Cargo Type")
        if not edited:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            repo = CargoTypeRepository(db)
            edited = repo.create(edited)
        self._items.append(edited)
        self._fill_table()

    def _on_edit(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Edit", "Select a cargo type first.")
            return
        ct = next((c for c in self._items if c.id == cid), None)
        if not ct:
            return
        edited = _edit_cargo_type_dialog(self, ct, "Edit Cargo Type")
        if not edited:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            repo = CargoTypeRepository(db)
            repo.update(edited)
        idx = next((i for i, c in enumerate(self._items) if c.id == cid), None)
        if idx is not None:
            self._items[idx] = edited
        self._fill_table()

    def _on_delete(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Delete", "Select a cargo type first.")
            return
        if QMessageBox.question(
            self,
            "Delete",
            "Delete this cargo type?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            CargoTypeRepository(db).delete(cid)
        self._items = [c for c in self._items if c.id != cid]
        self._fill_table()

    def _on_move_up(self) -> None:
        cid = self._selected_id()
        if cid is None:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            if CargoTypeRepository(db).move_up(cid):
                self._load_from_db()
                # Restore selection
                for row in range(self._table.rowCount()):
                    if self._table.item(row, 0) and self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == cid:
                        self._table.selectRow(row)
                        break

    def _on_move_down(self) -> None:
        cid = self._selected_id()
        if cid is None:
            return
        if database.SessionLocal is None:
            return
        with database.SessionLocal() as db:
            if CargoTypeRepository(db).move_down(cid):
                self._load_from_db()
                for row in range(self._table.rowCount()):
                    if self._table.item(row, 0) and self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == cid:
                        self._table.selectRow(row)
                        break

    def _on_ok(self) -> None:
        self.accept()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Cargo Library",
            "", "JSON (*.json);;All (*)",
        )
        if not path:
            return
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if database.SessionLocal is None:
                return
            with database.SessionLocal() as db:
                repo = CargoTypeRepository(db)
                for i, item in enumerate(data if isinstance(data, list) else data.get("cargo_types", [])):
                    ct = CargoType(
                        display_order=item.get("display_order", i),
                        color_hex=item.get("color_hex", "#8844aa"),
                        pattern=item.get("pattern", "Solid"),
                        in_use=item.get("in_use", True),
                        name=item.get("name", ""),
                        description=item.get("description", ""),
                        method=item.get("method", "Livestock"),
                        cargo_subtype=item.get("cargo_subtype", "Walk-On, Walk-Off"),
                        avg_weight_per_head_kg=float(item.get("avg_weight_per_head_kg", 520)),
                        vcg_from_deck_m=float(item.get("vcg_from_deck_m", 1.5)),
                        deck_area_per_head_m2=float(item.get("deck_area_per_head_m2", 1.85)),
                        dung_weight_pct_per_day=float(item.get("dung_weight_pct_per_day", 1.5)),
                    )
                    repo.create(ct)
            self._load_from_db()
            QMessageBox.information(self, "Import", "Cargo library imported.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cargo Library",
            "", "JSON (*.json);;All (*)",
        )
        if not path:
            return
        try:
            import json
            if not path.endswith(".json"):
                path += ".json"
            data = [
                {
                    "display_order": c.display_order,
                    "color_hex": c.color_hex,
                    "pattern": c.pattern,
                    "in_use": c.in_use,
                    "name": c.name,
                    "description": c.description,
                    "method": getattr(c, "method", "Livestock"),
                    "cargo_subtype": getattr(c, "cargo_subtype", "Walk-On, Walk-Off"),
                    "avg_weight_per_head_kg": getattr(c, "avg_weight_per_head_kg", 520.0),
                    "vcg_from_deck_m": getattr(c, "vcg_from_deck_m", 1.5),
                    "deck_area_per_head_m2": getattr(c, "deck_area_per_head_m2", 1.85),
                    "dung_weight_pct_per_day": getattr(c, "dung_weight_pct_per_day", 1.5),
                }
                for c in self._items
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"cargo_types": data}, f, indent=2)
            QMessageBox.information(self, "Export", "Cargo library exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
