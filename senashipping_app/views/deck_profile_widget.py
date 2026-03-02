from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QSize, QSignalBlocker, QTimer, QEvent
from PyQt6.QtGui import QPen, QBrush, QColor, QLinearGradient, QPainterPath, QFont, QResizeEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsPathItem,
    QGraphicsItem,
    QGraphicsEllipseItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsPolygonItem,
)

from senashipping_app.views.graphics_views import ShipGraphicsView
from senashipping_app.utils.sorting import get_pen_sort_key


def _get_cad_dir() -> Path:
    """CAD folder path; works in dev and when frozen (PyInstaller)."""
    from senashipping_app.config.settings import Settings
    return Settings.default().project_root / "cads"


# Vertical offset to shift profile/deck polylines up to match the ship DXF.
# Fraction of drawing height (e.g. 0.02 = 2% up). Use this so the shift is visible
# regardless of DXF units (mm vs m). Set to 0 to disable.
POLYLINE_Y_OFFSET_FRACTION = 0.02

# Profile pen (and tank) marker position offsets so they align with the DXF.
# Tune these then restart the app (or reopen the condition) so pens redraw with the new offset.
#
# Fraction of ship length/depth: X positive = right, Y positive = UP.
PROFILE_PEN_X_OFFSET_FRACTION = 0.0
PROFILE_PEN_Y_OFFSET_FRACTION = 0.02
# Absolute offset in scene units (same as DXF). Use if fraction has no visible effect.
# X positive = right. Y: positive value = move pens UP (we subtract from y).
PROFILE_PEN_X_OFFSET = 0.0
PROFILE_PEN_Y_OFFSET = 0.0  # e.g. 30 to move pens up by 30 units

# Z-order constants for profile/deck scene items (maintainable stacking).
Z_HULL = -10
Z_BASELINE = 0
Z_WATER = 50
Z_WATERLINE_LINE = 100
Z_TANKS_PROFILE = 40
Z_PENS = 80
Z_DRAFT_MARKERS = 110
Z_DRAFT_LABELS = 120
Z_SELECTION = 150


def _load_dxf_into_scene(dxf_path: Path, scene: QGraphicsScene, y_offset: float = 0.0) -> bool:
    """
    Load basic geometry from a DXF file into the given scene.

    Supports LINE, LWPOLYLINE, POLYLINE and entities inside INSERT blocks.

    y_offset: vertical offset in scene coordinates (e.g. -30 to shift content up by 30 px).

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
            scene.addLine(x1, -y1 + y_offset, x2, -y2 + y_offset, pen)
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
                        path.moveTo(x, -y + y_offset)
                        first = False
                    else:
                        path.lineTo(x, -y + y_offset)
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


def _outline_to_path(outline_xy: list, y_offset: float = 0.0) -> QPainterPath:
    """Convert list of (x, y) to QPainterPath (y flipped for Qt). y_offset shifts vertically to match DXF."""
    path = QPainterPath()
    for i, (x, y) in enumerate(outline_xy):
        if i == 0:
            path.moveTo(x, -y + y_offset)
        else:
            path.lineTo(x, -y + y_offset)
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
        """
        Style tank polygon so that in the normal state it matches the
        underlying DXF: thin dark gray lines, no fill. On hover/selection,
        highlight in blue so the chosen tank stands out.
        """
        if self.isSelected():
            self.setPen(QPen(QColor(0, 100, 255), 2.5))
            self.setBrush(QBrush(QColor(100, 160, 255, 80)))
        elif self._hover:
            self.setPen(QPen(QColor(80, 140, 255), 1.5))
            self.setBrush(QBrush(QColor(200, 220, 255, 40)))
        else:
            # Match DXF look: cosmetic hairline dark gray, no fill
            base_pen = QPen(Qt.GlobalColor.darkGray, 0)
            self.setPen(base_pen)
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
    def tank_id(self) -> int:
        return self._tank_id


class PenMarkerItem(QGraphicsRectItem):
    """
    Selectable, hoverable rectangle marker for a pen. Visual states: normal, hover, selected.
    Used in profile view (LCG/VCG) and deck view (LCG/TCG). Shows tooltip on hover.
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
        """
        Style pen marker rectangles: thin dark gray normally, blue when hovered/selected.
        """
        if self.isSelected():
            self.setPen(QPen(QColor(0, 150, 255), 1.5))
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        elif self._hover:
            self.setPen(QPen(QColor(100, 180, 255), 1.2))
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        else:
            self.setPen(QPen(Qt.GlobalColor.darkGray, 0))
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
    # Emits (pen_ids, tank_ids) when selection changes (so profile tanks sync with table).
    selection_changed = pyqtSignal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # Keep DXF profile static within its section (no scrollbars)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # White drawing area; dark surround and rounded frame
        self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
        self.setStyleSheet("""
            QGraphicsView {
                background-color: #2d2d2d;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
            }
        """)

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
        self._hull_fill_item: QGraphicsPolygonItem | None = None
        self._baseline_item: QGraphicsLineItem | None = None
        self._show_waterline = True
        self._show_pens = True
        self._show_draft_marks = True
        self._draft_scale_items: list[QGraphicsItem] = []
        self._cog_items: list[QGraphicsItem] = []
        self._pen_markers: dict[int, PenMarkerItem] = {}
        self._tank_items: list = []
        self._current_pens: list = []
        self._current_tanks: list = []
        self._show_tanks = True
        self._syncing_selection = False
        # Default pen/tank offset so they align with DXF (X: 10, Y up: 3.6)
        self._pen_offset_x = 10.0
        self._pen_offset_y = 3.6

        # Ship dimensions for scaling
        self._ship_length: float = 0.0
        self._ship_breadth: float = 0.0
        self._ship_depth: float = 0.0
        self._keel_y: float = 0.0  # Y position of keel baseline in scene coordinates
        self._hull_bounds: QRectF | None = None  # Fixed bounds of DXF hull/profile
        
        self._load_profile()
        self._scene.selectionChanged.connect(self._on_selection_changed)
    
    def _on_selection_changed(self) -> None:
        """Emit full selected pen set (multi-selection)."""
        if self._syncing_selection:
            return
        selected_pen_ids = {
            item.pen_id for item in self._scene.selectedItems() if isinstance(item, PenMarkerItem)
        }
        selected_tank_ids = {
            item.tank_id for item in self._scene.selectedItems() if isinstance(item, TankPolygonItem)
        }
        self.pen_selection_changed.emit(set(selected_pen_ids))
        self.selection_changed.emit(set(selected_pen_ids), set(selected_tank_ids))
    
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

    def _metric_scale(self) -> float:
        """
        Scale factor for draft/trim graphics based on current viewport size.

        Keeps labels and markers visually balanced on both small and large
        screens instead of using hard-coded pixel sizes.
        """
        view = self.viewport()
        if not view:
            return 1.0
        h = max(1, view.height())
        # Around 320 px tall -> scale 1.0, clamp to a sensible range
        scale = h / 320.0
        return max(0.7, min(1.4, scale))

    def _metric_font(self, base_px: int, weight: int = QFont.Weight.Medium) -> QFont:
        """Return a font whose pixel size scales with the viewport."""
        scale = self._metric_scale()
        size = int(round(base_px * scale))
        size = max(7, min(12, size))
        return QFont("Arial", size, weight)
    
    def _fit_scene_to_view(self) -> None:
        """
        Fit the fixed DXF hull/profile to the viewport so the profile fills
        the section, without the waterline changing the zoom/position.
        """
        if not self._scene:
            return

        # Prefer the stored hull/profile bounds so waterline and markers do not
        # affect the automatic fitting/zoom.
        if self._hull_bounds is not None and self._hull_bounds.isValid() and not self._hull_bounds.isEmpty():
            bounds = self._hull_bounds
        else:
            bounds = self._scene.itemsBoundingRect()

        if not bounds.isValid() or bounds.isEmpty():
            return
        margin = 0.04  # 4% padding
        w, h = bounds.width(), bounds.height()
        if w > 0 and h > 0:
            bounds = bounds.adjusted(-w * margin, -h * margin, w * margin, h * margin)
        self._scene.setSceneRect(bounds)
        if self.width() > 0 and self.height() > 0:
            self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def fit_to_view(self) -> None:
        """Fit profile drawing to view (same as resize/load)."""
        self._fit_scene_to_view()

    def _load_profile(self) -> None:
        """Load ship profile from DXF. Add hull fill and keel baseline. No placeholder."""
        self._scene.clear()
        self._waterline_item = None
        self._waterline_fill_item = None
        self._waterline_aft_item = None
        self._waterline_fwd_item = None
        self._draft_markers.clear()
        self._trim_text_item = None
        self._hull_fill_item = None
        self._baseline_item = None
        self._hull_bounds = None
        
        dxf_path = _get_cad_dir() / "profile.dxf"
        if not _load_dxf_into_scene(dxf_path, self._scene, y_offset=0.0):
            # No placeholder: use defaults so waterline/pen logic still works
            self._ship_length = 100.0
            self._ship_breadth = 20.0
            self._ship_depth = 20.0
            self._keel_y = 0.0
            # Synthetic hull bounds so fit/zoom stays stable
            self._hull_bounds = QRectF(0.0, -self._ship_depth, self._ship_length, self._ship_depth)
        else:
            # Compute offset as fraction of drawing height so shift is visible in any DXF units
            bounds = self._scene.itemsBoundingRect()
            y_offset = -bounds.height() * POLYLINE_Y_OFFSET_FRACTION if POLYLINE_Y_OFFSET_FRACTION else 0.0
            if y_offset != 0.0:
                self._scene.clear()
                _load_dxf_into_scene(dxf_path, self._scene, y_offset=y_offset)
                bounds = self._scene.itemsBoundingRect()
            self._ship_length = max(bounds.width(), 100.0)
            # Keel at bottom of bounding box; ship depth = vertical extent
            self._keel_y = bounds.bottom()
            self._ship_depth = abs(bounds.height())
            self._ship_breadth = max(self._ship_depth, 20.0)
            # Freeze hull/profile bounds so waterline changes do not move the DXF
            self._hull_bounds = bounds

            # Hull fill: very light gray with slight gradient and sharp outline
            hull_fill_rect = QRectF(bounds.left(), bounds.top(), bounds.width(), bounds.height())
            hull_gradient = QLinearGradient(0, bounds.top(), 0, bounds.bottom())
            hull_gradient.setColorAt(0, QColor(245, 245, 245))
            hull_gradient.setColorAt(1, QColor(235, 235, 235))
            hull_fill_brush = QBrush(hull_gradient)
            outline_pen = QPen(QColor(100, 100, 100), 0)
            outline_pen.setCosmetic(True)
            self._hull_fill_item = self._scene.addRect(hull_fill_rect, outline_pen, hull_fill_brush)
            self._hull_fill_item.setZValue(Z_HULL)

            # Dashed keel baseline (reference line)
            baseline_pen = QPen(QColor(120, 120, 120), 0)
            baseline_pen.setStyle(Qt.PenStyle.DashLine)
            baseline_pen.setCosmetic(True)
            self._baseline_item = self._scene.addLine(
                bounds.left(), self._keel_y, bounds.right(), self._keel_y, baseline_pen
            )
            self._baseline_item.setZValue(Z_BASELINE)
        
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

        # Total offset: constants + runtime (toolbar spinboxes); positive Y = move pens up
        dx = (self._ship_length * PROFILE_PEN_X_OFFSET_FRACTION) + PROFILE_PEN_X_OFFSET + self._pen_offset_x
        dy_up = (self._ship_depth * PROFILE_PEN_Y_OFFSET_FRACTION) + PROFILE_PEN_Y_OFFSET + self._pen_offset_y

        # For profile view: x = LCG, y = VCG from keel (keel_y - vcg)
        for pen in self._current_pens:
            if not pen.id:
                continue

            # Position: LCG along ship, VCG from keel; apply alignment offsets
            x_center = pen.lcg_m + dx
            y_center = self._keel_y - pen.vcg_m - dy_up  # dy_up > 0 moves pens up

            # Size rectangle based on area
            # Convert area (m²) to visual size: assume sqrt(area) gives a reasonable dimension
            # Scale it appropriately for the view
            area_m2 = pen.area_m2 or 10.0  # Default 10 m² if not set
            # Width: proportional to sqrt(area), scaled to ship length
            # Height: fixed small height for profile view (pens are thin vertically)
            width = max(min(area_m2 ** 0.5 * 2.0, self._ship_length * 0.1), 5.0)  # Min 5, max 10% of ship length
            height = max(self._ship_depth * 0.05, 3.0)  # Small fixed height, min 3

            rect = QRectF(x_center - width / 2, y_center - height / 2, width, height)
            marker = PenMarkerItem(pen.id, rect)
            marker.setZValue(Z_PENS)
            name = getattr(pen, "name", None) or f"Pen {pen.id}"
            area = pen.area_m2 or 0.0
            lcg = pen.lcg_m
            vcg = pen.vcg_m
            tcg = getattr(pen, "tcg_m", 0.0)
            marker.setToolTip(
                f"{name}\n"
                f"Area: {area:.2f} m²\n"
                f"LCG: {lcg:.2f} m\n"
                f"VCG: {vcg:.2f} m\n"
                f"TCG: {tcg:.2f} m"
            )
            self._pen_markers[pen.id] = marker
            self._scene.addItem(marker)
        self._apply_profile_visibility()

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

    def set_selected_tanks(self, tank_ids: set[int]) -> None:
        """Programmatically set tank selection in profile view without feedback loops."""
        self._syncing_selection = True
        try:
            with QSignalBlocker(self._scene):
                for item in self._tank_items:
                    item.setSelected(getattr(item, "tank_id", -1) in (tank_ids or set()))
        finally:
            self._syncing_selection = False

    def _clear_waterline_items(self) -> None:
        """Remove all waterline-related items from the scene."""
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
        for item in self._draft_scale_items:
            self._scene.removeItem(item)
        self._draft_scale_items.clear()
        for item in self._cog_items:
            self._scene.removeItem(item)
        self._cog_items.clear()
        if self._trim_text_item:
            self._scene.removeItem(self._trim_text_item)
            self._trim_text_item = None

    def clear_waterline(self) -> None:
        """Public helper to clear waterline and refit the profile view."""
        self._clear_waterline_items()
        self._fit_scene_to_view()

    def update_waterline(
        self,
        draft_mid: float,
        draft_aft: float | None = None,
        draft_fwd: float | None = None,
        ship_length: float | None = None,
        ship_depth: float | None = None,
        trim_m: float | None = None,
        cog_lcg_m: float | None = None,
        cog_vcg_m: float | None = None,
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
            cog_lcg_m: Center of gravity LCG (m), optional - draw G marker
            cog_vcg_m: Center of gravity VCG (m), optional - draw G marker
        """
        if ship_length:
            self._ship_length = ship_length
        if ship_depth:
            self._ship_depth = ship_depth

        if self._ship_length == 0:
            return

        # Calculate proper scaling factor so draft (in metres) scales with the
        # actual ship depth. Prefer the frozen hull/profile bounds so visual
        # scaling is tied to the hull height, not transient items.
        if self._ship_depth > 0:
            if self._hull_bounds is not None and self._hull_bounds.isValid():
                scene_depth = abs(self._hull_bounds.height())
            else:
                scene_bounds = self._scene.itemsBoundingRect()
                scene_depth = abs(scene_bounds.height())
            if scene_depth > 0:
                scale_y = scene_depth / self._ship_depth
            else:
                scale_y = self._ship_breadth / 10.0 if self._ship_breadth > 0 else 1.0
        else:
            # Fallback when we don't know ship depth: approximate using breadth
            scale_y = self._ship_breadth / 10.0 if self._ship_breadth > 0 else 1.0

        # Remove old waterline elements before drawing the new one
        self._clear_waterline_items()

        # Calculate waterline positions (measured from keel upward)
        # In Qt scene coordinates, y increases downward, so we subtract from keel_y.
        # Use hull bounds so the waterline aligns horizontally with the DXF profile
        # instead of starting at scene x=0.
        if self._hull_bounds is not None and self._hull_bounds.isValid():
            x_left = self._hull_bounds.left()
            x_right = self._hull_bounds.right()
            # Clamp waterline to ship height: never draw above the deck (hull top)
            hull_top_y = self._hull_bounds.top()
        else:
            x_left = 0.0
            x_right = self._ship_length
            hull_top_y = None

        if draft_aft is not None and draft_fwd is not None:
            # Angled waterline showing trim
            y_aft = self._keel_y - draft_aft * scale_y
            y_fwd = self._keel_y - draft_fwd * scale_y
            if hull_top_y is not None:
                y_aft = max(y_aft, hull_top_y)
                y_fwd = max(y_fwd, hull_top_y)

            # Draw waterline fill (gradient from waterline down to keel)
            fill_path = QPainterPath()
            fill_path.moveTo(x_left, y_aft)
            fill_path.lineTo(x_right, y_fwd)
            fill_path.lineTo(x_right, self._keel_y)
            fill_path.lineTo(x_left, self._keel_y)
            fill_path.closeSubpath()

            y_top = min(y_aft, y_fwd)
            gradient = QLinearGradient(0, y_top, 0, self._keel_y)
            gradient.setColorAt(0, QColor(80, 140, 230, 60))
            gradient.setColorAt(1, QColor(80, 140, 230, 20))
            self._waterline_fill_item = self._scene.addPath(
                fill_path,
                QPen(Qt.PenStyle.NoPen),
                QBrush(gradient)
            )
            self._waterline_fill_item.setZValue(Z_WATER)

            # Draw a finer, less dominant waterline
            waterline_pen = QPen(QColor(0, 80, 160), 1.5)
            waterline_pen.setCosmetic(True)
            self._waterline_item = self._scene.addLine(
                x_left, y_aft, x_right, y_fwd, waterline_pen
            )
            self._waterline_item.setZValue(Z_WATERLINE_LINE)

            # Add draft markers at aft, mid, and forward
            self._add_draft_marker(x_left, y_aft, draft_aft, "Aft")
            mid_x = (x_left + x_right) / 2.0
            y_mid = y_aft + (y_fwd - y_aft) * 0.5
            self._add_draft_marker(mid_x, y_mid, draft_mid, "Mid")
            self._add_draft_marker(x_right, y_fwd, draft_fwd, "Fwd")

            # Display trim value and trim angle (degrees)
            if trim_m is not None:
                trim_str = f"Trim {abs(trim_m):.2f} m {'A' if trim_m >= 0 else 'F'}"
                if self._ship_length and self._ship_length > 0:
                    trim_angle_deg = math.degrees(math.atan(abs(trim_m) / self._ship_length))
                    trim_str += f"  Angle: {trim_angle_deg:.2f}°"
                trim_color = QColor(0, 150, 0) if abs(trim_m) < 1.0 else QColor(200, 150, 0) if abs(trim_m) < 2.0 else QColor(200, 0, 0)
                trim_font = QFont("Arial", 8, QFont.Weight.Medium)
                self._trim_text_item = self._scene.addText(trim_str, trim_font)
                self._trim_text_item.setDefaultTextColor(trim_color)
                self._trim_text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                self._trim_text_item.setPos(mid_x - 40, y_mid - 22)
                self._trim_text_item.setZValue(Z_SELECTION)
        else:
            # Level waterline
            y = self._keel_y - draft_mid * scale_y
            if hull_top_y is not None:
                y = max(y, hull_top_y)

            # Draw waterline fill (gradient from waterline down to keel)
            fill_path = QPainterPath()
            fill_path.moveTo(x_left, y)
            fill_path.lineTo(x_right, y)
            fill_path.lineTo(x_right, self._keel_y)
            fill_path.lineTo(x_left, self._keel_y)
            fill_path.closeSubpath()

            gradient = QLinearGradient(0, y, 0, self._keel_y)
            gradient.setColorAt(0, QColor(80, 140, 230, 60))
            gradient.setColorAt(1, QColor(80, 140, 230, 20))
            self._waterline_fill_item = self._scene.addPath(
                fill_path,
                QPen(Qt.PenStyle.NoPen),
                QBrush(gradient)
            )
            self._waterline_fill_item.setZValue(Z_WATER)

            # Draw a finer, less dominant waterline
            waterline_pen = QPen(QColor(0, 80, 160), 1.5)
            waterline_pen.setCosmetic(True)
            self._waterline_item = self._scene.addLine(
                x_left, y, x_right, y, waterline_pen
            )
            self._waterline_item.setZValue(Z_WATERLINE_LINE)

            # Add draft marker at midship
            mid_x = (x_left + x_right) / 2.0
            self._add_draft_marker(mid_x, y, draft_mid, "Mid")
            # Optional trim label for level waterline when trim_m provided
            if trim_m is not None and self._ship_length and self._ship_length > 0:
                trim_angle_deg = math.degrees(math.atan(abs(trim_m) / self._ship_length))
                trim_str = f"Trim {abs(trim_m):.2f} m  Angle: {trim_angle_deg:.2f}°"
                trim_font = QFont("Arial", 8, QFont.Weight.Medium)
                self._trim_text_item = self._scene.addText(trim_str, trim_font)
                self._trim_text_item.setDefaultTextColor(QColor(100, 100, 100))
                self._trim_text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                self._trim_text_item.setPos(mid_x - 40, y - 22)
                self._trim_text_item.setZValue(Z_SELECTION)

        # Bring waterline to front
        if self._waterline_item:
            self._waterline_item.setZValue(Z_WATERLINE_LINE)

        # Draft scale on side at midship (vertical scale in m)
        self._add_draft_scale(x_left, x_right, scale_y)

        # Center of gravity marker (G point) if provided
        if cog_lcg_m is not None and cog_vcg_m is not None and self._hull_bounds is not None:
            self._add_cog_marker(cog_lcg_m, cog_vcg_m, scale_y, x_left, x_right)

        # Apply visibility toggles
        self._apply_profile_visibility()

    def _add_draft_marker(self, x: float, y: float, draft_value: float, label: str) -> None:
        """Add a subtle draft measurement marker with label at the specified position."""
        marker_pen = QPen(QColor(0, 100, 200), 0)
        marker_pen.setCosmetic(True)
        marker_length = 6.0
        marker_line = self._scene.addLine(
            x, y - marker_length / 2, x, y + marker_length / 2, marker_pen
        )
        marker_line.setZValue(Z_DRAFT_MARKERS)
        self._draft_markers.append(marker_line)
        
        # Add compact text label with clearer number formatting
        label_text = f"{label} {draft_value:.2f} m"
        text_font = QFont("Arial", 8, QFont.Weight.Medium)
        text_item = self._scene.addText(label_text, text_font)
        text_item.setDefaultTextColor(QColor(0, 100, 200))
        # Keep label size constant even if the view is rescaled
        text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        # Position label just above and slightly to the left of the marker
        text_item.setPos(x - 24, y - 18)
        text_item.setZValue(Z_DRAFT_LABELS)
        self._draft_markers.append(text_item)

    def _add_draft_scale(self, x_left: float, x_right: float, scale_y: float) -> None:
        """Add vertical draft scale at midship (draft values in m)."""
        mid_x = (x_left + x_right) / 2.0
        scale_x = mid_x - 12.0  # Left of center
        # Tick every 0.5 m from 0 to ship_depth
        draft_max = self._ship_depth if self._ship_depth > 0 else 10.0
        step = 0.5
        pen_scale = QPen(QColor(100, 100, 100), 0)
        pen_scale.setCosmetic(True)
        font = QFont("Arial", 7, QFont.Weight.Normal)
        d = 0.0
        while d <= draft_max:
            y_scene = self._keel_y - d * scale_y
            line = self._scene.addLine(scale_x, y_scene, scale_x + 4, y_scene, pen_scale)
            line.setZValue(Z_DRAFT_MARKERS)
            self._draft_scale_items.append(line)
            txt = self._scene.addText(f"{d:.1f}", font)
            txt.setDefaultTextColor(QColor(80, 80, 80))
            txt.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            txt.setPos(scale_x - 18, y_scene - 4)
            txt.setZValue(Z_DRAFT_LABELS)
            self._draft_scale_items.append(txt)
            d += step

    def _add_cog_marker(
        self, cog_lcg_m: float, cog_vcg_m: float, scale_y: float, x_left: float, x_right: float
    ) -> None:
        """Draw G (center of gravity) marker: LCG vertical line, VCG horizontal, small cross."""
        x_g = cog_lcg_m
        y_g = self._keel_y - cog_vcg_m * scale_y
        cog_pen = QPen(QColor(180, 0, 0), 0)
        cog_pen.setCosmetic(True)
        # Vertical line at LCG
        vl = self._scene.addLine(x_g, self._hull_bounds.top(), x_g, self._keel_y, cog_pen)
        vl.setZValue(Z_SELECTION - 5)
        self._cog_items.append(vl)
        # Horizontal line at VCG
        hl = self._scene.addLine(x_left, y_g, x_right, y_g, cog_pen)
        hl.setZValue(Z_SELECTION - 5)
        self._cog_items.append(hl)
        # Small cross/ellipse at G
        r = 3.0
        ell = self._scene.addEllipse(x_g - r, y_g - r, 2 * r, 2 * r, cog_pen, QBrush(QColor(200, 50, 50, 120)))
        ell.setZValue(Z_SELECTION)
        self._cog_items.append(ell)
        label = self._scene.addText("G", QFont("Arial", 7, QFont.Weight.Bold))
        label.setDefaultTextColor(QColor(180, 0, 0))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(x_g + 4, y_g - 5)
        label.setZValue(Z_SELECTION)
        self._cog_items.append(label)

    def _apply_profile_visibility(self) -> None:
        """Show/hide waterline, pens, draft markers per toggles."""
        if self._waterline_item:
            self._waterline_item.setVisible(self._show_waterline)
        if self._waterline_fill_item:
            self._waterline_fill_item.setVisible(self._show_waterline)
        for m in self._draft_markers:
            m.setVisible(self._show_draft_marks)
        for m in self._draft_scale_items:
            m.setVisible(self._show_draft_marks)
        if self._trim_text_item:
            self._trim_text_item.setVisible(self._show_waterline)
        for marker in self._pen_markers.values():
            marker.setVisible(self._show_pens)
        for item in self._tank_items:
            item.setVisible(self._show_tanks)

    def set_show_waterline(self, show: bool) -> None:
        self._show_waterline = show
        self._apply_profile_visibility()

    def set_show_pens(self, show: bool) -> None:
        self._show_pens = show
        self._apply_profile_visibility()

    def set_show_draft_marks(self, show: bool) -> None:
        self._show_draft_marks = show
        self._apply_profile_visibility()

    def set_show_tanks(self, show: bool) -> None:
        self._show_tanks = show
        self._apply_profile_visibility()

    def set_pen_offset(self, x: float, y: float) -> None:
        """Set runtime offset for pens/tanks (no restart). Positive y = move up. Redraws immediately."""
        self._pen_offset_x = x
        self._pen_offset_y = y
        self._update_pen_markers()
        if self._current_tanks and self._hull_bounds and self._ship_length:
            self.set_tanks(self._current_tanks)  # re-apply tanks with new offset

    def set_tanks(self, tanks: list) -> None:
        """Draw tank polylines on the profile (longitudinal band per tank at VCG)."""
        for item in self._tank_items:
            self._scene.removeItem(item)
        self._tank_items.clear()
        self._current_tanks = tanks or []

        if not self._current_tanks or not self._hull_bounds or self._ship_length == 0:
            self._apply_profile_visibility()
            return

        x_left = self._hull_bounds.left()
        x_right = self._hull_bounds.right()
        # Height of tank band in profile (metres in scene if 1:1, else scale)
        tank_height = max(self._ship_depth * 0.04, 1.0)
        dx = (self._ship_length * PROFILE_PEN_X_OFFSET_FRACTION) + PROFILE_PEN_X_OFFSET + self._pen_offset_x
        dy_up = (self._ship_depth * PROFILE_PEN_Y_OFFSET_FRACTION) + PROFILE_PEN_Y_OFFSET + self._pen_offset_y

        for tank in self._current_tanks:
            tid = getattr(tank, "id", None) or -1
            kg_m = float(getattr(tank, "kg_m", 0.0) or 0.0)
            lcg_m = float(getattr(tank, "lcg_m", 0.0) or 0.0)
            outline = getattr(tank, "outline_xy", None)

            if outline and len(outline) >= 2:
                xs = [float(p[0]) for p in outline]
                x_min, x_max = min(xs), max(xs)
                x_center = (x_min + x_max) / 2.0
                half_w = max((x_max - x_min) / 2.0, 1.0)
            else:
                x_center = lcg_m
                half_w = 2.0

            x_center += dx
            y_center = self._keel_y - kg_m - dy_up
            path = QPainterPath()
            path.addRect(
                x_center - half_w,
                y_center - tank_height / 2.0,
                half_w * 2.0,
                tank_height,
            )
            item = TankPolygonItem(tid, path)
            item.setZValue(Z_TANKS_PROFILE)
            item.setVisible(self._show_tanks)
            name = getattr(tank, "name", None) or f"Tank {tid}"
            item.setToolTip(f"{name}\nVCG: {kg_m:.2f} m\nLCG: {lcg_m:.2f} m")
            self._tank_items.append(item)
            self._scene.addItem(item)

        self._apply_profile_visibility()


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

        # Keep DXF deck plan static within its section (no scrollbars)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Set white background
        self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))

        # Enable interaction for pen selection with multi-selection
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)  # Enable rubber band selection
        self.setInteractive(True)  # Enable interaction for clickable pens
        
        self._deck_name = ""
        self._pen_markers: dict[int, PenMarkerItem] = {}
        self._tank_polygon_items: list = []
        self._current_pens: list = []
        self._syncing_selection = False
        self._show_tanks = True
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def set_show_tanks(self, show: bool) -> None:
        self._show_tanks = show
        for item in self._tank_polygon_items:
            item.setVisible(show)

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
        if self.width() > 0 and self.height() > 0:
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
        self._tank_polygon_items.clear()

        # Load deck DXF first; use fraction-of-height offset so shift is visible in any DXF units
        dxf_path = _get_cad_dir() / f"deck_{deck_name}.dxf"
        _load_dxf_into_scene(dxf_path, self._scene, y_offset=0.0)
        bounds = self._scene.itemsBoundingRect()
        y_offset = -bounds.height() * POLYLINE_Y_OFFSET_FRACTION if POLYLINE_Y_OFFSET_FRACTION else 0.0
        if y_offset != 0.0:
            self._scene.clear()
            _load_dxf_into_scene(dxf_path, self._scene, y_offset=y_offset)

        # Add tank polylines on top with same y_offset so they align with the deck DXF
        deck_tanks = []
        if tanks:
            for t in tanks:
                deck = getattr(t, "deck_name", None) or ""
                outline = getattr(t, "outline_xy", None)
                if (deck or "").strip().upper() == deck_name.upper() and outline and len(outline) >= 3:
                    deck_tanks.append(t)

        for tank in deck_tanks:
            path = _outline_to_path(tank.outline_xy, y_offset=y_offset)
            item = TankPolygonItem(tank.id or -1, path)
            item.setVisible(self._show_tanks)
            self._tank_polygon_items.append(item)
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
        from senashipping_app.views.condition_table_widget import _deck_to_letter
        deck_letter = self._deck_name.upper()
        deck_pens = [
            p for p in self._current_pens
            if _deck_to_letter(p.deck or "") == deck_letter
        ]

        if not deck_pens:
            return

        # Map ship LCG/TCG range to the DXF bounding box by scaling and centring,
        # so pen rectangles sit on top of the drawing even if the absolute
        # origins differ.
        bounds = self._scene.itemsBoundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            return

        lcg_vals = [float(getattr(p, "lcg_m", 0.0) or 0.0) for p in deck_pens]
        tcg_vals = [float(getattr(p, "tcg_m", 0.0) or 0.0) for p in deck_pens]
        lcg_min, lcg_max = min(lcg_vals), max(lcg_vals)
        tcg_min, tcg_max = min(tcg_vals), max(tcg_vals)

        span_lcg = max(lcg_max - lcg_min, 1e-6)
        span_tcg = max(max(abs(tcg_min), abs(tcg_max)), 1e-6)

        scale_x = bounds.width() / span_lcg
        scale_y = (bounds.height() / 2.0) / span_tcg

        cx0 = bounds.left()
        cy0 = bounds.center().y()

        for pen in deck_pens:
            if not pen.id:
                continue

            lcg = float(getattr(pen, "lcg_m", 0.0) or 0.0)
            tcg = float(getattr(pen, "tcg_m", 0.0) or 0.0)

            # X: map [lcg_min, lcg_max] -> [bounds.left, bounds.right]
            x_center = cx0 + (lcg - lcg_min) * scale_x
            # Y: map TCG (m from CL) symmetrically about the vertical centre of bounds
            y_center = cy0 - tcg * scale_y

            area_m2 = pen.area_m2 or 10.0
            size = max(area_m2 ** 0.5 * 1.5, 3.0)

            rect = QRectF(x_center - size / 2, y_center - size / 2, size, size)
            marker = PenMarkerItem(pen.id, rect)
            marker.setZValue(Z_PENS)
            name = getattr(pen, "name", None) or f"Pen {pen.id}"
            area = pen.area_m2 or 0.0
            vcg = getattr(pen, "vcg_m", 0.0)
            marker.setToolTip(
                f"{name}\nArea: {area:.2f} m²\nLCG: {lcg:.2f} m\nVCG: {vcg:.2f} m\nTCG: {tcg:.2f} m"
            )
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title above the deck DXF
        self._title_label = QLabel(self)
        self._title_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(self._title_label)

        # Deck plan drawing only (no side table)
        self._deck_view = DeckView(self)
        self._deck_view.load_deck(deck_name)
        layout.addWidget(self._deck_view, 1)

    def update_table(self, pens: list, tanks: list) -> None:
        """Update the deck view (tank polygons when outline_xy present) and title text."""
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

        if net_area == 0.0 and deck_pens:
            net_area = sum(
                getattr(p, "area_m2", 0.0) or 0.0 for p in deck_pens
            )
        self._title_label.setText(
            f"{self._deck_name} DECK (net area {net_area:.2f} sq.m.)"
        )


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

        # Profile view (created first so toolbar can connect to it)
        self._profile_view = ProfileView(self)

        # Toolbar: toggles above profile
        toolbar = QFrame(self)
        toolbar.setStyleSheet("QFrame { background: #f0f0f0; border-bottom: 1px solid #d0d0d0; }")
        tool_layout = QHBoxLayout(toolbar)
        tool_layout.setContentsMargins(6, 4, 6, 4)
        tool_layout.setSpacing(12)
        self._chk_waterline = QCheckBox("Show Waterline")
        self._chk_waterline.setChecked(True)
        self._chk_waterline.toggled.connect(self._profile_view.set_show_waterline)
        tool_layout.addWidget(self._chk_waterline)
        self._chk_pens = QCheckBox("Show Pens")
        self._chk_pens.setChecked(True)
        self._chk_pens.toggled.connect(self._profile_view.set_show_pens)
        tool_layout.addWidget(self._chk_pens)
        self._chk_draft_marks = QCheckBox("Show Draft Marks")
        self._chk_draft_marks.setChecked(True)
        self._chk_draft_marks.toggled.connect(self._profile_view.set_show_draft_marks)
        tool_layout.addWidget(self._chk_draft_marks)
        self._chk_tanks = QCheckBox("Show Tanks")
        self._chk_tanks.setChecked(True)
        self._chk_tanks.toggled.connect(self._on_show_tanks_toggled)
        tool_layout.addWidget(self._chk_tanks)
        tool_layout.addStretch()
        main_layout.addWidget(toolbar)
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

        self._profile_view.pen_selection_changed.connect(self._on_profile_selection_changed)
        self._profile_view.selection_changed.connect(self._on_profile_selection_changed_full)
        self._syncing_selection = False
        main_layout.addWidget(self._deck_tabs, 45)
        self._deck_tabs.currentChanged.connect(self._on_tab_changed)

        # Install event filter on view and viewport - key events may go to viewport when focused
        for w in (self._profile_view, self._profile_view.viewport()):
            w.installEventFilter(self)
        for tab_widget in self._deck_tab_widgets.values():
            deck_view = tab_widget._deck_view
            for w in (deck_view, deck_view.viewport()):
                w.installEventFilter(self)

    def _on_tab_changed(self, index: int) -> None:
        """Called when user switches to a different deck tab."""
        if 0 <= index < self._deck_tabs.count():
            tab_widget = self._deck_tabs.widget(index)
            if isinstance(tab_widget, DeckTabWidget):
                deck_name = tab_widget._deck_name
                self.deck_changed.emit(deck_name)
                tab_widget._deck_view.set_show_tanks(self._chk_tanks.isChecked())
                QTimer.singleShot(50, tab_widget._deck_view.fit_to_view)

    def _on_show_tanks_toggled(self, checked: bool) -> None:
        """Propagate Show Tanks toggle to profile and all deck views."""
        self._profile_view.set_show_tanks(checked)
        for tab_widget in self._deck_tab_widgets.values():
            tab_widget._deck_view.set_show_tanks(checked)

    def update_tables(self, pens: list, tanks: list) -> None:
        """Update all deck tab tables with current pens/tanks data."""
        self._profile_view.set_pens(pens)
        self._profile_view.set_tanks(tanks)
        for tab_widget in self._deck_tab_widgets.values():
            tab_widget.update_table(pens, tanks)
            tab_widget._deck_view.set_pens(pens)

    def _on_profile_selection_changed(self, pen_ids: set[int]) -> None:
        if self._syncing_selection:
            return
        self.selection_changed.emit(set(pen_ids), None)
        # Propagate to deck views so pen lights up in deck drawing too
        self.set_selected(pen_ids, set())

    def _on_profile_selection_changed_full(self, pen_ids: set, tank_ids: set) -> None:
        if self._syncing_selection:
            return
        self.selection_changed.emit(set(pen_ids or ()), set(tank_ids or ()))
        # Propagate to deck views so pen lights up in deck drawing too
        self.set_selected(set(pen_ids or ()), set(tank_ids or ()))

    def _on_deck_view_selection_changed(self, pen_ids: set[int], tank_ids: set[int]) -> None:
        if self._syncing_selection:
            return
        self.selection_changed.emit(set(pen_ids), set(tank_ids))
        # Propagate to profile view and other deck tabs so pen lights up everywhere
        self.set_selected(set(pen_ids), set(tank_ids))

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """ESC clears selection when pressed in profile or deck view."""
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
        ):
            # Clear selection directly on profile and all deck scenes to avoid any
            # feedback-loop issues with higher-level helpers.
            if self._profile_view and getattr(self._profile_view, "_scene", None):
                self._profile_view._scene.clearSelection()
            for tab_widget in self._deck_tab_widgets.values():
                deck_view = getattr(tab_widget, "_deck_view", None)
                scene = getattr(deck_view, "_scene", None) if deck_view is not None else None
                if scene is not None:
                    scene.clearSelection()

            # Also notify listeners (e.g. tables) that selection is now empty
            self.selection_changed.emit(set(), set())
            return True
        return super().eventFilter(obj, event)

    def set_selected(self, pen_ids: set[int], tank_ids: set[int]) -> None:
        """Programmatically set selection in profile + all deck views."""
        self._syncing_selection = True
        try:
            self._profile_view.set_selected_pens(pen_ids)
            self._profile_view.set_selected_tanks(tank_ids)
            for tab_widget in self._deck_tab_widgets.values():
                tab_widget._deck_view.set_selected(pen_ids, tank_ids)
        finally:
            self._syncing_selection = False

    def refresh_all_pen_tank_styles(self) -> None:
        """Force all pens and tanks to refresh their visual style (e.g. after ESC clear)."""
        for item in list(getattr(self._profile_view, "_pen_markers", {}).values()) + getattr(
            self._profile_view, "_tank_items", []
        ):
            if hasattr(item, "_update_style"):
                item._update_style()
        for tab_widget in self._deck_tab_widgets.values():
            deck_view = tab_widget._deck_view
            for item in list(getattr(deck_view, "_pen_markers", {}).values()) + getattr(
                deck_view, "_tank_polygon_items", []
            ):
                if hasattr(item, "_update_style"):
                    item._update_style()
    
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
        cog_lcg_m: float | None = None,
        cog_vcg_m: float | None = None,
    ) -> None:
        """Update waterline visualization in profile view."""
        self._profile_view.update_waterline(
            draft_mid, draft_aft, draft_fwd, ship_length, ship_depth, trim_m,
            cog_lcg_m=cog_lcg_m, cog_vcg_m=cog_vcg_m,
        )

    def clear_waterline(self) -> None:
        """Clear any existing waterline from the profile view."""
        self._profile_view.clear_waterline()

