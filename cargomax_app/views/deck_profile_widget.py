from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QComboBox,
    QLabel,
    QGraphicsScene,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
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


class ProfileView(ShipGraphicsView):
    """
    Top profile view with waterline and frame markers.

    Shows ship profile with dynamic waterline based on draft,
    frame markers, and trim indicators.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # Store references to dynamic elements
        self._waterline_item: QGraphicsLineItem | None = None
        self._waterline_aft_item: QGraphicsLineItem | None = None
        self._waterline_fwd_item: QGraphicsLineItem | None = None
        self._frame_markers: list[QGraphicsLineItem] = []
        self._frame_labels: list[QGraphicsTextItem] = []
        
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
        self._frame_markers = []
        self._frame_labels = []
        
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
            
        # Add frame markers
        self._add_frame_markers()
        
        if self._scene.items():
            self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
            
    def _add_frame_markers(self) -> None:
        """Add frame markers along the ship profile."""
        if self._ship_length == 0:
            return
            
        # Add frame markers at regular intervals
        num_frames = 8
        frame_spacing = self._ship_length / (num_frames - 1)
        font = QFont("Arial", 8)
        
        frame_numbers = [41, 59, 77, 83, 101, 121, 140, 159]  # Example frame numbers
        
        for i, frame_num in enumerate(frame_numbers[:num_frames]):
            x = i * frame_spacing
            # Vertical line for frame marker
            marker = self._scene.addLine(
                x, -self._ship_breadth * 0.6,
                x, self._ship_breadth * 0.1,
                QPen(QColor(200, 0, 0), 1, Qt.PenStyle.DashLine)
            )
            self._frame_markers.append(marker)
            
            # Frame label below
            label = self._scene.addText(f"F{frame_num}", font)
            label.setDefaultTextColor(QColor(150, 0, 0))
            label.setPos(x - 10, self._ship_breadth * 0.15)
            self._frame_labels.append(label)
            
        # Add "Long" label with Aft/Fwd indicators
        long_label = self._scene.addText("Long", font)
        long_label.setDefaultTextColor(QColor(100, 100, 100))
        long_label.setPos(self._ship_length * 0.1, self._ship_breadth * 0.2)
        
        aft_label = self._scene.addText("Aft", font)
        aft_label.setDefaultTextColor(QColor(100, 100, 100))
        aft_label.setPos(10, self._ship_breadth * 0.2)
        
        fwd_label = self._scene.addText("Fwd", font)
        fwd_label.setDefaultTextColor(QColor(100, 100, 100))
        fwd_label.setPos(self._ship_length - 30, self._ship_breadth * 0.2)
        
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
    Bottom deck view.

    For now, draws a placeholder rectangle; later this will render the
    per-deck DXFs from CAD_DIR (e.g. 'A DECK.dxf', 'B DECK.dxf', ...).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

    def load_deck(self, deck_name: str) -> None:
        """
        Load the given deck.

        DXF path convention:
          'A' -> 'deck_A.dxf'
          'B' -> 'deck_B.dxf'
          ...
        """
        self._scene.clear()

        dxf_path = CAD_DIR / f"deck_{deck_name}.dxf"
        drew = _load_dxf_into_scene(dxf_path, self._scene)

        if not drew:
            # Fallback placeholder rectangle
            self._scene.addRect(
                QRectF(0, 0, 600, 200),
                QPen(Qt.GlobalColor.darkGreen, 2),
                QBrush(Qt.GlobalColor.green),
            )

        if self._scene.items():
            self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)


class DeckTabWidget(QWidget):
    """
    Widget for a single deck tab: shows deck plan + pens/tanks table.
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

        # Right: pens/tanks table
        self._table = QTableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Type", "Area/Capacity", "Deck"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

    def update_table(self, pens: list, tanks: list) -> None:
        """Update the table to show pens/tanks for this deck."""
        self._table.setRowCount(0)

        # Add pens for this deck
        for pen in pens:
            if (pen.deck or "").strip().upper() == self._deck_name.upper():
                row = self._table.rowCount()
                self._table.insertRow(row)
                self._table.setItem(row, 0, QTableWidgetItem(pen.name))
                self._table.setItem(row, 1, QTableWidgetItem("Pen"))
                self._table.setItem(row, 2, QTableWidgetItem(f"{pen.area_m2:.2f} m²"))
                self._table.setItem(row, 3, QTableWidgetItem(pen.deck))

        # Add tanks for this deck (if tanks have deck field in future)
        for tank in tanks:
            # For now, show all tanks; later filter by tank.deck if that field exists
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(tank.name))
            self._table.setItem(row, 1, QTableWidgetItem("Tank"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{tank.capacity_m3:.2f} m³"))
            self._table.setItem(row, 3, QTableWidgetItem("—"))


class DeckProfileWidget(QWidget):
    """
    Composite widget:
      - top half: ship profile view
      - bottom half: tabs for each deck (A-H), each showing deck plan + pens/tanks table.
    """

    # Emitted whenever the active deck changes, e.g. "A", "B", "C"
    deck_changed = pyqtSignal(str)

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

