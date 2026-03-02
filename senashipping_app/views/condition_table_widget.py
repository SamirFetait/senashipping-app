"""
Tabbed table widget for displaying livestock pens and tanks by category.

Matches the reference UI with tabs for each deck, tank type, etc.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtWidgets import (
    QApplication,
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
    QStyledItemDelegate,
    QLineEdit,
)
from PyQt6.QtGui import QDoubleValidator, QKeyEvent

from senashipping_app.models import Tank, LivestockPen
from senashipping_app.models.tank import TankType
from senashipping_app.utils.sorting import get_pen_sort_key, get_tank_sort_key
from senashipping_app.repositories import database
from senashipping_app.repositories.livestock_pen_repository import LivestockPenRepository


MASS_PER_HEAD_T = 0.5  # Average mass per head in tonnes

# Map tank category tab name -> TankType(s) for filtering. Same list used in Ship Manager "Storing" dropdown.
TANK_CATEGORY_TYPES: Dict[str, List[TankType]] = {
    "Water Ballast": [TankType.BALLAST],
    "Fresh Water": [TankType.FRESH_WATER],
    "Heavy Fuel Oil": [TankType.FUEL],
    "Diesel Oil": [TankType.FUEL],
    "Lube Oil": [TankType.OTHER],
    "Misc. Tanks": [TankType.CARGO],
    "Dung": [],       # Pens for dung (optional; define in Ship & data setup)
    "Fodder Hold": [TankType.CARGO],
    "Spaces": [TankType.CARGO],  # Spaces category for tanks
}
TANK_CATEGORY_NAMES: List[str] = list(TANK_CATEGORY_TYPES.keys())


class _NumericItemDelegate(QStyledItemDelegate):
    """
    Delegate that restricts editing to numeric input only (floating-point).
    Used for all tank and pen numeric columns so users cannot type text.
    """

    def __init__(self, allow_negative: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allow_negative = allow_negative

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        validator = QDoubleValidator(parent)
        if not self._allow_negative:
            validator.setBottom(0.0)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setDecimals(6)
        editor.setValidator(validator)
        return editor


def _deck_to_letter(deck: str) -> Optional[str]:
    """Normalize Ship Manager deck value to AΓÇôH so it matches loading condition tabs (Livestock-DK1..DK8)."""
    s = (deck or "").strip().upper()
    if not s:
        return None
    # AΓÇôH already
    if s in ("A", "B", "C", "D", "E", "F", "G", "H"):
        return s
    # 1ΓÇô8 or DK1ΓÇôDK8
    if s.isdigit() and 1 <= int(s) <= 8:
        return chr(ord("A") + int(s) - 1)
    if s.startswith("DK") and s[2:].strip().isdigit():
        n = int(s[2:].strip())
        if 1 <= n <= 8:
            return chr(ord("A") + n - 1)
    return s if s in ("A", "B", "C", "D", "E", "F", "G", "H") else None


class ConditionTableWidget(QWidget):
    """
    Tabbed table widget showing livestock pens and tanks by category (SenaShipping-style).
    
    Tabs: Livestock-DK1..DK8, Water Ballast, Fresh Water, Heavy Fuel Oil, Diesel Oil,
    Lube Oil, Misc. Tanks, Dung, Fodder Hold, Spaces, All.
    Use the '+' button to add tanks/pens (define them in Tools ΓåÆ Ship & data setup).
    """

    add_requested = pyqtSignal()  # Emitted when user clicks '+' (e.g. open Ship & data setup)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        
        self._tabs = QTabWidget(self)
        # Enable scroll buttons for tabs when they don't fit
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self._table_widgets: Dict[str, QTableWidget] = {}
        self._cargo_header_combos: Dict[str, QComboBox] = {}  # tab_name -> cargo header combo
        self._current_pens: List[LivestockPen] = []
        self._current_cargo_types: List[Any] = []
        self._current_ship_id: Optional[int] = None
        self._skip_item_changed = False
        self._syncing_selection = False  # Flag to prevent infinite loops during selection sync
        self._deck_profile_widget = None  # Will be set by parent view
        # Optional callback (tank_id, volume_m3) -> (vcg_m, lcg_m, tcg_m) | None for sounding-based CoG display
        self._tank_cog_callback: Optional[Callable[[int, float], Optional[Tuple[float, float, float]]]] = None
        # Fallback when sounding returns None: (tank_id) -> (vcg_m, lcg_m, tcg_m) so VCG/LCG/TCG still update
        self._tank_default_cog_callback: Optional[Callable[[int], Tuple[float, float, float]]] = None
        # (tank_id, volume_m3) -> (ullage_m, fsm_mt) so UII/Snd and FSt update from volume like VCG/LCG/TCG
        self._tank_ullage_fsm_callback: Optional[Callable[[int, float], Tuple[Optional[float], Optional[float]]]] = None
        # Ullage (m) and FSM (tonne.m) from Excel: tank_id -> (ullage_m, fsm_mt); fallback when callback returns None
        self._tank_ullage_fsm: Dict[int, Tuple[float, float]] = {}

        self._create_tabs()
        
        # Connect tab changes to sync deck layout
        self._tabs.currentChanged.connect(self._on_tab_changed)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)
        
        # Bottom bar: totals label + Add button (like SenaShipping reference)
        bottom = QHBoxLayout()
        self._totals_label = QLabel("Totals", self)
        self._totals_label.setStyleSheet("color: #555; font-weight: bold;")
        bottom.addWidget(self._totals_label)
        bottom.addStretch()

        # TODO: Add button to add tank or pen
        # self._add_btn = QPushButton("+", self)
        # self._add_btn.setFixedSize(32, 28)
        # self._add_btn.setToolTip("Add tank or pen ΓÇô define in Tools ΓåÆ Ship & data setup, then they appear here")
        # self._add_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-size: 16px; font-weight: bold; border: none; border-radius: 3px; } QPushButton:hover { background-color: #45a049; }")
        # self._add_btn.clicked.connect(self._on_add_clicked)
        # bottom.addWidget(self._add_btn)
        layout.addLayout(bottom)
        
    def _on_add_clicked(self) -> None:
        """User clicked + to add tank/pen; main window can open Ship & data setup."""
        self.add_requested.emit()
        
    def _create_tabs(self) -> None:
        """Create all category tabs (names match reference: Livestock-DK1..DK8, then tank categories)."""
        for deck_num in range(1, 9):
            tab_name = f"Livestock-DK{deck_num}"
            deck_letter = chr(ord("A") + deck_num - 1)
            if deck_num == 8:
                table = self._create_deck8_table()
                self._table_widgets[tab_name] = table
                self._tabs.addTab(table, f"{tab_name} (Deck {deck_letter})")
            else:
                # Create table with header dropdown for deck tables (DK1-DK7)
                table_widget = self._create_table_with_header(tab_name)
                self._table_widgets[tab_name] = table_widget._table
                self._tabs.addTab(table_widget, f"{tab_name} (Deck {deck_letter})")
            
        tank_categories = [
            "Water Ballast", "Fresh Water", "Heavy Fuel Oil", "Diesel Oil",
            "Lube Oil", "Misc. Tanks", "Dung", "Fodder Hold", "Spaces",
        ]
        for cat in tank_categories:
            table = self._create_tank_table()
            self._table_widgets[cat] = table
            self._tabs.addTab(table, cat)

        # "All" tab: custom table with extra Deck column
        all_table = self._create_all_table()
        self._table_widgets["All"] = all_table
        self._tabs.addTab(all_table, "All")
            
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

        # Default: pens table cells are numeric-only, except Name and Cargo.
        numeric_delegate = _NumericItemDelegate(allow_negative=False, parent=table)
        table.setItemDelegate(numeric_delegate)
        text_delegate = QStyledItemDelegate(table)
        table.setItemDelegateForColumn(0, text_delegate)  # Name
        table.setItemDelegateForColumn(1, text_delegate)  # Cargo
        return table

    def _create_all_table(self) -> QTableWidget:
        """Create the 'All' tab table with Deck column after Name. Read-only, pens only (no tanks)."""
        table = QTableWidget(self)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setColumnCount(15)
        table.setHorizontalHeaderLabels([
            "Name",
            "Deck",
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
    
    def _create_table_with_header(self, tab_name: str) -> QWidget:
        """Create a table widget with a header combo box for Cargo column."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Header row with combo box aligned to Cargo column
        header_widget = QWidget(container)
        header_widget.setFixedHeight(30)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(4)
        
        # Label for Name column
        name_label = QLabel("Name", header_widget)
        name_label.setMinimumWidth(100)
        header_layout.addWidget(name_label)
        
        # Cargo combo box in header (aligned with Cargo column)
        cargo_label = QLabel("Cargo:", header_widget)
        header_layout.addWidget(cargo_label)
        cargo_combo = QComboBox(header_widget)
        cargo_combo.setMinimumWidth(150)
        cargo_combo.setToolTip("Select cargo to apply to all rows in this table")
        cargo_combo.addItem("-- Apply to All --")  # Default option
        cargo_combo.currentTextChanged.connect(
            lambda cargo: self._on_header_cargo_changed(tab_name, cargo)
        )
        self._cargo_header_combos[tab_name] = cargo_combo
        header_layout.addWidget(cargo_combo)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        # Table below header
        table = self._create_table()
        layout.addWidget(table)
        
        # Store table reference for easy access
        container._table = table
        
        # Connect table column resize to sync header layout if needed
        def sync_header_widths():
            # Update header widget width to match table
            header_widget.setMinimumWidth(table.width())
        table.horizontalHeader().sectionResized.connect(sync_header_widths)
        
        return container

    def _create_deck8_table(self) -> QTableWidget:
        """Create deck 8 table: Name, Quantity, Weight (MT), Total Weight (MT), VCG m-BL, LCG m-[FR], TCG m-CL, LS Moment m-MT, Delete."""
        table = QTableWidget(self)
        table.setColumnCount(self.DECK8_COLUMNS)
        table.setHorizontalHeaderLabels([
            "Name",
            "Quantity",
            "Weight (MT)",
            "Total Weight (MT)",
            "VCG m-BL",
            "LCG m-[FR]",
            "TCG m-CL",
            "LS Moment m-MT",
            "",
        ])
        self._setup_common_table(table)
        header = table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(self.DECK8_COL_DELETE, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(self.DECK8_COL_DELETE, 120)

        # Deck 8 table: all editable columns except Name are numeric-only; column 8 is Delete button.
        numeric_delegate = _NumericItemDelegate(allow_negative=False, parent=table)
        table.setItemDelegate(numeric_delegate)
        text_delegate = QStyledItemDelegate(table)
        table.setItemDelegateForColumn(0, text_delegate)  # Name
        return table

    # Deck 8 (Deck H) table: 9 columns including Delete button for full CRUD
    DECK8_COLUMNS = 9
    DECK8_COL_DELETE = 8

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

        # Tank tables: all editable columns are numeric-only, except indicator and Name.
        numeric_delegate = _NumericItemDelegate(allow_negative=True, parent=table)
        table.setItemDelegate(numeric_delegate)
        text_delegate = QStyledItemDelegate(table)
        table.setItemDelegateForColumn(0, text_delegate)  # Indicator
        table.setItemDelegateForColumn(1, text_delegate)  # Name
        return table

    def _setup_common_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)  # Allow multi-selection (Ctrl+click, Shift+click)
        # Minimum row height so cell widgets (e.g. QComboBox) never get zero-size paint device (QPainter engine == 0)
        vh = table.verticalHeader()
        if vh is not None:
            vh.setDefaultSectionSize(max(vh.defaultSectionSize(), 24))
        # Connect selection changes to sync with deck layout
        table.itemSelectionChanged.connect(lambda: self._on_table_selection_changed(table))
        table.installEventFilter(self)  # ESC to clear selection
    
    def set_tank_cog_callback(self, callback: Optional[Callable[[int, float], Optional[Tuple[float, float, float]]]]) -> None:
        """Set callback to get (VCG, LCG, TCG) for display when sounding table is used. (tank_id, volume_m3) -> (vcg_m, lcg_m, tcg_m) or None."""
        self._tank_cog_callback = callback

    def set_tank_default_cog_callback(self, callback: Optional[Callable[[int], Tuple[float, float, float]]]) -> None:
        """Set fallback (tank_id) -> (vcg_m, lcg_m, tcg_m) when sounding returns None, so VCG/LCG/TCG still update when weight changes."""
        self._tank_default_cog_callback = callback

    def set_tank_ullage_fsm_callback(self, callback: Optional[Callable[[int, float], Tuple[Optional[float], Optional[float]]]]) -> None:
        """Set callback (tank_id, volume_m3) -> (ullage_m, fsm_mt) so UII/Snd and FSt update when volume changes, like VCG/LCG/TCG."""
        self._tank_ullage_fsm_callback = callback

    def get_tank_volumes_from_tables(self) -> Dict[int, float]:
        """Read current Volume (m³) per tank from all tank category tables. Used so Compute/Save use the same volumes as shown (real volume → dynamic CG from sounding)."""
        out: Dict[int, float] = {}
        for cat in TANK_CATEGORY_NAMES:
            table = self._table_widgets.get(cat)
            if not table:
                continue
            for row in range(table.rowCount()):
                name_item = table.item(row, self.TANK_COL_NAME)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue
                tank_id = name_item.data(Qt.ItemDataRole.UserRole)
                if tank_id is None:
                    continue
                vol_item = table.item(row, self.TANK_COL_VOLUME)
                if not vol_item:
                    continue
                try:
                    vol = float((vol_item.text() or "0").strip())
                except (TypeError, ValueError):
                    vol = 0.0
                out[int(tank_id)] = max(0.0, vol)
        return out

    def get_pen_loadings_from_tables(self) -> Dict[int, int]:
        """Read current head count per pen from Livestock-DK1..DK8 deck tabs only. The All tab is UI-only and must not affect calculations (to avoid double-counting)."""
        out: Dict[int, int] = {}
        for deck_num in range(1, 9):
            tab_name = f"Livestock-DK{deck_num}"
            table = self._table_widgets.get(tab_name)
            if not table:
                continue
            is_deck8 = deck_num == 8
            # DK1..DK7: col 0 = name (pen id), col 2 = # Head; DK8: col 0 = name (pen id), col 1 = Quantity
            head_col = 1 if is_deck8 else 2
            for row in range(table.rowCount()):
                name_item = table.item(row, 0)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue
                pen_id = name_item.data(Qt.ItemDataRole.UserRole)
                if pen_id is None:
                    continue
                head_item = table.item(row, head_col)
                if not head_item:
                    continue
                try:
                    heads = int(float((head_item.text() or "0").strip()))
                except (ValueError, TypeError):
                    heads = 0
                heads = max(0, heads)
                out[int(pen_id)] = heads
        return out

    # ------------------------------------------------------------------
    # Public helpers for Edit menu operations (via ConditionEditorView)
    # ------------------------------------------------------------------

    def _current_table_for_edit(self) -> Optional[QTableWidget]:
        """Return the QTableWidget in the currently selected tab, if any."""
        widget = self._tabs.currentWidget()
        if isinstance(widget, QTableWidget):
            return widget
        if isinstance(widget, QWidget):
            return widget.findChild(QTableWidget)
        return None

    def edit_selected_item(self) -> None:
        """Begin editing the currently selected cell in the active table."""
        table = self._current_table_for_edit()
        if not table:
            return
        item = table.currentItem()
        if item is None and table.rowCount() > 0 and table.columnCount() > 0:
            table.setCurrentCell(0, 0)
            item = table.currentItem()
        if item is not None:
            table.editItem(item)

    def select_all_items(self) -> None:
        """Select all rows in the active table."""
        table = self._current_table_for_edit()
        if not table:
            return
        table.selectAll()

    def clear_selection(self) -> None:
        """Clear selection in the active table."""
        table = self._current_table_for_edit()
        if not table:
            return
        table.clearSelection()

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """ESC clears selection in any table."""
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and obj in self._table_widgets.values()
        ):
            self.clear_selection()
            return True
        return super().eventFilter(obj, event)

    def clear_selected_items(self) -> None:
        """
        Clear load for selected items in the active table.

        - On livestock deck tabs (Livestock-DK1..DK8): set head count to 0
          for selected pens.
        - On tank category tabs: set selected tanks to empty (0% full).
        """
        table = self._current_table_for_edit()
        if not table:
            return
        index = self._tabs.currentIndex()
        tab_text = self._tabs.tabText(index)

        # Livestock decks: zero head count in the appropriate column
        if tab_text.startswith("Livestock-DK"):
            is_deck8 = "DK8" in tab_text
            head_col = 1 if is_deck8 else 2
            sel_model = table.selectionModel()
            if not sel_model:
                return
            for idx in sel_model.selectedRows():
                row = idx.row()
                name_item = table.item(row, 0)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue
                head_item = table.item(row, head_col)
                if head_item is None:
                    head_item = QTableWidgetItem("0")
                    table.setItem(row, head_col, head_item)
                else:
                    head_item.setText("0")
            return

        # Tank categories: treat "delete" as emptying the space
        if tab_text in TANK_CATEGORY_NAMES:
            self._set_selected_tank_fill(table, level_pct=0.0)

    def set_selected_tanks_empty(self) -> None:
        """Set selected tanks in the current tank tab to 0% full."""
        table = self._current_table_for_edit()
        if not table:
            return
        index = self._tabs.currentIndex()
        tab_text = self._tabs.tabText(index)
        if tab_text in TANK_CATEGORY_NAMES:
            self._set_selected_tank_fill(table, level_pct=0.0)

    def set_selected_tanks_full(self) -> None:
        """Set selected tanks in the current tank tab to 100% full."""
        table = self._current_table_for_edit()
        if not table:
            return
        index = self._tabs.currentIndex()
        tab_text = self._tabs.tabText(index)
        if tab_text in TANK_CATEGORY_NAMES:
            self._set_selected_tank_fill(table, level_pct=100.0)

    def set_selected_tanks_fill_to(self, level_pct: float) -> None:
        """Set selected tanks in the current tank tab to a given % full (0–100)."""
        table = self._current_table_for_edit()
        if not table:
            return
        index = self._tabs.currentIndex()
        tab_text = self._tabs.tabText(index)
        if tab_text in TANK_CATEGORY_NAMES:
            # Clamp to sensible range
            pct = max(0.0, min(100.0, float(level_pct)))
            self._set_selected_tank_fill(table, level_pct=pct)

    def _set_selected_tank_fill(self, table: QTableWidget, level_pct: Optional[float]) -> None:
        """
        Helper: set selected tank rows in a tank table to a given % full.

        Implemented by adjusting Weight so that Volume derived from
        Weight/Density matches the requested % of Capacity and then
        reusing the existing recalculation logic.
        """
        sel_model = table.selectionModel()
        if not sel_model:
            return
        for idx in sel_model.selectedRows():
            row = idx.row()
            # Skip totals row
            name_item = table.item(row, self.TANK_COL_NAME)
            if not name_item or "Totals" in (name_item.text() or ""):
                continue
            cap_item = table.item(row, self.TANK_COL_CAPACITY)
            dens_item = table.item(row, self.TANK_COL_DENS)
            if not cap_item or not dens_item:
                continue
            try:
                cap_text = (cap_item.text() or "").strip()
                capacity = float(cap_text) if cap_text else 0.0
            except (TypeError, ValueError):
                capacity = 0.0
            try:
                dens_text = (dens_item.text() or "").strip()
                dens = float(dens_text) if dens_text else 1.025
            except (TypeError, ValueError):
                dens = 1.025

            if not level_pct or level_pct <= 0.0 or capacity <= 0.0 or dens <= 0.0:
                weight_mt = 0.0
            else:
                vol = capacity * (level_pct / 100.0)
                weight_mt = vol * dens

            weight_item = table.item(row, self.TANK_COL_WEIGHT)
            if weight_item is None:
                weight_item = QTableWidgetItem(f"{weight_mt:.3f}")
                table.setItem(row, self.TANK_COL_WEIGHT, weight_item)
            else:
                weight_item.setText(f"{weight_mt:.3f}")

            # Reuse existing logic to update Volume, %Full, CG, Ullage/FSM, and totals.
            self._recalculate_tank_row(table, row)

    def search_by_name(self, term: str) -> bool:
        """
        Search for an item by name in the current tab.

        Returns True if a matching row is found and selected.
        """
        table = self._current_table_for_edit()
        if not table or not term:
            return False
        index = self._tabs.currentIndex()
        tab_text = self._tabs.tabText(index)

        # Determine name column: pens use column 0; tanks use TANK_COL_NAME.
        if tab_text in TANK_CATEGORY_NAMES:
            name_col = self.TANK_COL_NAME
        else:
            name_col = 0

        needle = term.strip().lower()
        for row in range(table.rowCount()):
            item = table.item(row, name_col)
            if not item:
                continue
            text = (item.text() or "").strip().lower()
            if not text or "totals" in text:
                continue
            if needle in text:
                table.setCurrentCell(row, name_col)
                table.scrollToItem(item)
                return True
        return False

    def set_deck_profile_widget(self, deck_profile_widget) -> None:
        """Set reference to deck profile widget for bidirectional synchronization."""
        self._deck_profile_widget = deck_profile_widget
        if deck_profile_widget:
            # Connect deck layout selection changes to update tables
            deck_profile_widget.selection_changed.connect(self._on_deck_layout_selection_changed)
            deck_profile_widget.deck_changed.connect(self._on_deck_changed)
    
    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change - sync deck layout if switching to a deck table, or refresh All table if switching to it."""
        if self._syncing_selection:
            return
        
        # Get the widget for this tab
        widget = self._tabs.widget(index)
        if not widget:
            return
        
        # Check if switching to "All" table - refresh it to sync with deck tables
        tab_text = self._tabs.tabText(index)
        if tab_text == "All":
            # Refresh the All table to sync with current deck table values
            all_table = self._table_widgets.get("All")
            if all_table and self._current_pens:
                # Re-populate All table with current data
                # Get current pens, tanks, and loadings
                pens = self._current_pens
                tanks = []  # Will be populated from update_data call
                pen_loadings = {}
                tank_volumes = {}
                
                # Extract pen_loadings from deck tables
                for tab_name, table in self._table_widgets.items():
                    if tab_name.startswith("Livestock-DK") and tab_name != "Livestock-DK8":
                        for row in range(table.rowCount()):
                            name_item = table.item(row, 0)
                            if not name_item or "Totals" in (name_item.text() or ""):
                                continue
                            pen_id = name_item.data(Qt.ItemDataRole.UserRole)
                            if pen_id:
                                head_item = table.item(row, 2)
                                if head_item:
                                    try:
                                        heads = int(float(head_item.text() or "0"))
                                        pen_loadings[pen_id] = heads
                                    except (ValueError, TypeError):
                                        pass
                
                # Call update_data to refresh All table
                # Note: This will be called with the full data, but we need to trigger a refresh
                # For now, just re-populate the pens section
                self._refresh_all_table_pens(all_table, pens, pen_loadings, self._current_cargo_types)
                return
        
        # Handle deck table tab switching
        if not self._deck_profile_widget:
            return
        
        # Find which deck table this tab corresponds to
        deck_num = None
        for tab_name, table in self._table_widgets.items():
            if tab_name.startswith("Livestock-DK"):
                # Check if this widget contains the table
                if widget == table or (hasattr(widget, "_table") and widget._table == table):
                    try:
                        deck_num = int(tab_name.replace("Livestock-DK", ""))
                        break
                    except ValueError:
                        continue
        
        if deck_num and 1 <= deck_num <= 8:
            deck_letter = chr(ord("A") + deck_num - 1)
            # Switch deck layout to match table
            self._syncing_selection = True
            try:
                # Find the deck tab index in deck profile widget
                deck_tabs = self._deck_profile_widget._deck_tabs
                for i in range(deck_tabs.count()):
                    tab_widget = deck_tabs.widget(i)
                    if hasattr(tab_widget, "_deck_name") and tab_widget._deck_name == deck_letter:
                        deck_tabs.setCurrentIndex(i)
                        break
            finally:
                self._syncing_selection = False
    
    def _refresh_all_table_pens(self, all_table: QTableWidget, pens: List[LivestockPen], pen_loadings: Dict[int, int], cargo_types: Optional[List[Any]] = None) -> None:
        """Refresh pens in the All table by syncing with deck tables."""
        # Clear existing pen rows (keep tanks)
        rows_to_remove = []
        for row in range(all_table.rowCount()):
            item = all_table.item(row, 2)  # Cargo column (col 2) - "Tank" indicates tank row
            if item and item.text() != "Tank":
                rows_to_remove.append(row)
        
        # Remove rows in reverse order to maintain indices
        for row in reversed(rows_to_remove):
            all_table.removeRow(row)
        
        # Re-populate pens from deck tables, sorted by deck first
        def all_table_sort_key(pen: LivestockPen) -> tuple:
            deck_letter = _deck_to_letter(pen.deck or "") or ""
            # Normalize deck to A-H for sorting
            if deck_letter and deck_letter.upper() in ["A", "B", "C", "D", "E", "F", "G", "H"]:
                deck_order = ord(deck_letter.upper())
            else:
                deck_order = 999  # Put invalid decks at end
            # Then use standard pen sort key for secondary sorting
            standard_key = get_pen_sort_key(pen)
            return (deck_order, standard_key[0], standard_key[1], standard_key[2])
        
        sorted_pens = sorted(pens, key=all_table_sort_key)
        for pen in sorted_pens:
            deck_data = self._get_pen_data_from_deck_table(pen, cargo_types)
            
            row = all_table.rowCount()
            all_table.insertRow(row)
            
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            all_table.setItem(row, 0, name_item)
            
            # Deck column (col 1): show normalized deck letter (A-H), read-only
            deck_letter = _deck_to_letter(pen.deck or "") or (pen.deck or "")
            deck_item = QTableWidgetItem(deck_letter)
            deck_item.setFlags(deck_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
            all_table.setItem(row, 1, deck_item)
            
            # Cargo column (col 2): read-only, sync with deck table
            cargo_item = QTableWidgetItem(deck_data.get("cargo", "-- Blank --"))
            cargo_item.setFlags(cargo_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
            all_table.setItem(row, 2, cargo_item)
            
            # All other columns: sync with deck table values (shifted by 1 due to Deck column)
            all_table.setItem(row, 3, QTableWidgetItem(str(deck_data.get("heads", 0))))
            all_table.setItem(row, 4, QTableWidgetItem(f"{deck_data.get('head_pct', 0.0):.2f}"))
            all_table.setItem(row, 5, QTableWidgetItem(str(int(deck_data.get('head_capacity', 0.0)))))
            all_table.setItem(row, 6, QTableWidgetItem(f"{deck_data.get('area_used', 0.0):.2f}"))
            all_table.setItem(row, 7, QTableWidgetItem(f"{pen.area_m2:.2f}"))
            all_table.setItem(row, 8, QTableWidgetItem(f"{deck_data.get('area_per_head', 0.0):.2f}"))
            all_table.setItem(row, 9, QTableWidgetItem(f"{deck_data.get('mass_per_head_t', 0.0):.2f}"))
            all_table.setItem(row, 10, QTableWidgetItem(f"{deck_data.get('weight_mt', 0.0):.2f}"))
            all_table.setItem(row, 11, QTableWidgetItem(f"{deck_data.get('vcg_display', pen.vcg_m):.3f}"))
            all_table.setItem(row, 12, QTableWidgetItem(f"{pen.lcg_m:.3f}"))
            all_table.setItem(row, 13, QTableWidgetItem(f"{pen.tcg_m:.3f}"))
            all_table.setItem(row, 14, QTableWidgetItem(f"{deck_data.get('lcg_moment', 0.0):.2f}"))
    
    def _on_table_selection_changed(self, table: QTableWidget) -> None:
        """Handle table selection change - sync to deck layout."""
        if self._syncing_selection or not self._deck_profile_widget:
            return
        
        # Get selected pen IDs from the table
        selected_pen_ids = set()
        selection_model = table.selectionModel()
        if selection_model:
            selected_rows = selection_model.selectedRows()
            for index in selected_rows:
                row = index.row()
                item = table.item(row, 0)
                if item:
                    pen_id = item.data(Qt.ItemDataRole.UserRole)
                    if pen_id:
                        selected_pen_ids.add(pen_id)
        
        # Update deck layout selection
        self._syncing_selection = True
        try:
            self._deck_profile_widget.set_selected(selected_pen_ids, set())
        finally:
            self._syncing_selection = False
    
    def _on_deck_layout_selection_changed(self, pen_ids: set[int], tank_ids: set[int]) -> None:
        """Handle deck layout selection change - sync to tables (multi-select)."""
        if self._syncing_selection:
            return
        
        self._syncing_selection = True
        try:
            for tab_name, table in self._table_widgets.items():
                if not isinstance(table, QTableWidget):
                    continue
                table.clearSelection()
                # ExtendedSelection + selectRow() only keeps last row; use MultiSelection for programmatic multi-select
                mode = table.selectionMode()
                table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
                for row in range(table.rowCount()):
                    item = table.item(row, 0)
                    if not item:
                        continue
                    pen_id = item.data(Qt.ItemDataRole.UserRole)
                    if pen_id in pen_ids:
                        table.selectRow(row)
                table.setSelectionMode(mode)
        finally:
            self._syncing_selection = False
    
    def _on_deck_changed(self, deck_letter: str) -> None:
        """Handle deck change in deck layout - switch to corresponding table tab."""
        if self._syncing_selection:
            return
        
        # Convert deck letter to deck number (A=1, B=2, ..., H=8)
        deck_num = ord(deck_letter.upper()) - ord("A") + 1
        if 1 <= deck_num <= 8:
            tab_name = f"Livestock-DK{deck_num}"
            # Find and switch to the corresponding tab
            if tab_name in self._table_widgets:
                table = self._table_widgets[tab_name]
                # Find the tab index that contains this table
                for i in range(self._tabs.count()):
                    widget = self._tabs.widget(i)
                    # Check if this widget contains the table
                    if widget == table or (hasattr(widget, "_table") and widget._table == table):
                        self._syncing_selection = True
                        try:
                            self._tabs.setCurrentIndex(i)
                        finally:
                            self._syncing_selection = False
                        break
        
    def update_data(
        self,
        pens: List[LivestockPen],
        tanks: List[Tank],
        pen_loadings: Dict[int, int],
        tank_volumes: Dict[int, float],
        cargo_type: Any = None,
        cargo_type_names: Optional[List[str]] = None,
        cargo_types: Optional[List[Any]] = None,
        ship_id: Optional[int] = None,
        default_cargo_name: Optional[str] = None,
        tank_ullage_fsm: Optional[Dict[int, Tuple[float, float]]] = None,
    ) -> None:
        """
        Update all tables with current pens and tanks data.
        If cargo_type is set, uses its avg_weight_per_head_kg and deck_area_per_head_m2 for dynamic pen calculations.
        If cargo_type_names is set, the Cargo column is a dropdown filled from the cargo library.
        If cargo_types (full CargoType objects) is set, changing Cargo or # Head will recalculate row and totals.
        ship_id is needed to save user-entered deck 8 rows to the database.
        default_cargo_name: Default cargo name to use (defaults to "-- Blank --" if not provided and no cargo_type).
        """
        self._current_pens = pens
        self._current_cargo_types = cargo_types or []
        self._current_ship_id = ship_id
        
        # Preserve all editable data from tables before clearing (so Compute does not reset any column)
        preserved_cargo_selections: Dict[int, str] = {}  # pen_id -> cargo_name
        preserved_head_counts: Dict[int, int] = {}  # pen_id -> head_count
        preserved_pen_rows: Dict[int, Dict[int, str]] = {}  # pen_id -> {col_index: cell_text} for cols 2,3,4,5,7,8,9,10,11,12,13
        preserved_tank_weights: Dict[int, float] = {}  # tank_id -> weight_mt
        
        # Preserve livestock pen data (cargo, head counts, and full row for decks 1-7)
        for deck_num in range(1, 9):
            tab_name = f"Livestock-DK{deck_num}"
            table = self._table_widgets.get(tab_name)
            if table:
                for row in range(table.rowCount()):
                    name_item = table.item(row, 0)
                    if not name_item:
                        continue
                    pen_id = name_item.data(Qt.ItemDataRole.UserRole)
                    if pen_id is None:
                        continue
                    if "Totals" in (name_item.text() or ""):
                        continue
                    
                    # Get cargo selection from combo box (column 1)
                    cargo_combo = table.cellWidget(row, 1)
                    if isinstance(cargo_combo, QComboBox):
                        cargo_text = cargo_combo.currentText()
                        if cargo_text:
                            preserved_cargo_selections[pen_id] = cargo_text
                    
                    # Get head count (column 2 for decks 1-7, column 1 for deck 8)
                    if deck_num == 8:
                        head_item = table.item(row, 1)  # Quantity column
                    else:
                        head_item = table.item(row, 2)  # # Head column
                    if head_item:
                        try:
                            head_count = int(float(head_item.text()))
                            if head_count > 0:
                                preserved_head_counts[pen_id] = head_count
                        except (ValueError, TypeError):
                            pass
                    
                    # Preserve all data columns for decks 1-7 (2,3,4,5,7,8,9,10,11,12,13) so Compute does not reset them
                    if deck_num != 8 and table.columnCount() >= 14:
                        row_data: Dict[int, str] = {}
                        for col in (2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13):
                            item = table.item(row, col)
                            row_data[col] = (item.text() or "0").strip() if item else "0"
                        preserved_pen_rows[pen_id] = row_data
        
        # On "New condition" (empty loadings and volumes), do not restore previous state
        if not pen_loadings and not tank_volumes:
            preserved_cargo_selections.clear()
            preserved_head_counts.clear()
            preserved_pen_rows.clear()
            preserved_tank_weights.clear()
        
        # Preserve tank weights from all tank category tables
        tank_category_tabs = [
            "Water Ballast", "Fresh Water", "Heavy Fuel Oil", "Diesel Oil",
            "Lube Oil", "Misc. Tanks", "Dung", "Fodder Hold", "Spaces"
        ]
        for tab_name in tank_category_tabs:
            table = self._table_widgets.get(tab_name)
            if table:
                for row in range(table.rowCount()):
                    name_item = table.item(row, self.TANK_COL_NAME)
                    if not name_item:
                        continue
                    tank_id = name_item.data(Qt.ItemDataRole.UserRole)
                    if tank_id is None:
                        continue
                    
                    # Get weight (column 8)
                    weight_item = table.item(row, self.TANK_COL_WEIGHT)
                    if weight_item:
                        try:
                            weight_mt = float(weight_item.text())
                            if weight_mt > 0:
                                preserved_tank_weights[tank_id] = weight_mt
                        except (ValueError, TypeError):
                            pass
        
        # Clear all tables first
        for table in self._table_widgets.values():
            try:
                table.itemChanged.disconnect()
            except Exception:
                pass
            try:
                table.currentCellChanged.disconnect()
            except Exception:
                pass
            table.setRowCount(0)
        
        # Default to "-- Blank --" if no cargo_type and no default_cargo_name provided
        if cargo_type:
            mass_per_head_t = (getattr(cargo_type, "avg_weight_per_head_kg", 520.0) or 520.0) / 1000.0
            area_per_head_from_cargo = getattr(cargo_type, "deck_area_per_head_m2", None)
            cargo_name = (cargo_type.name or "Livestock").strip()
        else:
            # No cargo selected - use blank defaults
            mass_per_head_t = 0.0
            area_per_head_from_cargo = None
            cargo_name = default_cargo_name if default_cargo_name else "-- Blank --"

        # Update livestock deck tabs
        for deck_num in range(1, 9):
            tab_name = f"Livestock-DK{deck_num}"
            deck_letter = chr(ord('A') + deck_num - 1)  # A-H
            if deck_num == 8:
                self._populate_deck8_tab(
                    tab_name, pens, pen_loadings, deck_letter,
                    mass_per_head_t=mass_per_head_t,
                    area_per_head_from_cargo=area_per_head_from_cargo,
                    cargo_name=cargo_name,
                    cargo_type_names=cargo_type_names,
                    cargo_types=self._current_cargo_types,
                    preserved_cargo_selections=preserved_cargo_selections,
                    preserved_head_counts=preserved_head_counts,
                )
            else:
                self._populate_livestock_tab(
                    tab_name, pens, pen_loadings, deck_letter,
                    mass_per_head_t=mass_per_head_t,
                    area_per_head_from_cargo=area_per_head_from_cargo,
                    cargo_name=cargo_name,
                    cargo_type_names=cargo_type_names,
                    cargo_types=self._current_cargo_types,
                    preserved_cargo_selections=preserved_cargo_selections,
                    preserved_head_counts=preserved_head_counts,
                    preserved_pen_rows=preserved_pen_rows,
                )
            
        # Update tank category tabs (store ullage/FSM so row recalc can re-apply when weight changes)
        self._tank_ullage_fsm = tank_ullage_fsm or {}
        self._populate_tank_tabs(
            tanks, tank_volumes,
            preserved_tank_weights=preserved_tank_weights,
            tank_ullage_fsm=self._tank_ullage_fsm,
        )
        
        # Update "All" tab
        self._populate_all_tab(
            pens, tanks, pen_loadings, tank_volumes,
            mass_per_head_t=mass_per_head_t,
            area_per_head_from_cargo=area_per_head_from_cargo,
            cargo_name=cargo_name,
            cargo_type_names=cargo_type_names,
            cargo_types=self._current_cargo_types,
            preserved_cargo_selections=preserved_cargo_selections,
            preserved_head_counts=preserved_head_counts,
        )
        
        # Refresh cargo dropdowns in header combos
        self._refresh_cargo_header_dropdowns()
        # Refresh VCG/LCG/TCG for all tank rows in all tank category tabs
        self.refresh_all_tank_cog_cells()
        
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
        cargo_types: Optional[List[Any]] = None,
        preserved_cargo_selections: Optional[Dict[int, str]] = None,
        preserved_head_counts: Optional[Dict[int, int]] = None,
        preserved_pen_rows: Optional[Dict[int, Dict[int, str]]] = None,
    ) -> None:
        """Populate a livestock deck tab with pens for that deck. Cargo dropdown + dynamic recalc when Cargo or # Head changes."""
        table = self._table_widgets.get(tab_name)
        if not table:
            return
            
        deck_letter_upper = deck_letter.upper()
        deck_pens = [
            p for p in pens
            if _deck_to_letter(p.deck or "") == deck_letter_upper
        ]
        
        # Sort pens by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
        deck_pens = sorted(deck_pens, key=get_pen_sort_key)
        
        total_weight = 0.0
        total_area_used = 0.0
        total_area = 0.0
        
        for pen in deck_pens:
            row = table.rowCount()
            table.insertRow(row)
            
            pen_id = pen.id or -1
            pr = (preserved_pen_rows or {}).get(pen_id)
            
            if pr:
                # Use full preserved row so Compute does not reset any column
                def _f(d: Dict[int, str], c: int, default: str = "0") -> float:
                    try:
                        return float(d.get(c, default))
                    except (ValueError, TypeError):
                        return float(default) if default != "" else 0.0
                def _i(d: Dict[int, str], c: int, default: str = "0") -> int:
                    try:
                        return int(float(d.get(c, default)))
                    except (ValueError, TypeError):
                        return 0
                heads = _i(pr, 2)
                head_pct = _f(pr, 3)
                head_capacity = _i(pr, 4)
                area_used = _f(pr, 5)
                area_per_head = _f(pr, 7)
                display_avw = _f(pr, 8)
                display_weight = _f(pr, 9)
                weight_mt = display_weight
                vcg_display = _f(pr, 10, str(pen.vcg_m))
                lcg_display = _f(pr, 11, str(pen.lcg_m))
                tcg_display = _f(pr, 12, str(pen.tcg_m))
                lcg_moment = _f(pr, 13)
                total_weight += display_weight
                total_area_used += area_used
                total_area += pen.area_m2
            else:
                # Calculate from cargo/loadings
                if preserved_head_counts and pen_id in preserved_head_counts:
                    initial_heads = preserved_head_counts[pen_id]
                else:
                    initial_heads = pen_loadings.get(pen_id, 0)
                
                if cargo_name == "-- Blank --":
                    area_per_head = 0.0
                elif area_per_head_from_cargo is not None:
                    area_per_head = area_per_head_from_cargo
                else:
                    # Use cargo's area_per_head if available, otherwise calculate from initial heads
                    ct_sel = next((c for c in (cargo_types or []) if (getattr(c, "name", "") or "").strip() == cargo_name), None)
                    if ct_sel:
                        area_per_head = getattr(ct_sel, "deck_area_per_head_m2", 1.85) or 1.85
                    else:
                        area_per_head = pen.area_m2 / initial_heads if initial_heads > 0 else 1.85
                
                # Calculate maximum heads based on area constraint
                max_heads_by_area = int(pen.area_m2 / area_per_head) if area_per_head > 0 else 0
                max_heads_by_capacity = int(pen.capacity_head) if pen.capacity_head > 0 else max_heads_by_area
                
                if preserved_head_counts and pen_id in preserved_head_counts:
                    heads = preserved_head_counts[pen_id]
                    if area_per_head > 0:
                        area_used = min(heads * area_per_head, pen.area_m2)
                        head_capacity = int(pen.area_m2 / area_per_head)
                    else:
                        area_used = 0.0
                        head_capacity = 0
                elif cargo_name == "-- Blank --":
                    heads = 0
                    head_capacity = 0
                    area_used = 0.0
                else:
                    if max_heads_by_area > 0 and max_heads_by_capacity > 0:
                        heads = min(max_heads_by_area, max_heads_by_capacity)
                    elif max_heads_by_area > 0:
                        heads = max_heads_by_area
                    elif max_heads_by_capacity > 0:
                        heads = max_heads_by_capacity
                    else:
                        heads = initial_heads
                    area_used = min(heads * area_per_head, pen.area_m2) if heads > 0 else 0.0
                    head_capacity = int(pen.area_m2 / area_per_head) if area_per_head > 0 else 0
                
                head_pct = (heads / head_capacity * 100.0) if head_capacity > 0 else 0.0
                weight_mt = heads * mass_per_head_t
                display_avw = mass_per_head_t
                display_weight = weight_mt
                total_weight += display_weight
                total_area_used += area_used
                total_area += pen.area_m2
                
                ct_sel = next((c for c in (cargo_types or []) if (getattr(c, "name", "") or "").strip() == cargo_name), None)
                vcg_from_deck = (getattr(ct_sel, "vcg_from_deck_m", 0) or 0) if ct_sel else 0.0
                vcg_display = pen.vcg_m + vcg_from_deck
                lcg_display = pen.lcg_m
                tcg_display = pen.tcg_m
                lcg_moment = display_weight * pen.lcg_m
            
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only (from ship manager)
            table.setItem(row, 0, name_item)
            if cargo_type_names:
                combo = QComboBox(table)
                # Avoid QPainter "paint device returned engine == 0" when combo is in a table cell
                combo.setMinimumHeight(22)
                combo.setMinimumWidth(80)
                # Add blank cargo option first, then regular cargo types
                all_cargo_names = ["-- Blank --"] + cargo_type_names
                combo.addItems(all_cargo_names)
                # Check if this pen has a preserved cargo selection
                pen_id = pen.id or -1
                preserved_cargo = None
                if preserved_cargo_selections:
                    preserved_cargo = preserved_cargo_selections.get(pen_id)
                if preserved_cargo and preserved_cargo in all_cargo_names:
                    combo.setCurrentText(preserved_cargo)
                elif cargo_name in all_cargo_names:
                    combo.setCurrentText(cargo_name)
                elif all_cargo_names:
                    combo.setCurrentIndex(0)
                if cargo_types:
                    combo.currentTextChanged.connect(
                        lambda _t, t=table, r=row: self._recalculate_livestock_row(t, r, auto_max_heads=True)
                    )
                table.setCellWidget(row, 1, combo)
            else:
                cargo_item = QTableWidgetItem(cargo_name)
                cargo_item.setFlags(cargo_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only if no combo
                table.setItem(row, 1, cargo_item)
            # # Head (col 2) - editable
            head_item = QTableWidgetItem(str(heads))
            table.setItem(row, 2, head_item)
            # Head %Full (col 3) - calculated, read-only
            head_pct_item = QTableWidgetItem(f"{head_pct:.2f}")
            head_pct_item.setFlags(head_pct_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 3, head_pct_item)
            # Head Capacity (col 4) - calculated from Total Area / Area per Head, floored to integer, read-only
            cap_item = QTableWidgetItem(str(head_capacity))
            cap_item.setFlags(cap_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 4, cap_item)
            # Used Area m2 (col 5) - calculated, read-only
            area_used_item = QTableWidgetItem(f"{area_used:.2f}")
            area_used_item.setFlags(area_used_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 5, area_used_item)
            # Total Area m2 (col 6) - from ship manager, read-only
            area_item = QTableWidgetItem(f"{pen.area_m2:.2f}")
            area_item.setFlags(area_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 6, area_item)
            # Area/Head (col 7) - calculated, read-only
            area_per_head_item = QTableWidgetItem(f"{area_per_head:.2f}")
            area_per_head_item.setFlags(area_per_head_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 7, area_per_head_item)
            # AvW/Head MT (col 8) and Weight MT (col 9) - use display_avw/display_weight (already set above, preserves on Compute)
            mass_item = QTableWidgetItem(f"{display_avw:.2f}")
            mass_item.setFlags(mass_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 8, mass_item)
            weight_item = QTableWidgetItem(f"{display_weight:.2f}")
            weight_item.setFlags(weight_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 9, weight_item)
            # VCG m-BL (col 10) - calculated, read-only
            vcg_item = QTableWidgetItem(f"{vcg_display:.3f}")
            vcg_item.setFlags(vcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 10, vcg_item)
            # LCG m-[FR] (col 11) - from ship manager or preserved, read-only
            lcg_item = QTableWidgetItem(f"{lcg_display:.3f}")
            lcg_item.setFlags(lcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 11, lcg_item)
            # TCG m-CL (col 12) - from ship manager or preserved, read-only
            tcg_item = QTableWidgetItem(f"{tcg_display:.3f}")
            tcg_item.setFlags(tcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 12, tcg_item)
            # LS Moment m-MT (col 13) - calculated, read-only
            moment_item = QTableWidgetItem(f"{lcg_moment:.2f}")
            moment_item.setFlags(moment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 13, moment_item)
            
        if deck_pens and cargo_types:
            table.itemChanged.connect(self._make_livestock_item_changed(table))
            
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
    
    def _populate_deck8_tab(
        self,
        tab_name: str,
        pens: List[LivestockPen],
        pen_loadings: Dict[int, int],
        deck_letter: str,
        mass_per_head_t: float = MASS_PER_HEAD_T,
        area_per_head_from_cargo: Optional[float] = None,
        cargo_name: str = "Livestock",
        cargo_type_names: Optional[List[str]] = None,
        cargo_types: Optional[List[Any]] = None,
        preserved_cargo_selections: Optional[Dict[int, str]] = None,
        preserved_head_counts: Optional[Dict[int, int]] = None,
    ) -> None:
        """Populate deck 8 (H) tab with columns: Name, Quantity, Weight (MT), Total Weight (MT), LCG, VCG, TCG, LS Moment m-MT, Delete."""
        table = self._table_widgets.get(tab_name)
        if not table or table.columnCount() != self.DECK8_COLUMNS:
            return
        deck_letter_upper = deck_letter.upper()
        deck_pens = [
            p for p in pens
            if _deck_to_letter(p.deck or "") == deck_letter_upper
        ]
        deck_pens = sorted(deck_pens, key=get_pen_sort_key)
        total_weight = 0.0
        total_ls_moment = 0.0
        ct_sel = next((c for c in (cargo_types or []) if (getattr(c, "name", "") or "").strip() == cargo_name), None)
        vcg_from_deck = (getattr(ct_sel, "vcg_from_deck_m", 0) or 0) if ct_sel else 0.0
        for pen in deck_pens:
            row = table.rowCount()
            table.insertRow(row)
            # For deck 8: use preserved head count if available, otherwise pen_loadings, otherwise capacity_head
            pen_id = pen.id or -1
            if preserved_head_counts and pen_id in preserved_head_counts:
                heads = preserved_head_counts[pen_id]
            elif pen.id and pen.id in pen_loadings:
                heads = pen_loadings.get(pen_id, 0)
            else:
                heads = pen.capacity_head if pen.capacity_head > 0 else 0
            weight_mt = heads * mass_per_head_t
            vcg_display = pen.vcg_m + vcg_from_deck
            lcg_moment = weight_mt * pen.lcg_m
            total_weight += weight_mt
            total_ls_moment += lcg_moment
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, name_item)
            qty_item = QTableWidgetItem(str(heads))
            table.setItem(row, 1, qty_item)
            # Weight in MT per head - editable so user can override
            weight_item = QTableWidgetItem(f"{mass_per_head_t:.2f}")
            table.setItem(row, 2, weight_item)
            # Total Weight in MT (auto-calculated, read-only)
            total_weight_item = QTableWidgetItem(f"{weight_mt:.2f}")
            total_weight_item.setFlags(total_weight_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 3, total_weight_item)
            # VCG m-BL (col 4) - initial value from pen + cargo, editable
            vcg_item = QTableWidgetItem(f"{vcg_display:.3f}")
            table.setItem(row, 4, vcg_item)
            # LCG m-[FR] (col 5) - initial value from pen, editable
            lcg_item = QTableWidgetItem(f"{pen.lcg_m:.3f}")
            table.setItem(row, 5, lcg_item)
            # TCG m-CL (col 6) - initial value from pen, editable
            tcg_item = QTableWidgetItem(f"{pen.tcg_m:.3f}")
            table.setItem(row, 6, tcg_item)
            moment_item = QTableWidgetItem(f"{lcg_moment:.2f}")
            moment_item.setFlags(moment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 7, moment_item)
            self._set_deck8_delete_button(table, row)
        # Totals row (always present for deck 8) - Total Weight in MT
        tot_row = table.rowCount()
        table.insertRow(tot_row)
        table.setItem(tot_row, 0, QTableWidgetItem(f"{tab_name} Totals"))
        for c in range(1, 7):
            table.setItem(tot_row, c, QTableWidgetItem(""))
        table.setItem(tot_row, 3, QTableWidgetItem(f"{total_weight:.2f}"))
        table.setItem(tot_row, 7, QTableWidgetItem(f"{total_ls_moment:.2f}"))
        # Blank row for user entry (when filled, another blank is added)
        self._append_deck8_blank_row(table)
        if deck_pens or True:
            table.itemChanged.connect(self._make_deck8_item_changed(table))
    
    def _set_deck8_delete_button(self, table: QTableWidget, row: int) -> None:
        """Set a Delete button in the given row of the deck 8 table (column DECK8_COL_DELETE). Not used on the blank new row."""
        if table.columnCount() != self.DECK8_COLUMNS:
            return
        btn = QPushButton("Delete", table)
        btn.setToolTip("Remove this pen from Deck H")
        btn.setStyleSheet(
            "QPushButton {"
            " min-width: 60px; max-height: 24px; font-size: 11px; font-weight: 500;"
            " background-color: #dc3545; color: white; border: none; border-radius: 4px;"
            " padding: 4px 10px;"
            "}"
            "QPushButton:hover { background-color: #c82333; }"
            "QPushButton:pressed { background-color: #bd2130; }"
            "QPushButton:disabled { background-color: #e0a0a8; color: #fff; }"
        )
        btn.clicked.connect(lambda checked=False: self._on_deck8_delete_clicked(table))
        table.setCellWidget(row, self.DECK8_COL_DELETE, btn)

    def _on_deck8_delete_clicked(self, table: QTableWidget) -> None:
        """Find the row whose Delete button was clicked, delete the pen from DB if persisted, remove row, refresh totals."""
        if table.columnCount() != self.DECK8_COLUMNS:
            return
        sender = self.sender()
        if not isinstance(sender, QPushButton):
            return
        row = None
        for r in range(table.rowCount()):
            if table.cellWidget(r, self.DECK8_COL_DELETE) is sender:
                row = r
                break
        if row is None:
            return
        name_cell = table.item(row, 0)
        if not name_cell or "Totals" in (name_cell.text() or ""):
            return
        name_item = table.item(row, 0)
        pen_id = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
        if pen_id is not None and database.SessionLocal is not None:
            try:
                with database.SessionLocal() as db:
                    repo = LivestockPenRepository(db)
                    repo.delete(pen_id)
                self._current_pens = [p for p in self._current_pens if (p.id or 0) != pen_id]
            except Exception:
                pass
        was_last_row = row == table.rowCount() - 1
        table.removeRow(row)
        self._refresh_deck8_totals(table)
        if was_last_row:
            self._append_deck8_blank_row(table)

    def _append_deck8_blank_row(self, table: QTableWidget) -> None:
        """Append one editable blank row for new pen entry. No Delete button on this row."""
        if table.columnCount() != self.DECK8_COLUMNS:
            return
        row = table.rowCount()
        table.insertRow(row)
        for c in range(self.DECK8_COL_DELETE):
            item = QTableWidgetItem("")
            # Total Weight (col 3, MT) and LS Moment (col 7) are read-only, auto-calculated
            if c in (3, 7):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, c, item)
        # Leave column 8 empty so user sees only the row to fill
    
    def _make_deck8_item_changed(self, table: QTableWidget):
        """Return a handler for deck 8 itemChanged: auto-calc Total Weight when Quantity/Weight changes, or add blank row when last row is filled."""
        def on_item(item: QTableWidgetItem) -> None:
            if self._skip_item_changed:
                return
            row = item.row()
            if table.columnCount() != self.DECK8_COLUMNS:
                return
            last_row = table.rowCount() - 1
            if row == last_row:
                # User edited the blank row; if it's now "filled", save to database and add another blank row
                if self._deck8_row_is_filled(table, row):
                    self._skip_item_changed = True
                    try:
                        self._save_deck8_row_to_database(table, row)
                        self._append_deck8_blank_row(table)
                        self._set_deck8_delete_button(table, row)  # Add Delete to the row just saved
                        self._refresh_deck8_totals(table)
                    finally:
                        self._skip_item_changed = False
                # Also recalc Total Weight and LS Moment if Quantity, Weight, or LCG changed
                if item.column() in (1, 2, 5):
                    self._recalculate_deck8_row_total_weight(table, row)
                    # If row already has a pen ID, update it in database
                    name_item = table.item(row, 0)
                    if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                        self._save_deck8_row_to_database(table, row)
                return
            # Auto-calculate Total Weight and LS Moment when Quantity (col 1), Weight (col 2), or LCG (col 5) changes
            if item.column() in (1, 2, 5):
                self._recalculate_deck8_row_total_weight(table, row)
                # If row has a pen ID (user-entered row), update it in database
                name_item = table.item(row, 0)
                if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                    self._save_deck8_row_to_database(table, row)
        return on_item
    
    def _save_deck8_row_to_database(self, table: QTableWidget, row: int) -> None:
        """Save or update a deck 8 row to the database as a LivestockPen."""
        if self._current_ship_id is None or database.SessionLocal is None:
            return
        if table.columnCount() != self.DECK8_COLUMNS:
            return
        name_item = table.item(row, 0)
        if not name_item or "Totals" in (name_item.text() or ""):
            return
        try:
            name = (name_item.text() or "").strip()
            if not name:
                return
            pen_id = name_item.data(Qt.ItemDataRole.UserRole)
            try:
                qty_item = table.item(row, 1)
                qty_text = (qty_item.text() or "").strip() if qty_item else ""
                qty = int(float(qty_text)) if qty_text else 0
            except (TypeError, ValueError):
                qty = 0
            try:
                weight_kg_text = (table.item(row, 2).text() or "").strip()
                weight_kg = float(weight_kg_text) if weight_kg_text else 0.0
            except (TypeError, ValueError):
                weight_kg = 0.0
            try:
                vcg_text = (table.item(row, 4).text() or "").strip()
                vcg = float(vcg_text) if vcg_text else 0.0
            except (TypeError, ValueError):
                vcg = 0.0
            try:
                lcg_text = (table.item(row, 5).text() or "").strip()
                lcg = float(lcg_text) if lcg_text else 0.0
            except (TypeError, ValueError):
                lcg = 0.0
            try:
                tcg_text = (table.item(row, 6).text() or "").strip()
                tcg = float(tcg_text) if tcg_text else 0.0
            except (TypeError, ValueError):
                tcg = 0.0
            with database.SessionLocal() as db:
                repo = LivestockPenRepository(db)
                pen = LivestockPen(
                    id=pen_id,
                    ship_id=self._current_ship_id,
                    name=name,
                    deck="H",  # Deck 8 = H
                    vcg_m=vcg,
                    lcg_m=lcg,
                    tcg_m=tcg,
                    area_m2=0.0,  # Not used for deck 8
                    capacity_head=qty,  # Store quantity as capacity
                )
                if pen_id is None:
                    # Create new pen
                    saved = repo.create(pen)
                    if name_item:
                        name_item.setData(Qt.ItemDataRole.UserRole, saved.id)
                    # Add to current pens list so it appears in future updates
                    self._current_pens.append(saved)
                else:
                    # Update existing pen
                    repo.update(pen)
        except Exception as e:
            # Silently fail - user can retry by editing again
            pass
    
    def _deck8_row_is_filled(self, table: QTableWidget, row: int) -> bool:
        """True if the row has at least name or quantity filled (non-empty after strip)."""
        if row < 0 or row >= table.rowCount() or table.columnCount() != self.DECK8_COLUMNS:
            return False
        name_item = table.item(row, 0)
        qty_item = table.item(row, 1)
        name = (name_item.text() or "").strip() if name_item else ""
        qty = (qty_item.text() or "").strip() if qty_item else ""
        return bool(name or qty)
    
    def _recalculate_deck8_row_total_weight(self, table: QTableWidget, row: int) -> None:
        """Auto-calculate Total Weight (MT) = Quantity * Weight (MT) and LS Moment for any row (pen or user-entered)."""
        if row < 0 or row >= table.rowCount() or table.columnCount() != self.DECK8_COLUMNS:
            return
        name_cell = table.item(row, 0)
        if not name_cell or "Totals" in (name_cell.text() or ""):
            return
        try:
            qty_text = (table.item(row, 1).text() or "").strip()
            qty = float(qty_text) if qty_text else 0.0
        except (TypeError, ValueError):
            qty = 0.0
        try:
            weight_mt_text = (table.item(row, 2).text() or "").strip()
            weight_mt = float(weight_mt_text) if weight_mt_text else 0.0
        except (TypeError, ValueError):
            weight_mt = 0.0
        total_weight_mt = qty * weight_mt
        # Calculate LS Moment: Total Weight (MT) * LCG (m)
        try:
            lcg_text = (table.item(row, 5).text() or "").strip()
            lcg = float(lcg_text) if lcg_text else 0.0
        except (TypeError, ValueError):
            lcg = 0.0
        lcg_moment = total_weight_mt * lcg
        self._skip_item_changed = True
        try:
            # Update Total Weight (MT) - read-only, auto-calculated
            if table.item(row, 3):
                table.item(row, 3).setText(f"{total_weight_mt:.2f}")
            else:
                total_item = QTableWidgetItem(f"{total_weight_mt:.2f}")
                total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, 3, total_item)
            # Update LS Moment m-MT
            if table.item(row, 7):
                table.item(row, 7).setText(f"{lcg_moment:.2f}")
            else:
                moment_item = QTableWidgetItem(f"{lcg_moment:.2f}")
                moment_item.setFlags(moment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, 7, moment_item)
        finally:
            self._skip_item_changed = False
        # Refresh totals
        self._refresh_deck8_totals(table)
    
    def _refresh_deck8_totals(self, table: QTableWidget) -> None:
        """Refresh deck 8 totals row (Total Weight MT col 3, LS Moment m-MT col 7). Data rows + user rows; exclude totals row and last (blank) row."""
        if table.rowCount() < 2 or table.columnCount() != self.DECK8_COLUMNS:
            return
        tot_row = None
        for r in range(table.rowCount()):
            cell = table.item(r, 0)
            if cell and "Totals" in (cell.text() or ""):
                tot_row = r
                break
        if tot_row is None:
            return
        total_weight_mt = 0.0
        total_moment = 0.0
        last_row = table.rowCount() - 1
        for row in range(table.rowCount()):
            if row == tot_row or row == last_row:
                continue
            w = table.item(row, 3)
            m = table.item(row, 7)
            if w and (w.text() or "").strip():
                try:
                    total_weight_mt += float(w.text())
                except (TypeError, ValueError):
                    pass
            if m and (m.text() or "").strip():
                try:
                    total_moment += float(m.text())
                except (TypeError, ValueError):
                    pass
        if table.item(tot_row, 3):
            table.item(tot_row, 3).setText(f"{total_weight_mt:.2f}")
        if table.item(tot_row, 7):
            table.item(tot_row, 7).setText(f"{total_moment:.2f}")
    
    def _make_livestock_item_changed(self, table: QTableWidget):
        """Return a handler for itemChanged: recalc row when # Head (column 2) changes."""
        def on_item(item: QTableWidgetItem) -> None:
            if self._skip_item_changed:
                return
            if item.column() != 2:
                return
            row = item.row()
            if row >= table.rowCount() - 1:
                return
            self._recalculate_livestock_row(table, row)
        return on_item

    def _make_all_tab_item_changed(self, table: QTableWidget):
        """Return a handler for itemChanged on All tab (All tab is now read-only; this is unused)."""
        def on_item(item: QTableWidgetItem) -> None:
            pass
        return on_item
    
    def _refresh_cargo_header_dropdowns(self) -> None:
        """Refresh cargo options in header dropdown combos."""
        cargo_type_names = [c.name for c in self._current_cargo_types] if self._current_cargo_types else []
        # Add blank cargo option at the beginning
        blank_cargo_name = "-- Blank --"
        all_cargo_names = [blank_cargo_name] + cargo_type_names
        
        for tab_name, combo in self._cargo_header_combos.items():
            current_text = combo.currentText()
            combo.clear()
            combo.addItem("-- Apply to All --")  # Default option
            combo.addItems(all_cargo_names)
            # Restore previous selection if it still exists
            if current_text in all_cargo_names:
                combo.setCurrentText(current_text)
            else:
                combo.setCurrentIndex(0)  # Select "-- Apply to All --"
    
    def update_cargo_types(self, cargo_types: Optional[List[Any]] = None) -> None:
        """Update the current cargo types list and refresh all dropdowns (header and cell dropdowns)."""
        if cargo_types is not None:
            self._current_cargo_types = cargo_types
        
        # Refresh header dropdowns
        self._refresh_cargo_header_dropdowns()
        
        # Refresh all cell dropdowns in deck tables and other tables
        cargo_type_names = [c.name for c in self._current_cargo_types] if self._current_cargo_types else []
        # Add blank cargo option at the beginning
        blank_cargo_name = "-- Blank --"
        all_cargo_names = [blank_cargo_name] + cargo_type_names
        
        # Update cargo combos in all livestock deck tables (DK1-DK7)
        for deck_num in range(1, 8):
            tab_name = f"Livestock-DK{deck_num}"
            table = self._table_widgets.get(tab_name)
            if not table or table.columnCount() != 14:
                continue
            
            for row in range(table.rowCount()):
                # Skip totals row
                name_item = table.item(row, 0)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue
                
                # Cargo column is column 1
                combo = table.cellWidget(row, 1)
                if isinstance(combo, QComboBox):
                    current_text = combo.currentText()
                    combo.clear()
                    combo.addItems(all_cargo_names)
                    # Restore previous selection if it still exists
                    if current_text in all_cargo_names:
                        combo.setCurrentText(current_text)
                    elif all_cargo_names:
                        combo.setCurrentIndex(0)
        
        # Update cargo combos in "All" table (if it has cargo dropdowns)
        for tab_name in ["All"]:
            table = self._table_widgets.get(tab_name)
            if not table:
                continue

            for row in range(table.rowCount()):
                # Skip totals row
                name_item = table.item(row, 0)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue

                # Cargo column is column 1 (or column 2 if there's a Deck column)
                cargo_col = 1 if table.columnCount() == 14 else 2
                combo = table.cellWidget(row, cargo_col)
                if isinstance(combo, QComboBox):
                    current_text = combo.currentText()
                    combo.clear()
                    combo.addItems(all_cargo_names)
                    # Restore previous selection if it still exists
                    if current_text in all_cargo_names:
                        combo.setCurrentText(current_text)
                    elif all_cargo_names:
                        combo.setCurrentIndex(0)
    
    def _on_header_cargo_changed(self, tab_name: str, cargo: str) -> None:
        """Handle cargo selection from header combo - apply to all rows in the table."""
        if cargo == "-- Apply to All --" or not cargo:
            return
        
        table = self._table_widgets.get(tab_name)
        if not table or table.columnCount() != 14:
            return
        
        # Block itemChanged signals during bulk update
        self._skip_item_changed = True
        try:
            # Apply cargo to all rows (skip totals row)
            for row in range(table.rowCount()):
                # Skip totals row
                name_item = table.item(row, 0)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue
                
                # Cargo column is column 1
                combo = table.cellWidget(row, 1)
                if isinstance(combo, QComboBox):
                    # Find the index of the cargo in the combo
                    cargo_index = -1
                    available_items = []
                    for i in range(combo.count()):
                        item_text = combo.itemText(i)
                        available_items.append(item_text)
                        if item_text == cargo:
                            cargo_index = i
                            break
                    
                    # Skip if cargo not found in this combo
                    if cargo_index < 0:
                        # Try to add it if it's a valid cargo type
                        if cargo != "-- Blank --" and cargo in [c.name for c in self._current_cargo_types]:
                            combo.addItem(cargo)
                            cargo_index = combo.count() - 1
                        else:
                            continue
                    
                    # Block signals to avoid individual row recalculation during setting
                    combo.blockSignals(True)
                    
                    # Set the cargo using index (more reliable than setCurrentText)
                    combo.setCurrentIndex(cargo_index)
                    
                    combo.blockSignals(False)
                    
                    # Recalculate the row with auto-max heads (cargo changed via header)
                    try:
                        self._recalculate_livestock_row(table, row, auto_max_heads=True)
                    except Exception as e:
                        import logging
                        logging.error(f"Error recalculating row {row} in header cargo change: {e}", exc_info=True)
            
            # Reset header combo to default after applying
            header_combo = self._cargo_header_combos.get(tab_name)
            if header_combo:
                header_combo.blockSignals(True)
                header_combo.setCurrentIndex(0)  # Reset to "-- Apply to All --"
                header_combo.blockSignals(False)
        finally:
            self._skip_item_changed = False
    
    def _recalculate_livestock_row(self, table: QTableWidget, row: int, auto_max_heads: bool = False) -> None:
        """Recalculate one pen row from Cargo dropdown and # Head; then refresh totals.
        
        Args:
            table: The table widget containing the row
            row: The row index to recalculate
            auto_max_heads: If True, automatically set # Head to maximum when cargo changes.
                          If False, use current # Head value and cap it if needed.
        """
        if row >= table.rowCount() - 1:
            return
        name_item = table.item(row, 0)
        pen_id = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
        pen = next((p for p in self._current_pens if p.id == pen_id), None) if pen_id is not None else None
        if not pen:
            return
        
        # Get current heads value
        try:
            heads = int(float((table.item(row, 2) or QTableWidgetItem("0")).text()))
        except (TypeError, ValueError):
            heads = 0
        heads = max(0, heads)
        combo = table.cellWidget(row, 1)
        cargo_name = combo.currentText().strip() if isinstance(combo, QComboBox) else "Livestock"
        
        # Check if blank cargo is selected
        if cargo_name == "-- Blank --":
            # Set all values to zero for blank cargo
            heads = 0
            area_per_head = 0.0
            mass_per_head_t = 0.0
            area_used = 0.0
            head_capacity = 0.0
            # Head %Full = (Head / Head Capacity) * 100 = 0 / 0 = 0
            head_pct = 0.0
            weight_mt = 0.0
            vcg_display = pen.vcg_m  # Keep pen's base VCG
            lcg_moment = 0.0
            self._skip_item_changed = True
            try:
                # Update all cells to zero
                if table.item(row, 2):
                    table.item(row, 2).setText("0")
                else:
                    table.setItem(row, 2, QTableWidgetItem("0"))
                if table.item(row, 3):
                    table.item(row, 3).setText("0.00")
                else:
                    table.setItem(row, 3, QTableWidgetItem("0.00"))
                if table.item(row, 4):
                    table.item(row, 4).setText("0.00")
                else:
                    table.setItem(row, 4, QTableWidgetItem("0.00"))
                if table.item(row, 5):
                    table.item(row, 5).setText("0.00")
                else:
                    table.setItem(row, 5, QTableWidgetItem("0.00"))
                if table.item(row, 7):
                    table.item(row, 7).setText("0.00")
                else:
                    table.setItem(row, 7, QTableWidgetItem("0.00"))
                if table.item(row, 8):
                    table.item(row, 8).setText("0.00")
                else:
                    table.setItem(row, 8, QTableWidgetItem("0.00"))
                if table.item(row, 9):
                    table.item(row, 9).setText("0.00")
                else:
                    table.setItem(row, 9, QTableWidgetItem("0.00"))
                if table.item(row, 10):
                    table.item(row, 10).setText(f"{vcg_display:.3f}")
                else:
                    table.setItem(row, 10, QTableWidgetItem(f"{vcg_display:.3f}"))
                if table.item(row, 13):
                    table.item(row, 13).setText("0.00")
                else:
                    table.setItem(row, 13, QTableWidgetItem("0.00"))
            finally:
                self._skip_item_changed = False
            # Refresh totals
            last_row_label = (table.item(table.rowCount() - 1, 0).text() or "") if table.rowCount() else ""
            if "Totals" in last_row_label:
                self._refresh_livestock_totals(table)
            return
        
        ct = next((c for c in self._current_cargo_types if (getattr(c, "name", "") or "").strip() == cargo_name), None)
        if ct:
            mass_per_head_t = (getattr(ct, "avg_weight_per_head_kg", 520.0) or 520.0) / 1000.0
            area_per_head = getattr(ct, "deck_area_per_head_m2", 1.85) or 1.85
        else:
            mass_per_head_t = MASS_PER_HEAD_T
            area_per_head = pen.area_m2 / heads if heads > 0 else 0.0
        
        # Calculate maximum heads based on area constraint: max_heads = floor(Total Area / Area per Head)
        max_heads_by_area = 0
        if area_per_head > 0:
            max_heads_by_area = int(pen.area_m2 / area_per_head)
        
        # Calculate maximum heads based on capacity constraint
        max_heads_by_capacity = int(pen.capacity_head) if pen.capacity_head > 0 else max_heads_by_area
        
        # If cargo is "-- Blank --", set all values to zero (including head capacity)
        if cargo_name == "-- Blank --":
            heads = 0
            head_capacity = 0
            area_used = 0.0
        elif auto_max_heads:
            # Set heads to maximum (minimum of area-based and capacity-based maximums)
            if max_heads_by_area > 0 and max_heads_by_capacity > 0:
                heads = min(max_heads_by_area, max_heads_by_capacity)
            elif max_heads_by_area > 0:
                heads = max_heads_by_area
            elif max_heads_by_capacity > 0:
                heads = max_heads_by_capacity
            else:
                heads = max(0, heads)  # Keep current value if no constraints
            
            # Calculate Used Area (will be Γëñ Total Area due to capping)
            area_used = heads * area_per_head if heads > 0 else 0.0
            # Ensure Used Area Γëñ Total Area (safety check)
            area_used = min(area_used, pen.area_m2)
            
            # Head Capacity = Total Area / Area per Head (max capacity based on area), floored to integer
            head_capacity = int(pen.area_m2 / area_per_head) if area_per_head > 0 else 0
        else:
            # Use current heads value but cap it to maximums
            heads = max(0, heads)
            if area_per_head > 0 and max_heads_by_area > 0:
                heads = min(heads, max_heads_by_area)
            # Also cap by head capacity
            if max_heads_by_capacity > 0:
                heads = min(heads, max_heads_by_capacity)
            
            # Calculate Used Area (will be Γëñ Total Area due to capping)
            area_used = heads * area_per_head if heads > 0 else 0.0
            # Ensure Used Area Γëñ Total Area (safety check)
            area_used = min(area_used, pen.area_m2)
            
            # Head Capacity = Total Area / Area per Head (max capacity based on area), floored to integer
            head_capacity = int(pen.area_m2 / area_per_head) if area_per_head > 0 else 0
        
        # Head %Full = (Head / Head Capacity) * 100
        head_pct = (heads / head_capacity * 100.0) if head_capacity > 0 else 0.0
        
        weight_mt = heads * mass_per_head_t
        # VCG (m-BL) = pen deck + cargo VCG from deck (matches stability)
        vcg_from_deck = (getattr(ct, "vcg_from_deck_m", 0) or 0) if ct else 0.0
        vcg_display = pen.vcg_m + vcg_from_deck
        # LS Moment (m-MT) = Weight ├ù LCG
        lcg_moment = weight_mt * pen.lcg_m
        self._skip_item_changed = True
        try:
            # Update # Head in table if it was capped
            if table.item(row, 2):
                table.item(row, 2).setText(str(heads))
            else:
                table.setItem(row, 2, QTableWidgetItem(str(heads)))
            # Update Head Capacity - calculated from Total Area / Area per Head, floored to integer
            # If cargo is blank, head_capacity should already be 0 from above
            if table.item(row, 4):
                table.item(row, 4).setText(str(head_capacity))
            else:
                cap_item = QTableWidgetItem(str(head_capacity))
                cap_item.setFlags(cap_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, 4, cap_item)
            # Update Head %Full - calculated from Used Area / Total Area
            if table.item(row, 3):
                table.item(row, 3).setText(f"{head_pct:.2f}")
            else:
                table.setItem(row, 3, QTableWidgetItem(f"{head_pct:.2f}"))
            if table.item(row, 5):
                table.item(row, 5).setText(f"{area_used:.2f}")
            else:
                table.setItem(row, 5, QTableWidgetItem(f"{area_used:.2f}"))
            if table.item(row, 7):
                table.item(row, 7).setText(f"{area_per_head:.2f}")
            else:
                table.setItem(row, 7, QTableWidgetItem(f"{area_per_head:.2f}"))
            if table.item(row, 8):
                table.item(row, 8).setText(f"{mass_per_head_t:.2f}")
            else:
                table.setItem(row, 8, QTableWidgetItem(f"{mass_per_head_t:.2f}"))
            if table.item(row, 9):
                table.item(row, 9).setText(f"{weight_mt:.2f}")
            else:
                table.setItem(row, 9, QTableWidgetItem(f"{weight_mt:.2f}"))
            if table.item(row, 10):
                table.item(row, 10).setText(f"{vcg_display:.3f}")
            else:
                table.setItem(row, 10, QTableWidgetItem(f"{vcg_display:.3f}"))
            if table.item(row, 13):
                table.item(row, 13).setText(f"{lcg_moment:.2f}")
            else:
                table.setItem(row, 13, QTableWidgetItem(f"{lcg_moment:.2f}"))
        finally:
            self._skip_item_changed = False
        last_row_label = (table.item(table.rowCount() - 1, 0).text() or "") if table.rowCount() else ""
        if "Totals" in last_row_label:
            self._refresh_livestock_totals(table)
    
    def _refresh_livestock_totals(self, table: QTableWidget) -> None:
        """Refresh the totals row (last row) from data rows. Only for 14-column Livestock-DK1..7 tables."""
        if table.rowCount() < 2 or table.columnCount() != 14:
            return
        if "Totals" not in (table.item(table.rowCount() - 1, 0).text() or ""):
            return
        total_weight = 0.0
        total_area_used = 0.0
        total_area = 0.0
        for row in range(table.rowCount() - 1):
            w_item = table.item(row, 9)
            a5_item = table.item(row, 5)
            a6_item = table.item(row, 6)
            if w_item:
                try:
                    total_weight += float(w_item.text())
                except (TypeError, ValueError):
                    pass
            if a5_item:
                try:
                    total_area_used += float(a5_item.text())
                except (TypeError, ValueError):
                    pass
            if a6_item:
                try:
                    total_area += float(a6_item.text())
                except (TypeError, ValueError):
                    pass
        tot_row = table.rowCount() - 1
        if table.item(tot_row, 5):
            table.item(tot_row, 5).setText(f"{total_area_used:.2f}")
        if table.item(tot_row, 6):
            table.item(tot_row, 6).setText(f"{total_area:.2f}")
        if table.item(tot_row, 9):
            table.item(tot_row, 9).setText(f"{total_weight:.2f}")
            
    def _populate_tank_tabs(
        self,
        tanks: List[Tank],
        tank_volumes: Dict[int, float],
        preserved_tank_weights: Optional[Dict[int, float]] = None,
        tank_ullage_fsm: Optional[Dict[int, Tuple[float, float]]] = None,
    ) -> None:
        """Populate each tank category tab by tank category (Storing dropdown in Ship Manager).
        tank_ullage_fsm: tank_id -> (ullage_m, fsm_mt) from Excel for Ull/Snd and FSt columns.
        """
        tank_ullage_fsm = tank_ullage_fsm or {}
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
                    # Case-insensitive comparison to handle any casing differences
                    if tcat.lower() == cat.lower():
                        cat_tanks.append(t)
                elif t.tank_type in allowed_types:
                    cat_tanks.append(t)
            
            # Sort tanks within category by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
            cat_tanks = sorted(cat_tanks, key=get_tank_sort_key)
            
            total_cap = 0.0
            total_vol = 0.0
            total_weight = 0.0
            for tank in cat_tanks:
                row = table.rowCount()
                table.insertRow(row)
                # Initial: get volume from tank_volumes, calculate weight = volume * density
                # But use preserved weight if available
                tank_id = tank.id or -1
                if preserved_tank_weights and tank_id in preserved_tank_weights:
                    # Use preserved weight and calculate volume from it
                    weight_mt = preserved_tank_weights[tank_id]
                    dens = getattr(tank, "density_t_per_m3", 1.025) or 1.025
                    vol = weight_mt / dens if dens > 0 else 0.0
                    # Constraint: Volume cannot exceed Capacity
                    if tank.capacity_m3 > 0 and vol > tank.capacity_m3:
                        vol = tank.capacity_m3
                        weight_mt = vol * dens  # Recalculate weight if volume was capped
                else:
                    vol = tank_volumes.get(tank_id, 0.0)
                    dens = getattr(tank, "density_t_per_m3", 1.025) or 1.025
                    # Constraint: Volume cannot exceed Capacity
                    if tank.capacity_m3 > 0 and vol > tank.capacity_m3:
                        vol = tank.capacity_m3
                    weight_mt = vol * dens if vol > 0 else 0.0
                # Calculate %Full from volume and capacity
                fill_pct = (vol / tank.capacity_m3 * 100.0) if tank.capacity_m3 > 0 else 0.0
                total_cap += tank.capacity_m3
                total_vol += vol
                total_weight += weight_mt
                # VCG/LCG/TCG: sounding callback first, then default callback, else tank from loop
                cog = None
                if self._tank_cog_callback and tank_id >= 0:
                    cog = self._tank_cog_callback(tank_id, vol)
                if cog is None and self._tank_default_cog_callback and tank_id >= 0:
                    try:
                        cog = self._tank_default_cog_callback(tank_id)
                    except Exception:
                        cog = None
                if cog is None:
                    vcg = getattr(tank, "kg_m", 0.0) or 0.0
                    lcg = getattr(tank, "lcg_m", 0.0)
                    tcg = getattr(tank, "tcg_m", 0.0)
                else:
                    vcg, lcg, tcg = cog
                # Column 0: green indicator (empty cell; header is styled green)
                indicator_item = QTableWidgetItem("")
                indicator_item.setFlags(indicator_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, 0, indicator_item)
                
                # Name (col 1) - from ship manager, read-only; store tank id for recalc (never None)
                name_item = QTableWidgetItem(tank.name)
                name_item.setData(Qt.ItemDataRole.UserRole, tank.id if tank.id is not None else -1)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_NAME, name_item)
                
                # Ull/Snd (col 2) - from Excel Ullage (m) when available
                tid_key = int(tank_id) if tank_id is not None else -1
                ull_fsm = tank_ullage_fsm.get(tid_key, (None, None))
                ull_m = ull_fsm[0] if ull_fsm and ull_fsm[0] is not None else None
                ull_item = QTableWidgetItem(f"{ull_m:.3f}" if ull_m is not None else "")
                ull_item.setFlags(ull_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_ULL_SND, ull_item)
                
                # UTrim (col 3) - optional, read-only
                utrim_item = QTableWidgetItem("")
                utrim_item.setFlags(utrim_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_UTRIM, utrim_item)
                
                # Capacity (col 4) - from ship manager, read-only
                cap_item = QTableWidgetItem(f"{tank.capacity_m3:.3f}")
                cap_item.setFlags(cap_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_CAPACITY, cap_item)
                
                # %Full (col 5) - calculated from volume and capacity, read-only
                fill_item = QTableWidgetItem(f"{fill_pct:.3f}")
                fill_item.setFlags(fill_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_PCT_FULL, fill_item)
                
                # Volume (col 6) - calculated from weight and density, but capped at capacity, read-only
                # Ensure volume doesn't exceed capacity
                vol = min(vol, tank.capacity_m3) if tank.capacity_m3 > 0 else vol
                vol_item = QTableWidgetItem(f"{vol:.3f}")
                vol_item.setFlags(vol_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_VOLUME, vol_item)
                
                # Dens (col 7) - editable; Volume/%Full recalc when changed
                dens_item = QTableWidgetItem(f"{dens:.3f}")
                table.setItem(row, self.TANK_COL_DENS, dens_item)
                
                # Weight (col 8) - editable by user (only editable column)
                weight_item = QTableWidgetItem(f"{weight_mt:.3f}")
                table.setItem(row, self.TANK_COL_WEIGHT, weight_item)

                # VCG (col 9) - from ship manager or sounding table, read-only
                vcg_item = QTableWidgetItem(f"{vcg:.3f}")
                vcg_item.setFlags(vcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_VCG, vcg_item)
                
                # LCG (col 10) - from ship manager or sounding table, read-only
                lcg_item = QTableWidgetItem(f"{lcg:.3f}")
                lcg_item.setFlags(lcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_LCG, lcg_item)
                
                # TCG (col 11) - from ship manager or sounding table, read-only
                tcg_item = QTableWidgetItem(f"{tcg:.3f}")
                tcg_item.setFlags(tcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_TCG, tcg_item)
                
                # FSopt (col 12) - calculated, read-only
                fsopt_item = QTableWidgetItem("")
                fsopt_item.setFlags(fsopt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_FSOPT, fsopt_item)
                
                # FSt (col 13) - from Excel FSM (tonne.m) when available
                fsm_mt = ull_fsm[1] if ull_fsm and len(ull_fsm) > 1 and ull_fsm[1] is not None else None
                fst_item = QTableWidgetItem(f"{fsm_mt:.3f}" if fsm_mt is not None else "")
                fst_item.setFlags(fst_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_FST, fst_item)
            if cat_tanks:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(""))
                table.setItem(row, self.TANK_COL_NAME, QTableWidgetItem(f"{cat} Totals"))
                for c in (self.TANK_COL_ULL_SND, self.TANK_COL_UTRIM, self.TANK_COL_PCT_FULL,
                          self.TANK_COL_DENS, self.TANK_COL_VCG, self.TANK_COL_LCG,
                          self.TANK_COL_TCG, self.TANK_COL_FSOPT, self.TANK_COL_FST):
                    table.setItem(row, c, QTableWidgetItem(""))
                table.setItem(row, self.TANK_COL_CAPACITY, QTableWidgetItem(f"{total_cap:.3f}"))
                table.setItem(row, self.TANK_COL_VOLUME, QTableWidgetItem(f"{total_vol:.3f}"))
                table.setItem(row, self.TANK_COL_WEIGHT, QTableWidgetItem(f"{total_weight:.3f}"))
            # When Weight/Dens cell is edited or when you leave that cell (tab/click), recalc row
            table.itemChanged.connect(self._make_tank_item_changed(table))
            table.currentCellChanged.connect(
                lambda cur_r, cur_c, prev_r, prev_c, t=table: self._on_tank_cell_leave(t, prev_r, prev_c)
            )
    
    def _on_tank_cell_leave(self, table: QTableWidget, prev_row: int, prev_col: int) -> None:
        """When leaving a cell, if it was Weight or Dens, recalc that row so VCG/LCG/TCG update on tab/click away."""
        if prev_row < 0 or prev_col not in (self.TANK_COL_WEIGHT, self.TANK_COL_DENS):
            return
        if prev_row >= table.rowCount():
            return
        name_it = table.item(prev_row, self.TANK_COL_NAME)
        if not name_it or "Totals" in (name_it.text() or ""):
            return
        self._recalculate_tank_row(table, prev_row)
    
    def _make_tank_item_changed(self, table: QTableWidget):
        """Return a handler for tank table itemChanged: recalc Volume and %Full when Weight or Dens changes."""
        def on_item(item: QTableWidgetItem) -> None:
            if self._skip_item_changed:
                return
            if item.column() not in (self.TANK_COL_WEIGHT, self.TANK_COL_DENS):
                return
            row = item.row()
            # Skip totals row
            if row >= table.rowCount():
                return
            name_it = table.item(row, self.TANK_COL_NAME)
            if not name_it or "Totals" in (name_it.text() or ""):
                return
            # Recalc as soon as you leave the cell (itemChanged fires when edit is committed)
            self._recalculate_tank_row(table, row)
        return on_item
    
    def _recalculate_tank_row(self, table: QTableWidget, row: int) -> None:
        """Recalculate Volume and %Full from Weight and Density for a tank row.
        Volume is constrained to not exceed capacity; if it would, weight is adjusted accordingly."""
        if row < 0 or row >= table.rowCount():
            return
        # Skip totals row
        name_item = table.item(row, self.TANK_COL_NAME)
        if not name_item or "Totals" in (name_item.text() or ""):
            return
        
        weight_item = table.item(row, self.TANK_COL_WEIGHT)
        dens_item = table.item(row, self.TANK_COL_DENS)
        cap_item = table.item(row, self.TANK_COL_CAPACITY)
        if not weight_item or not dens_item or not cap_item:
            return
        try:
            weight_text = (weight_item.text() or "").strip()
            weight_mt = float(weight_text) if weight_text else 0.0
        except (TypeError, ValueError):
            weight_mt = 0.0
        try:
            dens_text = (dens_item.text() or "").strip()
            dens = float(dens_text) if dens_text else 1.025
        except (TypeError, ValueError):
            dens = 1.025
        try:
            cap_text = (cap_item.text() or "").strip()
            capacity = float(cap_text) if cap_text else 0.0
        except (TypeError, ValueError):
            capacity = 0.0
        # Calculate Volume = Weight / Density
        if dens > 0:
            vol = weight_mt / dens
        else:
            vol = 0.0
        
        # Constraint: Volume cannot exceed Capacity
        # If volume would exceed capacity, cap it and adjust weight accordingly
        weight_adjusted = False
        if capacity > 0 and vol > capacity:
            vol = capacity
            # Adjust weight to match the capped volume
            weight_mt = vol * dens
            weight_adjusted = True
        
        # Calculate %Full = (Volume / Capacity) * 100
        if capacity > 0:
            fill_pct = (vol / capacity) * 100.0
        else:
            fill_pct = 0.0
        
        self._skip_item_changed = True
        try:
            # Update Weight (col 8) if it was adjusted due to capacity constraint
            if weight_adjusted:
                if table.item(row, self.TANK_COL_WEIGHT):
                    table.item(row, self.TANK_COL_WEIGHT).setText(f"{weight_mt:.3f}")
                else:
                    weight_item = QTableWidgetItem(f"{weight_mt:.3f}")
                    table.setItem(row, self.TANK_COL_WEIGHT, weight_item)
            
            # Update Volume (col 6) - capped at capacity
            if table.item(row, self.TANK_COL_VOLUME):
                table.item(row, self.TANK_COL_VOLUME).setText(f"{vol:.3f}")
            else:
                vol_item = QTableWidgetItem(f"{vol:.3f}")
                vol_item.setFlags(vol_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_VOLUME, vol_item)
            # Update %Full (col 5)
            if table.item(row, self.TANK_COL_PCT_FULL):
                table.item(row, self.TANK_COL_PCT_FULL).setText(f"{fill_pct:.3f}")
            else:
                fill_item = QTableWidgetItem(f"{fill_pct:.3f}")
                fill_item.setFlags(fill_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_PCT_FULL, fill_item)
            # On weight/volume change: update LCG, VCG, TCG (from sounding or tank default) and UII/Snd, FSt (from cache)
            tank_id_val = name_item.data(Qt.ItemDataRole.UserRole)
            tid = int(tank_id_val) if tank_id_val is not None else -1
            cog = None
            if self._tank_cog_callback and tid >= 0:
                cog = self._tank_cog_callback(tid, vol)
            if cog is None and self._tank_default_cog_callback:
                try:
                    cog = self._tank_default_cog_callback(tid) if tid >= 0 else (0.0, 0.0, 0.0)
                except Exception:
                    cog = (0.0, 0.0, 0.0)
            if cog is None:
                cog = (0.0, 0.0, 0.0)
            vcg, lcg, tcg = cog
            # Always update VCG, LCG, TCG cells
            vcg_item = table.item(row, self.TANK_COL_VCG)
            if vcg_item:
                vcg_item.setText(f"{vcg:.3f}")
            else:
                vcg_item = QTableWidgetItem(f"{vcg:.3f}")
                vcg_item.setFlags(vcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_VCG, vcg_item)
            lcg_item = table.item(row, self.TANK_COL_LCG)
            if lcg_item:
                lcg_item.setText(f"{lcg:.3f}")
            else:
                lcg_item = QTableWidgetItem(f"{lcg:.3f}")
                lcg_item.setFlags(lcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_LCG, lcg_item)
            tcg_item = table.item(row, self.TANK_COL_TCG)
            if tcg_item:
                tcg_item.setText(f"{tcg:.3f}")
            else:
                tcg_item = QTableWidgetItem(f"{tcg:.3f}")
                tcg_item.setFlags(tcg_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_TCG, tcg_item)
            # Always update UII/Snd and FSt cells (from volume callback like VCG/LCG/TCG, else static cache)
            ull, fst = None, None
            if self._tank_ullage_fsm_callback and tid >= 0:
                try:
                    ull, fst = self._tank_ullage_fsm_callback(tid, vol)
                except Exception:
                    pass
            if ull is None and fst is None:
                ull_fsm = self._tank_ullage_fsm.get(tid, (None, None))
                ull = ull_fsm[0] if ull_fsm and ull_fsm[0] is not None else None
                fst = ull_fsm[1] if ull_fsm and len(ull_fsm) > 1 and ull_fsm[1] is not None else None
            ull_item = table.item(row, self.TANK_COL_ULL_SND)
            if ull_item:
                ull_item.setText(f"{ull:.3f}" if ull is not None else "")
            else:
                ull_item = QTableWidgetItem(f"{ull:.3f}" if ull is not None else "")
                ull_item.setFlags(ull_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_ULL_SND, ull_item)
            fst_item = table.item(row, self.TANK_COL_FST)
            if fst_item:
                fst_item.setText(f"{fst:.3f}" if fst is not None else "")
            else:
                fst_item = QTableWidgetItem(f"{fst:.3f}" if fst is not None else "")
                fst_item.setFlags(fst_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, self.TANK_COL_FST, fst_item)
            table.viewport().update()
            table.repaint()
            QApplication.processEvents()
            # Refresh totals row
            self._refresh_tank_totals(table)
        finally:
            self._skip_item_changed = False
    
    def _refresh_tank_totals(self, table: QTableWidget) -> None:
        """Refresh the totals row for a tank table (Capacity, Volume, Weight)."""
        if table.rowCount() < 2:
            return
        # Find totals row
        tot_row = None
        for r in range(table.rowCount()):
            name_item = table.item(r, self.TANK_COL_NAME)
            if name_item and "Totals" in (name_item.text() or ""):
                tot_row = r
                break
        if tot_row is None:
            return
        total_cap = 0.0
        total_vol = 0.0
        total_weight = 0.0
        for row in range(table.rowCount()):
            if row == tot_row:
                continue
            name_item = table.item(row, self.TANK_COL_NAME)
            if not name_item or "Totals" in (name_item.text() or ""):
                continue
            try:
                cap_text = (table.item(row, self.TANK_COL_CAPACITY).text() or "").strip()
                if cap_text:
                    total_cap += float(cap_text)
            except (TypeError, ValueError):
                pass
            try:
                vol_text = (table.item(row, self.TANK_COL_VOLUME).text() or "").strip()
                if vol_text:
                    total_vol += float(vol_text)
            except (TypeError, ValueError):
                pass
            try:
                weight_text = (table.item(row, self.TANK_COL_WEIGHT).text() or "").strip()
                if weight_text:
                    total_weight += float(weight_text)
            except (TypeError, ValueError):
                pass
        if table.item(tot_row, self.TANK_COL_CAPACITY):
            table.item(tot_row, self.TANK_COL_CAPACITY).setText(f"{total_cap:.3f}")
        if table.item(tot_row, self.TANK_COL_VOLUME):
            table.item(tot_row, self.TANK_COL_VOLUME).setText(f"{total_vol:.3f}")
        if table.item(tot_row, self.TANK_COL_WEIGHT):
            table.item(tot_row, self.TANK_COL_WEIGHT).setText(f"{total_weight:.3f}")

    def refresh_all_tank_cog_cells(self) -> None:
        """Refresh VCG/LCG/TCG for every tank row in every tank category table from current Volume. Call after update_data so all tabs show correct CoG."""
        for cat in TANK_CATEGORY_NAMES:
            table = self._table_widgets.get(cat)
            if not table:
                continue
            for row in range(table.rowCount()):
                name_item = table.item(row, self.TANK_COL_NAME)
                if not name_item or "Totals" in (name_item.text() or ""):
                    continue
                tank_id_val = name_item.data(Qt.ItemDataRole.UserRole)
                if tank_id_val is None:
                    continue
                tid = int(tank_id_val)
                vol_item = table.item(row, self.TANK_COL_VOLUME)
                if not vol_item:
                    continue
                try:
                    vol = float((vol_item.text() or "0").strip())
                except (TypeError, ValueError):
                    vol = 0.0
                cog = None
                if self._tank_cog_callback and tid >= 0:
                    cog = self._tank_cog_callback(tid, vol)
                if cog is None and self._tank_default_cog_callback:
                    try:
                        cog = self._tank_default_cog_callback(tid) if tid >= 0 else (0.0, 0.0, 0.0)
                    except Exception:
                        cog = (0.0, 0.0, 0.0)
                if cog is None:
                    cog = (0.0, 0.0, 0.0)
                vcg, lcg, tcg = cog
                self._skip_item_changed = True
                try:
                    if table.item(row, self.TANK_COL_VCG):
                        table.item(row, self.TANK_COL_VCG).setText(f"{vcg:.3f}")
                    if table.item(row, self.TANK_COL_LCG):
                        table.item(row, self.TANK_COL_LCG).setText(f"{lcg:.3f}")
                    if table.item(row, self.TANK_COL_TCG):
                        table.item(row, self.TANK_COL_TCG).setText(f"{tcg:.3f}")
                    ull, fst = None, None
                    if self._tank_ullage_fsm_callback and tid >= 0:
                        try:
                            ull, fst = self._tank_ullage_fsm_callback(tid, vol)
                        except Exception:
                            pass
                    if ull is None and fst is None:
                        ull_fsm = self._tank_ullage_fsm.get(tid, (None, None))
                        ull = ull_fsm[0] if ull_fsm and ull_fsm[0] is not None else None
                        fst = ull_fsm[1] if ull_fsm and len(ull_fsm) > 1 and ull_fsm[1] is not None else None
                    ull_item = table.item(row, self.TANK_COL_ULL_SND)
                    if ull_item:
                        ull_item.setText(f"{ull:.3f}" if ull is not None else "")
                    else:
                        ull_item = QTableWidgetItem(f"{ull:.3f}" if ull is not None else "")
                        ull_item.setFlags(ull_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row, self.TANK_COL_ULL_SND, ull_item)
                    fst_item = table.item(row, self.TANK_COL_FST)
                    if fst_item:
                        fst_item.setText(f"{fst:.3f}" if fst is not None else "")
                    else:
                        fst_item = QTableWidgetItem(f"{fst:.3f}" if fst is not None else "")
                        fst_item.setFlags(fst_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row, self.TANK_COL_FST, fst_item)
                finally:
                    self._skip_item_changed = False

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
        cargo_types: Optional[List[Any]] = None,
        preserved_cargo_selections: Optional[Dict[int, str]] = None,
        preserved_head_counts: Optional[Dict[int, int]] = None,
    ) -> None:
        """Populate the 'All' tab with everything. Cargo dropdown + dynamic recalc for pen rows."""
        all_table = self._table_widgets.get("All")
        if not all_table:
            return
        
        # Sort pens by deck first (A, B, C, D, ...), then by the standard pen sort key
        def all_table_sort_key(pen: LivestockPen) -> tuple:
            deck_letter = _deck_to_letter(pen.deck or "") or ""
            # Normalize deck to A-H for sorting
            if deck_letter and deck_letter.upper() in ["A", "B", "C", "D", "E", "F", "G", "H"]:
                deck_order = ord(deck_letter.upper())
            else:
                deck_order = 999  # Put invalid decks at end
            # Then use standard pen sort key for secondary sorting
            standard_key = get_pen_sort_key(pen)
            return (deck_order, standard_key[0], standard_key[1], standard_key[2])
        
        sorted_pens = sorted(pens, key=all_table_sort_key)
            
        # Add all pens from every deck (including those with 0 heads)
        for pen in sorted_pens:
            # Get all data from deck table (cargo, heads, head capacity, etc.)
            deck_data = self._get_pen_data_from_deck_table(pen, cargo_types)
            
            row = all_table.rowCount()
            all_table.insertRow(row)
            
            # All columns read-only; All tab shows pens only (no tanks)
            name_item = QTableWidgetItem(pen.name)
            name_item.setData(Qt.ItemDataRole.UserRole, pen.id)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            all_table.setItem(row, 0, name_item)
            deck_letter = _deck_to_letter(pen.deck or "") or (pen.deck or "")
            deck_item = QTableWidgetItem(deck_letter)
            deck_item.setFlags(deck_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            all_table.setItem(row, 1, deck_item)
            cargo_item = QTableWidgetItem(deck_data.get("cargo", "-- Blank --"))
            cargo_item.setFlags(cargo_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            all_table.setItem(row, 2, cargo_item)
            for col, val in [
                (3, str(deck_data.get("heads", 0))),
                (4, f"{deck_data.get('head_pct', 0.0):.2f}"),
                (5, str(int(deck_data.get('head_capacity', 0.0)))),
                (6, f"{deck_data.get('area_used', 0.0):.2f}"),
                (7, f"{pen.area_m2:.2f}"),
                (8, f"{deck_data.get('area_per_head', 0.0):.2f}"),
                (9, f"{deck_data.get('mass_per_head_t', 0.0):.2f}"),
                (10, f"{deck_data.get('weight_mt', 0.0):.2f}"),
                (11, f"{deck_data.get('vcg_display', pen.vcg_m):.3f}"),
                (12, f"{pen.lcg_m:.3f}"),
                (13, f"{pen.tcg_m:.3f}"),
                (14, f"{deck_data.get('lcg_moment', 0.0):.2f}"),
            ]:
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                all_table.setItem(row, col, it)
    
    def _get_pen_data_from_deck_table(self, pen: LivestockPen, cargo_types: Optional[List[Any]] = None) -> Dict[str, Any]:
        """Get all pen data (cargo, heads, head capacity, etc.) from the deck table for this pen.
        Returns a dictionary with all calculated values, or defaults if not found."""
        # Default values
        result = {
            "cargo": "-- Blank --",
            "heads": 0,
            "head_pct": 0.0,
            "head_capacity": 0.0,
            "area_used": 0.0,
            "area_per_head": 0.0,
            "mass_per_head_t": 0.0,
            "weight_mt": 0.0,
            "vcg_display": pen.vcg_m,
            "lcg_moment": 0.0,
        }
        
        # Determine which deck table this pen belongs to
        deck_letter = _deck_to_letter(pen.deck or "")
        if not deck_letter:
            return result
        
        # Convert deck letter to deck number (A=1, B=2, ..., H=8)
        deck_num = ord(deck_letter.upper()) - ord("A") + 1
        if not (1 <= deck_num <= 8):
            return result
        
        # Deck 8 (H) doesn't have cargo dropdowns, skip it
        if deck_num == 8:
            return result
        
        # Find the deck table
        tab_name = f"Livestock-DK{deck_num}"
        deck_table = self._table_widgets.get(tab_name)
        if not deck_table:
            return result
        
        # Find the pen in the deck table by pen ID
        for deck_row in range(deck_table.rowCount()):
            deck_name_item = deck_table.item(deck_row, 0)
            if not deck_name_item:
                continue
            
            # Skip totals row
            if "Totals" in (deck_name_item.text() or ""):
                continue
            
            deck_pen_id = deck_name_item.data(Qt.ItemDataRole.UserRole)
            if deck_pen_id == pen.id:
                # Found the pen, get all data from the deck table
                # Cargo (col 1)
                cargo_combo = deck_table.cellWidget(deck_row, 1)
                if isinstance(cargo_combo, QComboBox):
                    cargo_text = cargo_combo.currentText().strip()
                    result["cargo"] = cargo_text if cargo_text else "-- Blank --"
                else:
                    cargo_item = deck_table.item(deck_row, 1)
                    if cargo_item:
                        result["cargo"] = cargo_item.text().strip() or "-- Blank --"
                
                # # Head (col 2)
                head_item = deck_table.item(deck_row, 2)
                if head_item:
                    try:
                        result["heads"] = int(float(head_item.text() or "0"))
                    except (ValueError, TypeError):
                        result["heads"] = 0
                
                # Head %Full (col 3)
                head_pct_item = deck_table.item(deck_row, 3)
                if head_pct_item:
                    try:
                        result["head_pct"] = float(head_pct_item.text() or "0")
                    except (ValueError, TypeError):
                        result["head_pct"] = 0.0
                
                # Head Capacity (col 4)
                head_cap_item = deck_table.item(deck_row, 4)
                if head_cap_item:
                    try:
                        result["head_capacity"] = float(head_cap_item.text() or "0")
                    except (ValueError, TypeError):
                        result["head_capacity"] = 0.0
                
                # Used Area m2 (col 5)
                area_used_item = deck_table.item(deck_row, 5)
                if area_used_item:
                    try:
                        result["area_used"] = float(area_used_item.text() or "0")
                    except (ValueError, TypeError):
                        result["area_used"] = 0.0
                
                # Area/Head (col 7)
                area_per_head_item = deck_table.item(deck_row, 7)
                if area_per_head_item:
                    try:
                        result["area_per_head"] = float(area_per_head_item.text() or "0")
                    except (ValueError, TypeError):
                        result["area_per_head"] = 0.0
                
                # AvW/Head MT (col 8)
                mass_item = deck_table.item(deck_row, 8)
                if mass_item:
                    try:
                        result["mass_per_head_t"] = float(mass_item.text() or "0")
                    except (ValueError, TypeError):
                        result["mass_per_head_t"] = 0.0
                
                # Weight MT (col 9)
                weight_item = deck_table.item(deck_row, 9)
                if weight_item:
                    try:
                        result["weight_mt"] = float(weight_item.text() or "0")
                    except (ValueError, TypeError):
                        result["weight_mt"] = 0.0
                
                # VCG m-BL (col 10)
                vcg_item = deck_table.item(deck_row, 10)
                if vcg_item:
                    try:
                        result["vcg_display"] = float(vcg_item.text() or str(pen.vcg_m))
                    except (ValueError, TypeError):
                        result["vcg_display"] = pen.vcg_m
                
                # LS Moment m-MT (col 13)
                moment_item = deck_table.item(deck_row, 13)
                if moment_item:
                    try:
                        result["lcg_moment"] = float(moment_item.text() or "0")
                    except (ValueError, TypeError):
                        result["lcg_moment"] = 0.0
                
                break
        
        return result
