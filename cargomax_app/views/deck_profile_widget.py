from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QPainterPath
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QComboBox,
    QLabel,
    QGraphicsScene,
    QGraphicsPathItem,
    QGraphicsItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
)

from .graphics_views import ShipGraphicsView


BASE_DIR = Path(__file__).resolve().parent.parent  # -> senashipping_app
CAD_DIR = BASE_DIR / "cads"


def _load_dxf_into_scene(dxf_path: Path, scene: QGraphicsScene) -> bool:
    """
    Load basic geometry from a DXF file into the given scene.

    Supports LINE, LWPOLYLINE, POLYLINE and entities inside INSERT blocks.

    Returns True if something was drawn, False otherwise.
    """
    if not dxf_path.exists():
        return False

    try:
        import ezdxf  # type: ignore[import]
    except ImportError:
        # ezdxf not installed – caller will show a placeholder instead.
        return False

    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:
        return False

    msp = doc.modelspace()
    pen = QPen(Qt.GlobalColor.darkGray, 0)  # cosmetic pen (width 0 = hairline)

    from PyQt6.QtGui import QPainterPath

    drew_anything = False

    def draw_entity(e) -> None:
        nonlocal drew_anything
        et = e.dxftype()
        if et == "LINE":
            x1, y1, _ = e.dxf.start
            x2, y2, _ = e.dxf.end
            scene.addLine(x1, -y1, x2, -y2, pen)
            drew_anything = True
        elif et in ("LWPOLYLINE", "POLYLINE"):
            try:
                points = [(p[0], p[1]) for p in e.get_points()]  # type: ignore[attr-defined]
            except Exception:
                return
            if len(points) >= 2:
                path = QPainterPath()
                first = True
                for x, y in points:
                    if first:
                        path.moveTo(x, -y)
                        first = False
                    else:
                        path.lineTo(x, -y)
                if getattr(e, "closed", False):
                    path.closeSubpath()
                scene.addPath(path, pen)
                drew_anything = True

    for e in msp:
        et = e.dxftype()
        if et == "INSERT":
            # Many drawings use blocks; draw the virtual entities inside.
            try:
                for ve in e.virtual_entities():  # type: ignore[attr-defined]
                    draw_entity(ve)
            except Exception:
                continue
        else:
            draw_entity(e)

    return drew_anything


def _outline_to_path(outline_xy: list) -> QPainterPath:
    """Convert list of (x, y) to QPainterPath (y flipped for Qt)."""
    path = QPainterPath()
    for i, (x, y) in enumerate(outline_xy):
        if i == 0:
            path.moveTo(x, -y)
        else:
            path.lineTo(x, -y)
    path.closeSubpath()
    return path


class TankPolygonItem(QGraphicsPathItem):
    """
    Selectable, hoverable polygon for one tank. Visual states: normal, hover, selected.
    """
    def __init__(self, tank_id: int, path: QPainterPath, parent: QGraphicsItem | None = None) -> None:
        super().__init__(path, parent)
        self._tank_id = tank_id
        self._hover = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
        self.setAcceptHoverEvents(True)
        self.setData(0, tank_id)
        self._update_style()

    def _update_style(self) -> None:
        if self.isSelected():
            self.setPen(QPen(QColor(0, 100, 255), 2.5))
            self.setBrush(QBrush(QColor(100, 160, 255, 80)))
        elif self._hover:
            self.setPen(QPen(QColor(80, 140, 255), 1.5))
            self.setBrush(QBrush(QColor(200, 220, 255, 100)))
        else:
            self.setPen(QPen(Qt.GlobalColor.darkGray, 1))
            self.setBrush(QBrush(QColor(220, 220, 220, 60)))
        self.update()

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self._update_style()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self._update_style()
        super().hoverLeaveEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value) -> None:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            self._update_style()
        return super().itemChange(change, value)

    @property
    def tank_id(self) -> int:
        return self._tank_id


class ProfileView(ShipGraphicsView):
    """
    Top profile view with waterline.

    Shows ship profile with dynamic waterline based on draft and trim.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # Store references to dynamic elements
        self._waterline_item: QGraphicsLineItem | None = None
        self._waterline_aft_item: QGraphicsLineItem | None = None
        self._waterline_fwd_item: QGraphicsLineItem | None = None
        
        # Ship dimensions for scaling
        self._ship_length: float = 0.0
        self._ship_breadth: float = 0.0
        
        self._load_profile()

    def _load_profile(self) -> None:
        """Load ship profile from DXF or show placeholder."""
        self._scene.clear()
        self._waterline_item = None
        self._waterline_aft_item = None
        self._waterline_fwd_item = None
        
        dxf_path = CAD_DIR / "profile.dxf"
        if not _load_dxf_into_scene(dxf_path, self._scene):
            # Fallback placeholder if DXF missing or ezdxf not installed
            # Draw a simple hull shape
            hull_pen = QPen(QColor(50, 50, 50), 2)
            self._scene.addLine(0, 0, 800, 0, hull_pen)  # Baseline
            self._scene.addRect(QRectF(50, -40, 700, 80), QPen(QColor(30, 30, 30), 2))
            self._ship_length = 800.0
            self._ship_breadth = 80.0
        else:
            # Estimate dimensions from scene bounds
            bounds = self._scene.itemsBoundingRect()
            self._ship_length = max(bounds.width(), 100.0)
            self._ship_breadth = max(abs(bounds.height()), 20.0)
        
        if self._scene.items():
            self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
            
    def update_waterline(
        self,
        draft_mid: float,
        draft_aft: float | None = None,
        draft_fwd: float | None = None,
        ship_length: float | None = None,
    ) -> None:
        """
        Update waterline visualization based on draft values.
        
        Args:
            draft_mid: Draft at midship (m)
            draft_aft: Draft at aft (m), optional
            draft_fwd: Draft at forward (m), optional
            ship_length: Ship length (m), optional
        """
        if ship_length:
            self._ship_length = ship_length
            
        if self._ship_length == 0:
            return
            
        # Scale draft to scene coordinates (assuming scene is scaled appropriately)
        # For now, use a simple scaling factor
        scale_y = self._ship_breadth / 10.0 if self._ship_breadth > 0 else 1.0
        
        # Remove old waterlines
        if self._waterline_item:
            self._scene.removeItem(self._waterline_item)
        if self._waterline_aft_item:
            self._scene.removeItem(self._waterline_aft_item)
        if self._waterline_fwd_item:
            self._scene.removeItem(self._waterline_fwd_item)
            
        # Draw waterline (blue, thick)
        waterline_pen = QPen(QColor(0, 100, 200), 3)
        
        if draft_aft is not None and draft_fwd is not None:
            # Draw angled waterline showing trim
            y_aft = -draft_aft * scale_y
            y_fwd = -draft_fwd * scale_y
            self._waterline_item = self._scene.addLine(
                0, y_aft, self._ship_length, y_fwd, waterline_pen
            )
        else:
            # Draw level waterline
            y = -draft_mid * scale_y
            self._waterline_item = self._scene.addLine(
                0, y, self._ship_length, y, waterline_pen
            )
            
        # Bring waterline to front
        if self._waterline_item:
            self._waterline_item.setZValue(100)


class DeckView(ShipGraphicsView):
    """
    Deck plan view: draws DXF or tank polygons. Tank polygons are selectable
    with visual states (normal/hover/selected) and emit tank_selected.
    """

    tank_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._deck_name = ""
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        for item in self._scene.selectedItems():
            if isinstance(item, TankPolygonItem):
                self.tank_selected.emit(item.tank_id)
                return
        # No tank selected; could emit -1 or do nothing
        # self.tank_selected.emit(-1)

    def load_deck(self, deck_name: str, tanks: list | None = None) -> None:
        """
        Load the given deck. If tanks with outline_xy for this deck are provided,
        draw them as selectable polygons; otherwise load DXF from CAD_DIR.
        """
        self._deck_name = deck_name
        self._scene.clear()

        deck_tanks = []
        if tanks:
            for t in tanks:
                deck = getattr(t, "deck_name", None) or ""
                outline = getattr(t, "outline_xy", None)
                if (deck or "").strip().upper() == deck_name.upper() and outline and len(outline) >= 3:
                    deck_tanks.append(t)

        if deck_tanks:
            for tank in deck_tanks:
                path = _outline_to_path(tank.outline_xy)
                item = TankPolygonItem(tank.id or -1, path)
                self._scene.addItem(item)
        else:
            dxf_path = CAD_DIR / f"deck_{deck_name}.dxf"
            drew = _load_dxf_into_scene(dxf_path, self._scene)
            if not drew:
                self._scene.addRect(
                    QRectF(0, 0, 600, 200),
                    QPen(Qt.GlobalColor.darkGreen, 2),
                    QBrush(Qt.GlobalColor.green),
                )

        if self._scene.items():
            self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_tanks(self, tanks: list) -> None:
        """
        Redraw deck using tanks that have outline_xy and deck_name matching current deck.
        Call after load_deck when tank list changes (e.g. from condition editor).
        """
        if self._deck_name:
            self.load_deck(self._deck_name, tanks)


def _fmt_val(v: float | None, decimals: int = 2) -> str:
    """Format number or '---' when None."""
    if v is None:
        return "---"
    return f"{v:.{decimals}f}"


class DeckTabWidget(QWidget):
    """
    Widget for a single deck tab: shows deck plan + deck table matching reference.
    Table: Pens no. | Area A,B,C,D | LCG | VCG | TCG A,B,C,D | TOTAL row.
    """

    def __init__(self, deck_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._deck_name = deck_name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Left: deck plan drawing
        self._deck_view = DeckView(self)
        self._deck_view.load_deck(deck_name)
        layout.addWidget(self._deck_view, 2)

        # Right: deck table (title + table)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel(self)
        self._title_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        right.addWidget(self._title_label)

        self._table = QTableWidget(self)
        # self._table.setColumnCount(12)
        # self._table.setHorizontalHeaderLabels([
        #     "Pens no.",
        #     "A", "B", "C", "D",  # Area
        #     "LCG (m) from Fr. -6",
        #     "VCG (m) from B.L.",
        #     "A", "B", "C", "D",  # TCG (m) from C.L.
        # ])
        # self._table.horizontalHeader().setStretchLastSection(False)
        # for i in range(12):
        #     self._table.setColumnWidth(i, 72 if i > 0 else 56)
        # right.addWidget(self._table, 1)
        # layout.addLayout(right, 1)

    def update_table(self, pens: list, tanks: list) -> None:
        """Update the table and deck view (tank polygons when outline_xy present)."""
        self._deck_view.set_tanks(tanks)
        deck_pens = [
            p for p in pens
            if (getattr(p, "deck", None) or "").strip().upper() == self._deck_name.upper()
        ]
        # Sort by pen_no descending (14 at top), then by name
        def sort_key(p):
            pno = getattr(p, "pen_no", None)
            if pno is not None:
                return (-pno, p.name)
            return (0, p.name)
        deck_pens.sort(key=sort_key)

        # Net area: sum of area_a+area_b+area_c+area_d when set, else area_m2
        net_area = 0.0
        sums = [0.0, 0.0, 0.0, 0.0]  # Area A, B, C, D

        # self._table.setRowCount(0)
        # for pen in deck_pens:
        #     row = self._table.rowCount()
        #     self._table.insertRow(row)
        #     pen_no = getattr(pen, "pen_no", None)
        #     self._table.setItem(
        #         row, 0,
        #         QTableWidgetItem(str(pen_no) if pen_no is not None else pen.name or "—")
        #     )
        #     area_a = getattr(pen, "area_a_m2", None)
        #     area_b = getattr(pen, "area_b_m2", None)
        #     area_c = getattr(pen, "area_c_m2", None)
        #     area_d = getattr(pen, "area_d_m2", None)
        #     if area_a is None and area_b is None and area_c is None and area_d is None:
        #         area_a = getattr(pen, "area_m2", 0.0) or 0.0
        #         if area_a:
        #             sums[0] += area_a
        #         net_area += area_a
        #     else:
        #         for i, v in enumerate([area_a, area_b, area_c, area_d]):
        #             if v is not None:
        #                 sums[i] += v
        #                 net_area += v
        #     self._table.setItem(row, 1, QTableWidgetItem(_fmt_val(area_a)))
        #     self._table.setItem(row, 2, QTableWidgetItem(_fmt_val(area_b)))
        #     self._table.setItem(row, 3, QTableWidgetItem(_fmt_val(area_c)))
        #     self._table.setItem(row, 4, QTableWidgetItem(_fmt_val(area_d)))
        #     self._table.setItem(
        #         row, 5,
        #         QTableWidgetItem(_fmt_val(getattr(pen, "lcg_m", None)))
        #     )
        #     self._table.setItem(
        #         row, 6,
        #         QTableWidgetItem(_fmt_val(getattr(pen, "vcg_m", None)))
        #     )
        #     tcg_a = getattr(pen, "tcg_a_m", None)
        #     tcg_b = getattr(pen, "tcg_b_m", None)
        #     tcg_c = getattr(pen, "tcg_c_m", None)
        #     tcg_d = getattr(pen, "tcg_d_m", None)
        #     if tcg_a is None and tcg_b is None and tcg_c is None and tcg_d is None:
        #         tcg = getattr(pen, "tcg_m", 0.0)
        #         tcg_a = tcg_b = tcg_c = tcg_d = tcg if tcg else None
        #     self._table.setItem(row, 7, QTableWidgetItem(_fmt_val(tcg_a)))
        #     self._table.setItem(row, 8, QTableWidgetItem(_fmt_val(tcg_b)))
        #     self._table.setItem(row, 9, QTableWidgetItem(_fmt_val(tcg_c)))
        #     self._table.setItem(row, 10, QTableWidgetItem(_fmt_val(tcg_d)))

        # # TOTAL row
        # self._table.insertRow(self._table.rowCount())
        # total_row = self._table.rowCount() - 1
        # self._table.setItem(total_row, 0, QTableWidgetItem("TOTAL:"))
        # for c in range(1, 5):
        #     self._table.setItem(
        #         total_row, c,
        #         QTableWidgetItem(f"{sums[c - 1]:.2f}" if sums[c - 1] else "")
        #     )
        # for c in range(5, 12):
        #     self._table.setItem(total_row, c, QTableWidgetItem(""))

        # if net_area == 0.0 and deck_pens:
        #     net_area = sum(getattr(p, "area_m2", 0.0) or 0.0 for p in deck_pens)
        # self._title_label.setText(
        #     f"{self._deck_name} DECK (net area {net_area:.2f} sq.m.)"
        # )


class DeckProfileWidget(QWidget):
    """
    Composite widget:
      - top half: ship profile view
      - bottom half: tabs for each deck (A-H), each showing deck plan + pens/tanks table.
    """

    # Emitted whenever the active deck changes, e.g. "A", "B", "C"
    deck_changed = pyqtSignal(str)
    # Emitted when user selects a tank polygon in a deck view (connects to calculation UI)
    tank_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        splitter = QSplitter(Qt.Orientation.Vertical, self)

        # Top half: profile
        self._profile_view = ProfileView(self)
        splitter.addWidget(self._profile_view)

        # Bottom half: deck tabs
        self._deck_tabs = QTabWidget(self)
        self._deck_tab_widgets: dict[str, DeckTabWidget] = {}

        # Create a tab for each deck A-H
        for deck_letter in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            tab_widget = DeckTabWidget(deck_letter, self)
            self._deck_tab_widgets[deck_letter] = tab_widget
            self._deck_tabs.addTab(tab_widget, f"Deck {deck_letter}")
            tab_widget._deck_view.tank_selected.connect(self.tank_selected.emit)

        splitter.addWidget(self._deck_tabs)
        splitter.setStretchFactor(0, 1)  # Profile gets equal space
        splitter.setStretchFactor(1, 1)   # Tabs get equal space

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(splitter)

        # Wire tab changes
        self._deck_tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int) -> None:
        """Called when user switches to a different deck tab."""
        if 0 <= index < self._deck_tabs.count():
            tab_widget = self._deck_tabs.widget(index)
            if isinstance(tab_widget, DeckTabWidget):
                deck_name = tab_widget._deck_name
                self.deck_changed.emit(deck_name)

    def update_tables(self, pens: list, tanks: list) -> None:
        """Update all deck tab tables with current pens/tanks data."""
        for tab_widget in self._deck_tab_widgets.values():
            tab_widget.update_table(pens, tanks)

    def get_current_deck(self) -> str:
        """Return the currently selected deck letter."""
        current_tab = self._deck_tabs.currentWidget()
        if isinstance(current_tab, DeckTabWidget):
            return current_tab._deck_name
        return "A"
        
    def update_waterline(
        self,
        draft_mid: float,
        draft_aft: float | None = None,
        draft_fwd: float | None = None,
        ship_length: float | None = None,
    ) -> None:
        """Update waterline visualization in profile view."""
        self._profile_view.update_waterline(draft_mid, draft_aft, draft_fwd, ship_length)

