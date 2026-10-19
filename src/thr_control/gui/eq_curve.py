"""Small frequency-response plot for the bass/middle/treble knobs (illustrative only)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..domain.eq import log_frequencies, response_db
from . import style

DB_RANGE = 15.0
F_LOW, F_HIGH = 20.0, 20000.0
CAPTION = "Illustrative curve: the amp's real filter frequencies are not known."


class EqCurve(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.setToolTip(CAPTION)
        self._values = (50, 50, 50)
        self._freqs = log_frequencies(120, F_LOW, F_HIGH)
        self._curve = response_db(self._freqs, *self._values)

    def values(self) -> tuple[int, int, int]:
        return self._values

    def curve(self) -> list[float]:
        return list(self._curve)

    def set_values(self, bass: int, middle: int, treble: int) -> None:
        values = (bass, middle, treble)
        if values != self._values:
            self._values = values
            self._curve = response_db(self._freqs, *values)
            self.update()

    def _x(self, freq: float, rect: QRectF) -> float:
        span = math.log(F_HIGH / F_LOW)
        return rect.left() + rect.width() * math.log(freq / F_LOW) / span

    def _y(self, db: float, rect: QRectF) -> float:
        db = max(-DB_RANGE, min(DB_RANGE, db))
        return rect.center().y() - rect.height() / 2 * db / DB_RANGE

    def paintEvent(self, event: object) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = QRectF(34, 8, self.width() - 44, self.height() - 30)
        p.fillRect(plot, QColor("#17181b"))

        grid = QPen(QColor(style.TRACK), 1)
        small = p.font()
        small.setPointSize(8)
        p.setFont(small)
        for db in (-12, -6, 0, 6, 12):
            y = self._y(db, plot)
            p.setPen(QPen(QColor("#5a5d66"), 1.4) if db == 0 else grid)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor("#8a8a8a"))
            p.drawText(
                QRectF(0, y - 7, 30, 14), Qt.AlignmentFlag.AlignRight, f"{db:+d}" if db else "0"
            )
        for freq, label in ((100, "100"), (1000, "1k"), (10000, "10k")):
            x = self._x(freq, plot)
            p.setPen(grid)
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(QColor("#8a8a8a"))
            p.drawText(
                QRectF(x - 20, plot.bottom() + 2, 40, 14), Qt.AlignmentFlag.AlignCenter, label
            )

        path = QPainterPath()
        for i, (f, level) in enumerate(zip(self._freqs, self._curve, strict=True)):
            pt = QPointF(self._x(f, plot), self._y(level, plot))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(QPointF(plot.right(), self._y(0, plot)))
        fill.lineTo(QPointF(plot.left(), self._y(0, plot)))
        fill.closeSubpath()
        color = QColor(style.ACCENT if self.isEnabled() else "#6a6a6a")
        fill_color = QColor(color)
        fill_color.setAlpha(45)
        p.fillPath(fill, fill_color)
        pen = QPen(color, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPath(path)
        p.end()
