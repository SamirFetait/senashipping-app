from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPen, QBrush
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QComboBox,
    QLabel,
    QGraphicsScene,
)

from .graphics_views import ShipGraphicsView


BASE_DIR = Path(__file__).resolve().parent.parent  # -> cargomax_app
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
    Top profile view.

    First version shows a simple placeholder hull; later we will replace this
    with real rendering of CAD_DIR / 'profile.dxf'.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._load_profile()

    def _load_profile(self) -> None:
        self._scene.clear()
        dxf_path = CAD_DIR / "profile.dxf"
        if not _load_dxf_into_scene(dxf_path, self._scene):
            # Fallback placeholder if DXF missing or ezdxf not installed
            self._scene.addLine(0, 0, 800, 0, QPen(Qt.GlobalColor.blue, 2))
            self._scene.addRect(QRectF(50, -40, 700, 80), QPen(Qt.GlobalColor.darkBlue))
        if self._scene.items():
            self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)


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


class DeckProfileWidget(QWidget):
    """
    Composite widget:
      - top: ship profile view
      - bottom: active deck plan with deck selector.
    """

    # Emitted whenever the active deck changes, e.g. "A", "B", "C"
    deck_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        splitter = QSplitter(Qt.Orientation.Vertical, self)

        # Top: profile
        self._profile_view = ProfileView(self)
        splitter.addWidget(self._profile_view)

        # Bottom: deck selector + view
        bottom = QWidget(self)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Deck:", self))

        self._deck_combo = QComboBox(self)
        # Decks A–H based on existing DXF files deck_A.dxf ... deck_H.dxf
        self._deck_combo.addItems(["A", "B", "C", "D", "E", "F", "G", "H"])
        selector_row.addWidget(self._deck_combo)
        selector_row.addStretch()

        bottom_layout.addLayout(selector_row)

        self._deck_view = DeckView(self)
        bottom_layout.addWidget(self._deck_view)

        splitter.addWidget(bottom)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter)

        # Wire deck selector
        self._deck_combo.currentTextChanged.connect(self._on_deck_changed)

        # Initial deck
        self._on_deck_changed(self._deck_combo.currentText())

    def _on_deck_changed(self, deck_name: str) -> None:
        self._deck_view.load_deck(deck_name)
        self.deck_changed.emit(deck_name)

