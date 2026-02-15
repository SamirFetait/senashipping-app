"""
Tabbed table widget for displaying livestock pens and tanks by category.

Matches the reference UI with tabs for each deck, tank type, etc.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLabel,
    QComboBox,
)

from ..models import Tank, LivestockPen
from ..models.tank import TankType


MASS_PER_HEAD_T = 0.5  # Average mass per head in tonnes

# Map tank category tab name -> TankType(s) for filtering. Same list used in Ship Manager "Storing" dropdown.
TANK_CATEGORY_TYPES: Dict[str, List[TankType]] = {
    "Water Ballast": [TankType.BALLAST],
    "Fresh Water": [TankType.FRESH_WATER],
    "Heavy Fuel Oil": [TankType.FUEL],
    "Diesel Oil": [TankType.FUEL],
    "Lube Oil": [TankType.OTHER],
    "Gray Water": [TankType.OTHER],
    "Misc. Tanks": [TankType.CARGO],
    "Dung": [],       # Pens for dung (optional; define in Ship & data setup)
    "Fodder Hold": [TankType.CARGO],
}
TANK_CATEGORY_NAMES: List[str] = list(TANK_CATEGORY_TYPES.keys())


def _deck_to_letter(deck: str) -> Optional[str]:
    """Normalize Ship Manager deck value to A–H so it matches loading condition tabs (Livestock-DK1..DK8)."""
    s = (deck or "").strip().upper()
    if not s:
        return None
    # A–H already
    if s in ("A", "B", "C", "D", "E", "F", "G", "H"):
        return s
    # 1–8 or DK1–DK8
    if s.isdigit() and 1 <= int(s) <= 8:
        return chr(ord("A") + int(s) - 1)
    if s.startswith("DK") and s[2:].strip().isdigit():
        n = int(s[2:].strip())
        if 1 <= n <= 8:
            return chr(ord("A") + n - 1)
    return s if s in ("A", "B", "C", "D", "E", "F", "G", "H") else None


class ConditionTableWidget(QWidget):
    """
    Tabbed table widget showing livestock pens and tanks by category (CargoMax-style).
    
    Tabs: Livestock-DK1..DK8, Water Ballast, Fresh Water, Heavy Fuel Oil, Diesel Oil,
    Lube Oil, Gray Water, Misc. Tanks, Dung, Fodder Hold, Misc. Weights, Spaces, All, Selected.
    Use the '+' button to add tanks/pens (define them in Tools → Ship & data setup).
    """

    add_requested = pyqtSignal()  # Emitted when user clicks '+' (e.g. open Ship & data setup)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        
        self._tabs = QTabWidget(self)
        self._table_widgets: Dict[str, QTableWidget] = {}
        
        self._create_tabs()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)
        
        # Bottom bar: totals label + Add button (like CargoMax reference)
        bottom = QHBoxLayout()
        self._totals_label = QLabel("Totals", self)
        self._totals_label.setStyleSheet("color: #555; font-weight: bold;")
        bottom.addWidget(self._totals_label)
        bottom.addStretch()
        self._add_btn = QPushButton("+", self)
        self._add_btn.setFixedSize(32, 28)
        self._add_btn.setToolTip("Add tank or pen – define in Tools → Ship & data setup, then they appear here")
        self._add_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-size: 16px; font-weight: bold; border: none; border-radius: 3px; } QPushButton:hover { background-color: #45a049; }")
        self._add_btn.clicked.connect(self._on_add_clicked)
        bottom.addWidget(self._add_btn)
        layout.addLayout(bottom)
        
    def _on_add_clicked(self) -> None:
        """User clicked + to add tank/pen; main window can open Ship & data setup."""
        self.add_requested.emit()
        
    def _create_tabs(self) -> None:
        """Create all category tabs (names match reference: Livestock-DK1..DK8, then tank categories)."""
        for deck_num in range(1, 9):
            tab_name = f"Livestock-DK{deck_num}"
            deck_letter = chr(ord("A") + deck_num - 1)
            table = self._create_table()
            self._table_widgets[tab_name] = table
            self._tabs.addTab(table, f"{tab_name} (Deck {deck_letter})")
            
        tank_categories = [
            "Water Ballast", "Fresh Water", "Heavy Fuel Oil", "Diesel Oil",
            "Lube Oil", "Gray Water", "Misc. Tanks", "Dung", "Fodder Hold",
        ]
        for cat in tank_categories:
            table = self._create_tank_table()
            self._table_widgets[cat] = table
            self._tabs.addTab(table, cat)
            
        for tab_name in ["Misc. Weights", "Spaces", "All", "Selected"]:
            table = self._create_table()
            self._table_widgets[tab_name] = table
            self._tabs.addTab(table, tab_name)
            
    def _create_table(self) -> QTableWidget:
        """Create a table with livestock column structure (pens)."""
        table = QTableWidget(self)
        table.setColumnCount(14)
        table.setHorizontalHeaderLabels([
            "Name",
            "Cargo",
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
        self._setup_common_table(table)
        return table

    # Tank table column indices (reference: green indicator, Name, Ull/Snd, UTrim, Capacity, %Full, Volume, Dens, Weight, VCG, LCG, TCG, FSopt, FSt)
    TANK_COL_NAME = 1
    TANK_COL_ULL_SND = 2
    TANK_COL_UTRIM = 3
    TANK_COL_CAPACITY = 4
    TANK_COL_PCT_FULL = 5
    TANK_COL_VOLUME = 6
    TANK_COL_DENS = 7
    TANK_COL_WEIGHT = 8
    TANK_COL_VCG = 9
    TANK_COL_LCG = 10
    TANK_COL_TCG = 11
    TANK_COL_FSOPT = 12
    TANK_COL_FST = 13

    def _create_tank_table(self) -> QTableWidget:
        """Create a table with tank columns: [indicator], Name, Ull/Snd m, UTrim m, Capacity m3, %Full, Volume m3, Dens MT/m3, Weight MT, VCG m-BL, LCG m-[FR], TCG m-CL, FSopt, FSt m-MT."""
        table = QTableWidget(self)
        table.setColumnCount(14)
        table.setHorizontalHeaderLabels([
            "",           # Green indicator column
            "Name",
            "Ull/Snd\n(m)",
            "UTrim\n(m)",
            "Capacity\n(m3)",
            "%Full\n(%)",
            "Volume\n(m3)",
            "Dens\n(MT/m3)",
            "Weight\n(MT)",
            "VCG\n(m-BL)",
            "LCG\n(m-[FR])",
            "TCG\n(m-CL)",
            "FSopt",
            "FSt\n(m-MT)",
        ])
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 28)  # Narrow indicator column (green in reference)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._setup_common_table(table)
        return table

    def _setup_common_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
    def update_data(
        self,
        pens: List[LivestockPen],
        tanks: List[Tank],
        pen_loadings: Dict[int, int],
        tank_volumes: Dict[int, float],
        cargo_type: Any = None,
        cargo_type_names: Optional[List[str]] = None,
    ) -> None:
        """
        Update all tables with current pens and tanks data.
        If cargo_type is set, uses its avg_weight_per_head_kg and deck_area_per_head_m2 for dynamic pen calculations.
        If cargo_type_names is set, the Cargo column is a dropdown filled from the cargo library.
        """
        # Clear all tables first
        for table in self._table_widgets.values():
            table.setRowCount(0)
            
        mass_per_head_t = (
            (getattr(cargo_type, "avg_weight_per_head_kg", 520.0) or 520.0) / 1000.0
            if cargo_type else MASS_PER_HEAD_T
        )
        area_per_head_from_cargo = (
            getattr(cargo_type, "deck_area_per_head_m2", None) if cargo_type else None
        )
        cargo_name = (cargo_type.name or "Livestock").strip() if cargo_type else "Livestock"

        # Update livestock deck tabs
        for deck_num in range(1, 9):
            tab_name = f"Livestock-DK{deck_num}"
            deck_letter = chr(ord('A') + deck_num - 1)  # A-H
            self._populate_livestock_tab(
                tab_name, pens, pen_loadings, deck_letter,
                mass_per_head_t=mass_per_head_t,
                area_per_head_from_cargo=area_per_head_from_cargo,
                cargo_name=cargo_name,
                cargo_type_names=cargo_type_names,
            )
            
        # Update tank category tabs
        self._populate_tank_tabs(tanks, tank_volumes)
        
        # Update "All" tab
        self._populate_all_tab(
            pens, tanks, pen_loadings, tank_volumes,
            mass_per_head_t=mass_per_head_t,
            area_per_head_from_cargo=area_per_head_from_cargo,
            cargo_name=cargo_name,
            cargo_type_names=cargo_type_names,
        )
        
    def _populate_livestock_tab(
        self,
        tab_name: str,
        pens: List[LivestockPen],
        pen_loadings: Dict[int, int],
        deck_letter: str,
        mass_per_head_t: float = MASS_PER_HEAD_T,
        area_per_head_from_cargo: Optional[float] = None,
        cargo_name: str = "Livestock",
        cargo_type_names: Optional[List[str]] = None,
    ) -> None:
        """Populate a livestock deck tab with pens for that deck. Cargo column is dropdown from library if cargo_type_names provided."""
        table = self._table_widgets.get(tab_name)
        if not table:
            return
            
        deck_letter_upper = deck_letter.upper()
        deck_pens = [
            p for p in pens
            if _deck_to_letter(p.deck or "") == deck_letter_upper
        ]
        
        total_weight = 0.0
        total_area_used = 0.0
        total_area = 0.0
        
        for pen in deck_pens:
            row = table.rowCount()
            table.insertRow(row)
            
            heads = pen_loadings.get(pen.id or -1, 0)
            weight_mt = heads * mass_per_head_t
            total_weight += weight_mt
            
            area_used = pen.area_m2 if heads > 0 else 0.0
            total_area_used += area_used
            total_area += pen.area_m2
            
            head_pct = (heads / pen.capacity_head * 100.0) if pen.capacity_head > 0 else 0.0
            if area_per_head_from_cargo is not None:
                area_per_head = area_per_head_from_cargo
            else:
                area_per_head = pen.area_m2 / heads if heads > 0 else 0.0
            
            # LCG moment (simplified - would need ship length for normalization)
            lcg_moment = weight_mt * pen.lcg_m
            
            table.setItem(row, 0, QTableWidgetItem(pen.name))
            if cargo_type_names:
                combo = QComboBox(table)
                combo.addItems(cargo_type_names)
                if cargo_name in cargo_type_names:
                    combo.setCurrentText(cargo_name)
                elif cargo_type_names:
                    combo.setCurrentIndex(0)
                table.setCellWidget(row, 1, combo)
            else:
                table.setItem(row, 1, QTableWidgetItem(cargo_name))
            table.setItem(row, 2, QTableWidgetItem(str(heads)))
            table.setItem(row, 3, QTableWidgetItem(f"{head_pct:.1f}"))
            table.setItem(row, 4, QTableWidgetItem(str(pen.capacity_head)))
            table.setItem(row, 5, QTableWidgetItem(f"{area_used:.2f}"))
            table.setItem(row, 6, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            table.setItem(row, 7, QTableWidgetItem(f"{area_per_head:.2f}"))
            table.setItem(row, 8, QTableWidgetItem(f"{mass_per_head_t:.2f}"))
            table.setItem(row, 9, QTableWidgetItem(f"{weight_mt:.2f}"))
            table.setItem(row, 10, QTableWidgetItem(f"{pen.vcg_m:.3f}"))
            table.setItem(row, 11, QTableWidgetItem(f"{pen.lcg_m:.3f}"))
            table.setItem(row, 12, QTableWidgetItem(f"{pen.tcg_m:.3f}"))
            table.setItem(row, 13, QTableWidgetItem(f"{lcg_moment:.2f}"))
            
        # Add totals row
        if deck_pens:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(f"{tab_name} Totals"))
            table.setItem(row, 1, QTableWidgetItem(""))
            table.setItem(row, 2, QTableWidgetItem(""))
            table.setItem(row, 3, QTableWidgetItem(""))
            table.setItem(row, 4, QTableWidgetItem(""))
            table.setItem(row, 5, QTableWidgetItem(f"{total_area_used:.2f}"))
            table.setItem(row, 6, QTableWidgetItem(f"{total_area:.2f}"))
            table.setItem(row, 7, QTableWidgetItem(""))
            table.setItem(row, 8, QTableWidgetItem(""))
            table.setItem(row, 9, QTableWidgetItem(f"{total_weight:.2f}"))
            table.setItem(row, 10, QTableWidgetItem(""))
            table.setItem(row, 11, QTableWidgetItem(""))
            table.setItem(row, 12, QTableWidgetItem(""))
            table.setItem(row, 13, QTableWidgetItem(""))
            
    def _populate_tank_tabs(
        self,
        tanks: List[Tank],
        tank_volumes: Dict[int, float],
    ) -> None:
        """Populate each tank category tab by tank category (Storing dropdown in Ship Manager)."""
        for cat in TANK_CATEGORY_NAMES:
            table = self._table_widgets.get(cat)
            if not table:
                continue
            allowed_types = TANK_CATEGORY_TYPES.get(cat, [])
            # Match by tank.category (Ship Manager "Storing"); fall back to tank_type for old data
            cat_tanks = []
            for t in tanks:
                tcat = (getattr(t, "category", None) or "").strip()
                if tcat:
                    if tcat == cat:
                        cat_tanks.append(t)
                elif t.tank_type in allowed_types:
                    cat_tanks.append(t)
            total_cap = 0.0
            total_vol = 0.0
            total_weight = 0.0
            for tank in cat_tanks:
                row = table.rowCount()
                table.insertRow(row)
                vol = tank_volumes.get(tank.id or -1, 0.0)
                fill_pct = (vol / tank.capacity_m3 * 100.0) if tank.capacity_m3 > 0 else 0.0
                dens = getattr(tank, "density_t_per_m3", 1.025) or 1.025
                weight_mt = vol * dens
                total_cap += tank.capacity_m3
                total_vol += vol
                total_weight += weight_mt
                vcg = getattr(tank, "kg_m", 0.0) or 0.0
                # Column 0: green indicator (empty cell; header is styled green)
                table.setItem(row, 0, QTableWidgetItem(""))
                table.setItem(row, self.TANK_COL_NAME, QTableWidgetItem(tank.name))
                table.setItem(row, self.TANK_COL_ULL_SND, QTableWidgetItem(""))   # Ullage/Sounding – optional
                table.setItem(row, self.TANK_COL_UTRIM, QTableWidgetItem(""))    # UTrim – optional
                table.setItem(row, self.TANK_COL_CAPACITY, QTableWidgetItem(f"{tank.capacity_m3:.2f}"))
                table.setItem(row, self.TANK_COL_PCT_FULL, QTableWidgetItem(f"{fill_pct:.1f}"))
                table.setItem(row, self.TANK_COL_VOLUME, QTableWidgetItem(f"{vol:.2f}"))
                table.setItem(row, self.TANK_COL_DENS, QTableWidgetItem(f"{dens:.3f}"))
                table.setItem(row, self.TANK_COL_WEIGHT, QTableWidgetItem(f"{weight_mt:.2f}"))
                table.setItem(row, self.TANK_COL_VCG, QTableWidgetItem(f"{vcg:.3f}"))
                table.setItem(row, self.TANK_COL_LCG, QTableWidgetItem(f"{tank.lcg_m:.3f}"))
                table.setItem(row, self.TANK_COL_TCG, QTableWidgetItem(f"{tank.tcg_m:.3f}"))
                table.setItem(row, self.TANK_COL_FSOPT, QTableWidgetItem(""))    # Free surface option
                table.setItem(row, self.TANK_COL_FST, QTableWidgetItem(""))     # Free surface moment
            if cat_tanks:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(""))
                table.setItem(row, self.TANK_COL_NAME, QTableWidgetItem(f"{cat} Totals"))
                for c in (self.TANK_COL_ULL_SND, self.TANK_COL_UTRIM, self.TANK_COL_PCT_FULL,
                          self.TANK_COL_DENS, self.TANK_COL_VCG, self.TANK_COL_LCG,
                          self.TANK_COL_TCG, self.TANK_COL_FSOPT, self.TANK_COL_FST):
                    table.setItem(row, c, QTableWidgetItem(""))
                table.setItem(row, self.TANK_COL_CAPACITY, QTableWidgetItem(f"{total_cap:.2f}"))
                table.setItem(row, self.TANK_COL_VOLUME, QTableWidgetItem(f"{total_vol:.2f}"))
                table.setItem(row, self.TANK_COL_WEIGHT, QTableWidgetItem(f"{total_weight:.2f}"))
            
    def _populate_all_tab(
        self,
        pens: List[LivestockPen],
        tanks: List[Tank],
        pen_loadings: Dict[int, int],
        tank_volumes: Dict[int, float],
        mass_per_head_t: float = MASS_PER_HEAD_T,
        area_per_head_from_cargo: Optional[float] = None,
        cargo_name: str = "Livestock",
        cargo_type_names: Optional[List[str]] = None,
    ) -> None:
        """Populate the 'All' tab with everything. Cargo column is dropdown from library for pen rows if cargo_type_names provided."""
        all_table = self._table_widgets.get("All")
        if not all_table:
            return
            
        # Add all pens
        for pen in pens:
            heads = pen_loadings.get(pen.id or -1, 0)
            if heads == 0:
                continue
                
            row = all_table.rowCount()
            all_table.insertRow(row)
            
            weight_mt = heads * mass_per_head_t
            head_pct = (heads / pen.capacity_head * 100.0) if pen.capacity_head > 0 else 0.0
            if area_per_head_from_cargo is not None:
                area_per_head = area_per_head_from_cargo
            else:
                area_per_head = pen.area_m2 / heads if heads > 0 else 0.0
            lcg_moment = weight_mt * pen.lcg_m
            
            all_table.setItem(row, 0, QTableWidgetItem(pen.name))
            if cargo_type_names:
                combo = QComboBox(all_table)
                combo.addItems(cargo_type_names)
                if cargo_name in cargo_type_names:
                    combo.setCurrentText(cargo_name)
                elif cargo_type_names:
                    combo.setCurrentIndex(0)
                all_table.setCellWidget(row, 1, combo)
            else:
                all_table.setItem(row, 1, QTableWidgetItem(cargo_name))
            all_table.setItem(row, 2, QTableWidgetItem(str(heads)))
            all_table.setItem(row, 3, QTableWidgetItem(f"{head_pct:.1f}"))
            all_table.setItem(row, 4, QTableWidgetItem(str(pen.capacity_head)))
            all_table.setItem(row, 5, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            all_table.setItem(row, 6, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            all_table.setItem(row, 7, QTableWidgetItem(f"{area_per_head:.2f}"))
            all_table.setItem(row, 8, QTableWidgetItem(f"{mass_per_head_t:.2f}"))
            all_table.setItem(row, 9, QTableWidgetItem(f"{weight_mt:.2f}"))
            all_table.setItem(row, 10, QTableWidgetItem(f"{pen.vcg_m:.3f}"))
            all_table.setItem(row, 11, QTableWidgetItem(f"{pen.lcg_m:.3f}"))
            all_table.setItem(row, 12, QTableWidgetItem(f"{pen.tcg_m:.3f}"))
            all_table.setItem(row, 13, QTableWidgetItem(f"{lcg_moment:.2f}"))
            
        # Add all tanks
        for tank in tanks:
            vol = tank_volumes.get(tank.id or -1, 0.0)
            if vol == 0.0:
                continue
                
            row = all_table.rowCount()
            all_table.insertRow(row)
            
            fill_pct = (vol / tank.capacity_m3 * 100.0) if tank.capacity_m3 > 0 else 0.0
            weight_mt = vol * 1.025
            
            all_table.setItem(row, 0, QTableWidgetItem(tank.name))
            all_table.setItem(row, 1, QTableWidgetItem("Tank"))
            all_table.setItem(row, 2, QTableWidgetItem(""))
            all_table.setItem(row, 3, QTableWidgetItem(f"{fill_pct:.1f}"))
            all_table.setItem(row, 4, QTableWidgetItem(f"{tank.capacity_m3:.2f}"))
            all_table.setItem(row, 5, QTableWidgetItem(""))
            all_table.setItem(row, 6, QTableWidgetItem(""))
            all_table.setItem(row, 7, QTableWidgetItem(""))
            all_table.setItem(row, 8, QTableWidgetItem(""))
            all_table.setItem(row, 9, QTableWidgetItem(f"{weight_mt:.2f}"))
            all_table.setItem(row, 10, QTableWidgetItem(""))
            all_table.setItem(row, 11, QTableWidgetItem(f"{tank.longitudinal_pos:.3f}"))
            all_table.setItem(row, 12, QTableWidgetItem(""))
            all_table.setItem(row, 13, QTableWidgetItem(""))
