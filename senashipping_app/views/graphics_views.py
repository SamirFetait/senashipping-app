from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QTransform
from PyQt6.QtWidgets import QGraphicsView


class ShipGraphicsView(QGraphicsView):
    """
    Base for ship profile and deck views. Provides zoom utilities.
    Subclasses set their own drag mode (e.g. RubberBandDrag for pen selection).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Receive key events (ESC to deselect)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """ESC clears selection - must handle before scene gets it (scene might select on ESC)."""
        if event.key() == Qt.Key.Key_Escape and self.scene():
            self.scene().clearSelection()
            event.accept()
            return
        super().keyPressEvent(event)

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
