from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QSize, QSignalBlocker, QTimer
from PyQt6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont, QResizeEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsPathItem,
    QGraphicsItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsPolygonItem,
)

from .graphics_views import ShipGraphicsView
from ..utils.sorting import get_pen_sort_key


BASE_DIR = Path(__file__).resolve().parent.parent  # -> senashipping_app
# cads folder is at project root (parent of senashipping_app)
PROJECT_ROOT = BASE_DIR.parent
CAD_DIR = PROJECT_ROOT / "cads"


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
                if et == "LWPOLYLINE":
                    with e.points("xy") as pts:
                        points = [(float(p[0]), float(p[1])) for p in pts]
                else:
                    # POLYLINE (heavy): .points() returns Vec3 iterator
                    points = [(float(p[0]), float(p[1])) for p in e.points()]
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
                closed = getattr(e, "closed", getattr(e, "is_closed", False))
                if closed:
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


class PenMarkerItem(QGraphicsRectItem):
    """
    Selectable, hoverable rectangle marker for a pen. Visual states: normal, hover, selected.
    Used in profile view (LCG/VCG) and deck view (LCG/TCG).
    """
    def __init__(self, pen_id: int, rect: QRectF, parent: QGraphicsItem | None = None) -> None:
        super().__init__(rect, parent)
        self._pen_id = pen_id
        self._hover = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
        self.setAcceptHoverEvents(True)
        self.setData(0, pen_id)
        self._update_style()

    def _update_style(self) -> None:
        if self.isSelected():
            self.setPen(QPen(QColor(0, 150, 255), 1.5))  # Thin blue outline when selected
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))  # No fill, just outline
        elif self._hover:
            self.setPen(QPen(QColor(100, 180, 255), 1.2))  # Lighter blue on hover
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        else:
            self.setPen(QPen(QColor(100, 100, 100), 0.8))  # Thin gray outline
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
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
    def pen_id(self) -> int:
        return self._pen_id


class ProfileView(ShipGraphicsView):
    """
    Top profile view with waterline.

    Shows ship profile with dynamic waterline based on draft and trim.
    Fixed view - no zoom/pan, auto-fits to window size.
    """

    # Emits the full current pen selection for this view.
    pen_selection_changed = pyqtSignal(object)  # set[int]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # Set white background
        self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
        
        # Enable interaction for pen selection with multi-selection
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)  # Enable rubber band selection
        self.setInteractive(True)  # Enable interaction for clickable pens
        
        # Store references to dynamic elements
        self._waterline_item: QGraphicsLineItem | None = None
        self._waterline_fill_item: QGraphicsPolygonItem | None = None
        self._waterline_aft_item: QGraphicsLineItem | None = None
        self._waterline_fwd_item: QGraphicsLineItem | None = None
        self._draft_markers: list[QGraphicsItem] = []
        self._trim_text_item: QGraphicsTextItem | None = None
        self._hull_fill_item: QGraphicsPolygonItem | None = None  # Gray hull fill
        self._pen_markers: dict[int, PenMarkerItem] = {}  # pen_id -> marker
        self._current_pens: list = []
        self._syncing_selection = False
        
        # Ship dimensions for scaling
        self._ship_length: float = 0.0
        self._ship_breadth: float = 0.0
        self._ship_depth: float = 0.0
        self._keel_y: float = 0.0  # Y position of keel baseline in scene coordinates
        
        self._load_profile()
        self._scene.selectionChanged.connect(self._on_selection_changed)
    
    def _on_selection_changed(self) -> None:
        """Emit full selected pen set (multi-selection)."""
        if self._syncing_selection:
            return
        selected_pen_ids = {
            item.pen_id for item in self._scene.selectedItems() if isinstance(item, PenMarkerItem)
        }
        self.pen_selection_changed.emit(set(selected_pen_ids))
    
    def showEvent(self, event) -> None:
        """Fit scene when view is first shown."""
        super().showEvent(event)
        self._fit_scene_to_view()
    
    def wheelEvent(self, event) -> None:
        """Disable zoom - do nothing."""
        event.ignore()
    
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Auto-fit scene to viewport when window is resized."""
        super().resizeEvent(event)
        self._fit_scene_to_view()
    
    def _fit_scene_to_view(self) -> None:
        """Fit all scene items (including waterline) to the viewport so the profile fills the section."""
        if not self._scene:
            return
        bounds = self._scene.itemsBoundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            return
        margin = 0.04  # 4% padding
        w, h = bounds.width(), bounds.height()
        if w > 0 and h > 0:
            bounds = bounds.adjusted(-w * margin, -h * margin, w * margin, h * margin)
        self._scene.setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def fit_to_view(self) -> None:
        """Fit profile drawing to view (same as resize/load)."""
        self._fit_scene_to_view()

    def _load_profile(self) -> None:
        """Load ship profile from DXF. Add gray hull fill when DXF loads. No placeholder."""
        self._scene.clear()
        self._waterline_item = None
        self._waterline_fill_item = None
        self._waterline_aft_item = None
        self._waterline_fwd_item = None
        self._draft_markers.clear()
        self._trim_text_item = None
        self._hull_fill_item = None
        
        dxf_path = CAD_DIR / "profile.dxf"
        if not _load_dxf_into_scene(dxf_path, self._scene):
            # No placeholder: use defaults so waterline/pen logic still works
            self._ship_length = 100.0
            self._ship_breadth = 20.0
            self._ship_depth = 20.0
            self._keel_y = 0.0
        else:
            # Estimate dimensions from scene bounds
            bounds = self._scene.itemsBoundingRect()
            self._ship_length = max(bounds.width(), 100.0)
            self._ship_breadth = max(abs(bounds.height()), 20.0)
            self._ship_depth = self._ship_breadth
            # Assume keel is at the bottom of the bounding box
            self._keel_y = bounds.bottom()
            
            # Add gray hull fill behind DXF lines
            hull_fill_rect = QRectF(bounds.left(), bounds.top(), bounds.width(), bounds.height())
            hull_fill_brush = QBrush(QColor(200, 200, 200, 180))  # Light gray, semi-transparent
            self._hull_fill_item = self._scene.addRect(hull_fill_rect, QPen(Qt.PenStyle.NoPen), hull_fill_brush)
            self._hull_fill_item.setZValue(-10)  # Behind DXF lines and everything else
        
        # Fit when layout is ready so profile fills the section
        QTimer.singleShot(0, self._fit_scene_to_view)
    
    def set_pens(self, pens: list) -> None:
        """Update pens and draw markers in profile view."""
        self._current_pens = pens
        self._update_pen_markers()
    
    def _update_pen_markers(self) -> None:
        """Draw pen markers as rectangles at their LCG/VCG positions, sized by area."""
        # Clear existing markers
        for marker in list(self._pen_markers.values()):
            self._scene.removeItem(marker)
        self._pen_markers.clear()
        
        if not self._current_pens or self._ship_length == 0:
            return
        
        # Calculate scaling: assume pens are positioned relative to ship length
        # For profile view: x = LCG, y = VCG from keel (keel_y - vcg)
        for pen in self._current_pens:
            if not pen.id:
                continue
            
            # Position: LCG along ship, VCG from keel
            x_center = pen.lcg_m
            y_center = self._keel_y - pen.vcg_m  # VCG measured from keel upward
            
            # Size rectangle based on area
            # Convert area (m²) to visual size: assume sqrt(area) gives a reasonable dimension
            # Scale it appropriately for the view
            area_m2 = pen.area_m2 or 10.0  # Default 10 m² if not set
            # Width: proportional to sqrt(area), scaled to ship length
            # Height: fixed small height for profile view (pens are thin vertically)
            width = max(min(area_m2 ** 0.5 * 2.0, self._ship_length * 0.1), 5.0)  # Min 5, max 10% of ship length
            height = max(self._ship_depth * 0.05, 3.0)  # Small fixed height, min 3
            
            rect = QRectF(x_center - width/2, y_center - height/2, width, height)
            marker = PenMarkerItem(pen.id, rect)
            marker.setZValue(100)  # Above hull fill, below waterline
            self._pen_markers[pen.id] = marker
            self._scene.addItem(marker)
    
    def highlight_pen(self, pen_id: int) -> None:
        """Highlight a pen marker by selecting it."""
        if pen_id in self._pen_markers:
            marker = self._pen_markers[pen_id]
            # Clear other selections first
            self._scene.clearSelection()
            marker.setSelected(True)
            # Scroll to marker
            self.ensureVisible(marker)

    def set_selected_pens(self, pen_ids: set[int]) -> None:
        """Programmatically select pens in this view without feedback loops."""
        self._syncing_selection = True
        try:
            with QSignalBlocker(self._scene):
                self._scene.clearSelection()
                for pid in pen_ids or set():
                    item = self._pen_markers.get(pid)
                    if item:
                        item.setSelected(True)
        finally:
            self._syncing_selection = False
            
    def update_waterline(
        self,
        draft_mid: float,
        draft_aft: float | None = None,
        draft_fwd: float | None = None,
        ship_length: float | None = None,
        ship_depth: float | None = None,
        trim_m: float | None = None,
    ) -> None:
        """
        Update waterline visualization based on draft values.
        
        Args:
            draft_mid: Draft at midship (m)
            draft_aft: Draft at aft (m), optional
            draft_fwd: Draft at forward (m), optional
            ship_length: Ship length (m), optional
            ship_depth: Ship depth (m), optional - used for proper scaling
            trim_m: Trim value (m, positive = stern down), optional - for display
        """
        if ship_length:
            self._ship_length = ship_length
        if ship_depth:
            self._ship_depth = ship_depth
            
        if self._ship_length == 0:
            return
        
        # Calculate proper scaling factor based on ship depth or use scene bounds
        if self._ship_depth > 0:
            # Use actual ship depth for scaling
            scene_bounds = self._scene.itemsBoundingRect()
            scene_depth = abs(scene_bounds.height())
            if scene_depth > 0:
                scale_y = scene_depth / self._ship_depth
            else:
                scale_y = self._ship_breadth / 10.0 if self._ship_breadth > 0 else 1.0
        else:
            # Fallback to estimated scaling
            scale_y = self._ship_breadth / 10.0 if self._ship_breadth > 0 else 1.0
        
        # Remove old waterline elements
        if self._waterline_item:
            self._scene.removeItem(self._waterline_item)
            self._waterline_item = None
        if self._waterline_fill_item:
            self._scene.removeItem(self._waterline_fill_item)
            self._waterline_fill_item = None
        if self._waterline_aft_item:
            self._scene.removeItem(self._waterline_aft_item)
            self._waterline_aft_item = None
        if self._waterline_fwd_item:
            self._scene.removeItem(self._waterline_fwd_item)
            self._waterline_fwd_item = None
        for marker in self._draft_markers:
            self._scene.removeItem(marker)
        self._draft_markers.clear()
        if self._trim_text_item:
            self._scene.removeItem(self._trim_text_item)
            self._trim_text_item = None
        
        # Calculate waterline positions (measured from keel upward)
        # In Qt scene coordinates, y increases downward, so we subtract from keel_y
        if draft_aft is not None and draft_fwd is not None:
            # Angled waterline showing trim
            y_aft = self._keel_y - draft_aft * scale_y
            y_fwd = self._keel_y - draft_fwd * scale_y
            
            # Draw waterline fill (semi-transparent blue polygon below waterline)
            fill_path = QPainterPath()
            fill_path.moveTo(0, y_aft)
            fill_path.lineTo(self._ship_length, y_fwd)
            fill_path.lineTo(self._ship_length, self._keel_y)
            fill_path.lineTo(0, self._keel_y)
            fill_path.closeSubpath()
            
            self._waterline_fill_item = self._scene.addPath(
                fill_path,
                QPen(Qt.PenStyle.NoPen),
                QBrush(QColor(100, 150, 255, 60))  # Semi-transparent blue
            )
            self._waterline_fill_item.setZValue(50)
            
            # Draw waterline (blue, thick)
            waterline_pen = QPen(QColor(0, 100, 200), 4)
            self._waterline_item = self._scene.addLine(
                0, y_aft, self._ship_length, y_fwd, waterline_pen
            )
            
            # Add draft markers at aft, mid, and forward
            self._add_draft_marker(0, y_aft, draft_aft, "Aft")
            mid_x = self._ship_length / 2
            y_mid = y_aft + (y_fwd - y_aft) * 0.5
            self._add_draft_marker(mid_x, y_mid, draft_mid, "Mid")
            self._add_draft_marker(self._ship_length, y_fwd, draft_fwd, "Fwd")
            
            # Display trim value
            if trim_m is not None:
                trim_str = f"Trim: {abs(trim_m):.3f}m {'A' if trim_m >= 0 else 'F'}"
                trim_color = QColor(0, 150, 0) if abs(trim_m) < 1.0 else QColor(200, 150, 0) if abs(trim_m) < 2.0 else QColor(200, 0, 0)
                self._trim_text_item = self._scene.addText(trim_str, QFont("Arial", 12, QFont.Weight.Bold))
                self._trim_text_item.setDefaultTextColor(trim_color)
                self._trim_text_item.setPos(mid_x - 50, y_mid - 30)
                self._trim_text_item.setZValue(150)
        else:
            # Level waterline
            y = self._keel_y - draft_mid * scale_y
            
            # Draw waterline fill
            fill_path = QPainterPath()
            fill_path.moveTo(0, y)
            fill_path.lineTo(self._ship_length, y)
            fill_path.lineTo(self._ship_length, self._keel_y)
            fill_path.lineTo(0, self._keel_y)
            fill_path.closeSubpath()
            
            self._waterline_fill_item = self._scene.addPath(
                fill_path,
                QPen(Qt.PenStyle.NoPen),
                QBrush(QColor(100, 150, 255, 60))
            )
            self._waterline_fill_item.setZValue(50)
            
            # Draw waterline (blue, thick)
            waterline_pen = QPen(QColor(0, 100, 200), 4)
            self._waterline_item = self._scene.addLine(
                0, y, self._ship_length, y, waterline_pen
            )
            
            # Add draft marker at midship
            mid_x = self._ship_length / 2
            self._add_draft_marker(mid_x, y, draft_mid, "Mid")
            
        # Bring waterline to front
        if self._waterline_item:
            self._waterline_item.setZValue(100)
        
        # Auto-fit scene to view after updating waterline
        self._fit_scene_to_view()
    
    def _add_draft_marker(self, x: float, y: float, draft_value: float, label: str) -> None:
        """Add a draft measurement marker with label at the specified position."""
        # Draw vertical line marker
        marker_pen = QPen(QColor(0, 100, 200), 2)
        marker_length = 15
        marker_line = self._scene.addLine(
            x, y - marker_length / 2, x, y + marker_length / 2, marker_pen
        )
        marker_line.setZValue(110)
        self._draft_markers.append(marker_line)
        
        # Add horizontal tick
        tick_length = 8
        tick_line = self._scene.addLine(
            x - tick_length / 2, y, x + tick_length / 2, y, marker_pen
        )
        tick_line.setZValue(110)
        self._draft_markers.append(tick_line)
        
        # Add text label
        label_text = f"{label}: {draft_value:.2f}m"
        text_item = self._scene.addText(label_text, QFont("Arial", 10))
        text_item.setDefaultTextColor(QColor(0, 100, 200))
        # Position label above the marker
        text_item.setPos(x - 30, y - 25)
        text_item.setZValue(120)
        self._draft_markers.append(text_item)


class DeckView(ShipGraphicsView):
    """
    Deck plan view: draws DXF or tank polygons. Tank polygons are selectable
    with visual states (normal/hover/selected) and emit tank_selected.
    Fixed view - no zoom/pan, auto-fits to window size.
    """

    # Kept for legacy behavior (other parts may connect).
    tank_selected = pyqtSignal(int)
    # Emits full selection sets from the deck scene.
    selection_changed = pyqtSignal(object, object)  # set[int], set[int]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # Set white background
        self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
        
        # Enable interaction for pen selection with multi-selection
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)  # Enable rubber band selection
        self.setInteractive(True)  # Enable interaction for clickable pens
        
        self._deck_name = ""
        self._pen_markers: dict[int, PenMarkerItem] = {}  # pen_id -> marker
        self._current_pens: list = []
        self._syncing_selection = False
        self._scene.selectionChanged.connect(self._on_selection_changed)
    
    def showEvent(self, event) -> None:
        """Fit scene when view is shown (e.g. tab switched); defer so layout has finished."""
        super().showEvent(event)
        QTimer.singleShot(50, self._fit_scene_to_view)
    
    def wheelEvent(self, event) -> None:
        """Disable zoom - do nothing."""
        event.ignore()
    
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Auto-fit scene to viewport when window is resized."""
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_scene_to_view)
    
    def _fit_scene_to_view(self) -> None:
        """Fit all scene items to the viewport so the deck plan fills the section."""
        if not self._scene:
            return
        # Skip if viewport not yet sized (e.g. tab not visible)
        vp = self.viewport()
        if vp.width() < 20 or vp.height() < 20:
            return
        bounds = self._scene.itemsBoundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            return
        margin = 0.04  # 4% padding
        w, h = bounds.width(), bounds.height()
        if w > 0 and h > 0:
            bounds = bounds.adjusted(-w * margin, -h * margin, w * margin, h * margin)
        self._scene.setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def fit_to_view(self) -> None:
        """Fit deck drawing to view (same as resize/load)."""
        self._fit_scene_to_view()

    def _on_selection_changed(self) -> None:
        """Emit full selected tank/pen sets (multi-selection)."""
        if self._syncing_selection:
            return
        selected_tanks = {
            item.tank_id for item in self._scene.selectedItems() if isinstance(item, TankPolygonItem)
        }
        selected_pens = {
            item.pen_id for item in self._scene.selectedItems() if isinstance(item, PenMarkerItem)
        }
        # Legacy: emit first selected tank id if any
        if selected_tanks:
            self.tank_selected.emit(next(iter(selected_tanks)))
        self.selection_changed.emit(set(selected_pens), set(selected_tanks))

    def set_selected(self, pen_ids: set[int], tank_ids: set[int]) -> None:
        """Programmatically set selection in this deck view without feedback loops."""
        self._syncing_selection = True
        try:
            with QSignalBlocker(self._scene):
                self._scene.clearSelection()
                for pid in pen_ids or set():
                    item = self._pen_markers.get(pid)
                    if item:
                        item.setSelected(True)
                for item in self._scene.items():
                    if isinstance(item, TankPolygonItem) and item.tank_id in (tank_ids or set()):
                        item.setSelected(True)
        finally:
            self._syncing_selection = False

    def load_deck(self, deck_name: str, tanks: list | None = None) -> None:
        """
        Load the given deck: always load deck DXF as background, then draw tank
        polylines on top so they match the drawing. No placeholders.
        """
        self._deck_name = deck_name
        self._scene.clear()
        self._pen_markers.clear()

        # Always load deck DXF first so the drawing is the background
        dxf_path = CAD_DIR / f"deck_{deck_name}.dxf"
        _load_dxf_into_scene(dxf_path, self._scene)

        # Add tank polylines on top (same coordinate system as DXF so they match)
        deck_tanks = []
        if tanks:
            for t in tanks:
                deck = getattr(t, "deck_name", None) or ""
                outline = getattr(t, "outline_xy", None)
                if (deck or "").strip().upper() == deck_name.upper() and outline and len(outline) >= 3:
                    deck_tanks.append(t)
        for tank in deck_tanks:
            path = _outline_to_path(tank.outline_xy)
            item = TankPolygonItem(tank.id or -1, path)
            self._scene.addItem(item)

        # Update pen markers for this deck
        self._update_pen_markers()

        # Set scene rect so view uses full content extent; fit when layout is ready
        bounds = self._scene.itemsBoundingRect()
        if bounds.isValid() and not bounds.isEmpty():
            margin = 0.04
            w, h = bounds.width(), bounds.height()
            if w > 0 and h > 0:
                bounds = bounds.adjusted(-w * margin, -h * margin, w * margin, h * margin)
            self._scene.setSceneRect(bounds)
        QTimer.singleShot(0, self._fit_scene_to_view)
    
    def set_pens(self, pens: list) -> None:
        """Update pens and draw markers in deck view."""
        self._current_pens = pens
        self._update_pen_markers()
    
    def _update_pen_markers(self) -> None:
        """Draw pen markers as rectangles at their LCG/TCG positions, sized by area."""
        # Clear existing markers
        for marker in list(self._pen_markers.values()):
            self._scene.removeItem(marker)
        self._pen_markers.clear()
        
        if not self._current_pens or not self._deck_name:
            return
        
        # Filter pens for this deck
        from .condition_table_widget import _deck_to_letter
        deck_letter = self._deck_name.upper()
        deck_pens = [
            p for p in self._current_pens
            if _deck_to_letter(p.deck or "") == deck_letter
        ]
        
        if not deck_pens:
            return
        
        # Get scene bounds to estimate ship dimensions
        bounds = self._scene.itemsBoundingRect()
        ship_length = max(bounds.width(), 100.0)
        ship_breadth = max(bounds.height(), 20.0)
        
        for pen in deck_pens:
            if not pen.id:
                continue
            
            # Position: LCG along ship, TCG from centerline
            x_center = pen.lcg_m
            y_center = ship_breadth / 2 + pen.tcg_m  # TCG: positive = starboard, negative = port
            
            # Size rectangle based on area
            area_m2 = pen.area_m2 or 10.0
            # For deck view: create square-ish rectangles based on area
            size = max(area_m2 ** 0.5 * 1.5, 3.0)  # Scale sqrt(area), min 3
            
            rect = QRectF(x_center - size/2, y_center - size/2, size, size)
            marker = PenMarkerItem(pen.id, rect)
            marker.setZValue(50)  # Above DXF lines
            self._pen_markers[pen.id] = marker
            self._scene.addItem(marker)

    def set_tanks(self, tanks: list) -> None:
        """
        Redraw deck using tanks that have outline_xy and deck_name matching current deck.
        Call after load_deck when tank list changes (e.g. from condition editor).
        """
        if self._deck_name:
            self.load_deck(self._deck_name, tanks)
            # load_deck already calls _fit_scene_to_view()
    
    def highlight_pen(self, pen_id: int) -> None:
        """Highlight a pen marker by selecting it."""
        if pen_id in self._pen_markers:
            marker = self._pen_markers[pen_id]
            marker.setSelected(True)
            self._scene.clearSelection()
            marker.setSelected(True)


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
        # Sort pens by the 3-level key: number -> letter pattern (A,B,D,C) -> deck
        deck_pens = sorted(deck_pens, key=get_pen_sort_key)

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
    # Emitted when selection changes anywhere in profile/deck views.
    # pens_selected/tanks_selected are `set[int]` or `None` (None = no change to that type).
    selection_changed = pyqtSignal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top: profile view — fixed proportion (~65% height), not resizable
        self._profile_view = ProfileView(self)
        main_layout.addWidget(self._profile_view, 55)

        # Bottom: deck tabs (plan/tank view) — fixed proportion (~35% height), not resizable
        self._deck_tabs = QTabWidget(self)
        self._deck_tab_widgets: dict[str, DeckTabWidget] = {}

        for deck_letter in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            tab_widget = DeckTabWidget(deck_letter, self)
            self._deck_tab_widgets[deck_letter] = tab_widget
            self._deck_tabs.addTab(tab_widget, f"Deck {deck_letter}")
            tab_widget._deck_view.tank_selected.connect(self.tank_selected.emit)
            tab_widget._deck_view.selection_changed.connect(self._on_deck_view_selection_changed)
        
        # Connect profile view pen selection
        self._profile_view.pen_selection_changed.connect(self._on_profile_selection_changed)

        self._syncing_selection = False

        main_layout.addWidget(self._deck_tabs, 45)

        # Wire tab changes
        self._deck_tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int) -> None:
        """Called when user switches to a different deck tab."""
        if 0 <= index < self._deck_tabs.count():
            tab_widget = self._deck_tabs.widget(index)
            if isinstance(tab_widget, DeckTabWidget):
                deck_name = tab_widget._deck_name
                self.deck_changed.emit(deck_name)
                # Fit deck drawing to section once tab has its size (fixes small drawing)
                QTimer.singleShot(50, tab_widget._deck_view.fit_to_view)

    def update_tables(self, pens: list, tanks: list) -> None:
        """Update all deck tab tables with current pens/tanks data."""
        # Update pens in profile and deck views
        self._profile_view.set_pens(pens)
        for tab_widget in self._deck_tab_widgets.values():
            tab_widget.update_table(pens, tanks)
            tab_widget._deck_view.set_pens(pens)

    def _on_profile_selection_changed(self, pen_ids: set[int]) -> None:
        if self._syncing_selection:
            return
        self.selection_changed.emit(set(pen_ids), None)

    def _on_deck_view_selection_changed(self, pen_ids: set[int], tank_ids: set[int]) -> None:
        if self._syncing_selection:
            return
        self.selection_changed.emit(set(pen_ids), set(tank_ids))

    def set_selected(self, pen_ids: set[int], tank_ids: set[int]) -> None:
        """Programmatically set selection in profile + all deck views."""
        self._syncing_selection = True
        try:
            self._profile_view.set_selected_pens(pen_ids)
            for tab_widget in self._deck_tab_widgets.values():
                tab_widget._deck_view.set_selected(pen_ids, tank_ids)
        finally:
            self._syncing_selection = False
    
    def highlight_pen(self, pen_id: int) -> None:
        """Highlight a pen in profile view and deck view."""
        self._profile_view.highlight_pen(pen_id)
        # Also highlight in current deck view
        current_tab = self._deck_tabs.currentWidget()
        if isinstance(current_tab, DeckTabWidget):
            current_tab._deck_view.highlight_pen(pen_id)

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
        ship_depth: float | None = None,
        trim_m: float | None = None,
    ) -> None:
        """Update waterline visualization in profile view."""
        self._profile_view.update_waterline(
            draft_mid, draft_aft, draft_fwd, ship_length, ship_depth, trim_m
        )

