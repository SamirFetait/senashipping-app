from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTransform
from PyQt6.QtWidgets import QGraphicsView


class ShipGraphicsView(QGraphicsView):
    """
    Common zoom/pan behaviour for ship profile and deck views.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Hand-drag to pan, zoom anchored under mouse for a natural feel
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """Zoom in/out with the mouse wheel."""
        zoom_in_factor = 1.15
        zoom_out_factor = 1.0 / zoom_in_factor
        factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(factor, factor)

    def reset_zoom(self) -> None:
        """Reset the view transform to 1:1."""
        self.setTransform(QTransform())
        
    def zoom_in(self) -> None:
        """Zoom in by a fixed factor."""
        self.scale(1.2, 1.2)
        
    def zoom_out(self) -> None:
        """Zoom out by a fixed factor."""
        self.scale(1.0 / 1.2, 1.0 / 1.2)
        
    def fit_to_view(self) -> None:
        """Fit all items in the scene to the view."""
        if self.scene() and self.width() > 0 and self.height() > 0:
            self.fitInView(self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

