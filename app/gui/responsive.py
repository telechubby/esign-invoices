from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QScrollArea, QWidget


def screen_fit_size(preferred_w: int, preferred_h: int, margin: int = 80) -> tuple[int, int]:
    """Clamps a preferred window/dialog size to comfortably fit the
    available screen, so it never opens larger than the screen (which is
    what pushes buttons/fields off-screen on small displays)."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return preferred_w, preferred_h
    avail = screen.availableGeometry()
    return min(preferred_w, avail.width() - margin), min(preferred_h, avail.height() - margin)


def make_scrollable(content: QWidget) -> QScrollArea:
    """Wraps `content` in a vertically-scrolling area so a tab/dialog with
    many sections degrades to a scrollbar instead of growing past the
    screen edge. The returned QScrollArea is itself a QWidget - add it
    directly to a layout in place of `content`."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll
