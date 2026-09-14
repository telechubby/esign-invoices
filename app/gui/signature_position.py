from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

# Letter (612x792 pt) is what this business's invoices actually use, but
# any page proportions are a reasonable enough stand-in for "roughly a
# page" - the point is showing where the box sits relative to the page
# edges, not reproducing the exact document.
_PAGE_W_PT = 612.0
_PAGE_H_PT = 792.0

_HANDLE_SIZE = 10.0


class SignaturePositionPicker(QWidget):
    """A mini page preview with a draggable, resizable box showing where the
    visible signature stamp will be placed on the first page. Position/size
    are tracked as percentages of the page (0-100), matching how the PDF
    box is computed at signing time."""

    changed = Signal()

    def __init__(self, x_pct: float, y_pct: float, width_pct: float, height_pct: float, parent=None):
        super().__init__(parent)
        self.x_pct = x_pct
        self.y_pct = y_pct
        self.width_pct = width_pct
        self.height_pct = height_pct
        self._drag_mode: str | None = None  # None | "move" | "resize"
        self._drag_anchor: QPointF | None = None
        self._drag_start = (0.0, 0.0, 0.0, 0.0)
        self.setMinimumSize(180, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_values(self, x_pct: float, y_pct: float, width_pct: float, height_pct: float) -> None:
        self.x_pct, self.y_pct, self.width_pct, self.height_pct = x_pct, y_pct, width_pct, height_pct
        self.update()

    # -- geometry helpers -------------------------------------------------

    def _page_rect(self) -> QRectF:
        w, h = self.width(), self.height()
        page_w = min(w - 4, (h - 4) / (_PAGE_H_PT / _PAGE_W_PT))
        page_h = page_w * (_PAGE_H_PT / _PAGE_W_PT)
        x0 = (w - page_w) / 2
        y0 = (h - page_h) / 2
        return QRectF(x0, y0, page_w, page_h)

    def _box_rect(self) -> QRectF:
        page = self._page_rect()
        bx = page.left() + self.x_pct / 100 * page.width()
        bw = self.width_pct / 100 * page.width()
        bh = self.height_pct / 100 * page.height()
        # y_pct is measured from the BOTTOM (PDF convention); screen y grows downward.
        by = page.bottom() - (self.y_pct / 100 * page.height()) - bh
        return QRectF(bx, by, bw, bh)

    def _box_to_pct(self, box: QRectF) -> None:
        page = self._page_rect()
        x_pct = (box.left() - page.left()) / page.width() * 100
        width_pct = box.width() / page.width() * 100
        height_pct = box.height() / page.height() * 100
        y_pct = (page.bottom() - box.bottom()) / page.height() * 100

        width_pct = max(2.0, min(100.0, width_pct))
        height_pct = max(2.0, min(100.0, height_pct))
        x_pct = max(0.0, min(100.0 - width_pct, x_pct))
        y_pct = max(0.0, min(100.0 - height_pct, y_pct))

        self.x_pct, self.y_pct, self.width_pct, self.height_pct = x_pct, y_pct, width_pct, height_pct

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        page = self._page_rect()
        painter.fillRect(page, QColor("#ffffff"))
        painter.setPen(QColor("#999999"))
        painter.drawRect(page)

        box = self._box_rect()
        painter.setBrush(QColor(255, 193, 7, 130))
        painter.setPen(QColor("#b8860b"))
        painter.drawRect(box)

        handle = QRectF(box.right() - _HANDLE_SIZE / 2, box.bottom() - _HANDLE_SIZE / 2, _HANDLE_SIZE, _HANDLE_SIZE)
        painter.setBrush(QColor("#b8860b"))
        painter.drawRect(handle)
        painter.end()

    # -- interaction ----------------------------------------------------

    def _resize_handle_rect(self) -> QRectF:
        box = self._box_rect()
        return QRectF(box.right() - _HANDLE_SIZE, box.bottom() - _HANDLE_SIZE, _HANDLE_SIZE * 1.5, _HANDLE_SIZE * 1.5)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        box = self._box_rect()
        self._drag_start = (self.x_pct, self.y_pct, self.width_pct, self.height_pct)
        if self._resize_handle_rect().contains(pos):
            self._drag_mode = "resize"
            self._drag_anchor = pos
        elif box.contains(pos):
            self._drag_mode = "move"
            self._drag_anchor = pos - box.topLeft()
        else:
            self._drag_mode = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode is None:
            return
        pos = event.position()
        page = self._page_rect()

        if self._drag_mode == "move":
            new_top_left = pos - self._drag_anchor
            box = self._box_rect()
            box.moveTopLeft(new_top_left)
            self._box_to_pct(box)
        elif self._drag_mode == "resize":
            box = self._box_rect()
            new_right = max(box.left() + 10, min(page.right(), pos.x()))
            new_bottom = max(box.top() + 10, min(page.bottom(), pos.y()))
            box.setRight(new_right)
            box.setBottom(new_bottom)
            self._box_to_pct(box)

        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_mode = None
        self._drag_anchor = None
