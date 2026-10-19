"""Frequency-response plot for the bass/middle/treble knobs and the live measurement.

Shows the illustrative model (dashed, always) and, when the live meter runs, the measured curve
(blue, only where it is trusted). The vertical range adapts to the data, curves are smoothed,
and hovering shows the frequency and level under the cursor.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..domain.eq import log_frequencies, response_db
from . import style

F_LOW, F_HIGH = 20.0, 20000.0
RANGE_STEPS = (6.0, 9.0, 12.0, 18.0, 24.0, 36.0)  # vertical half-range in dB
CAPTION = "Illustrative curve: the amp's real filter frequencies are not known."
MEASURED = QColor("#6ec1ff")
FREQ_TICKS = (
    (20, "20"),
    (50, "50"),
    (100, "100"),
    (200, "200"),
    (500, "500"),
    (1000, "1k"),
    (2000, "2k"),
    (5000, "5k"),
    (10000, "10k"),
    (20000, "20k"),
)


def pick_range(needed: float, current: float) -> float:
    """Half-range to show: grow at once when *needed* exceeds it, shrink only when well below.

    The hysteresis stops the scale flickering between steps as live data fluctuates.
    """
    fit = next((s for s in RANGE_STEPS if s >= needed), RANGE_STEPS[-1])
    if fit > current:
        return fit
    if needed < current * 0.55:
        return fit
    return current


def smooth_points(points: list[QPointF]) -> QPainterPath:
    """A smooth path through *points* (Catmull-Rom converted to cubic Beziers)."""
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0])
    for i in range(len(points) - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6, p1.y() + (p2.y() - p0.y()) / 6)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6, p2.y() - (p3.y() - p1.y()) / 6)
        path.cubicTo(c1, c2, p2)
    return path


class EqCurve(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setToolTip(CAPTION)
        self._values = (50, 50, 50)
        self._freqs = log_frequencies(160, F_LOW, F_HIGH)
        self._curve = response_db(self._freqs, *self._values)
        self._measured: tuple[list[float], list[float], list[bool]] | None = None
        self._coherence: list[float] | None = None
        self._range = RANGE_STEPS[2]
        self._hover: QPointF | None = None

    # -- data ----------------------------------------------------------------
    def values(self) -> tuple[int, int, int]:
        return self._values

    def curve(self) -> list[float]:
        return list(self._curve)

    def measured(self) -> tuple[list[float], list[float], list[bool]] | None:
        return self._measured

    def half_range(self) -> float:
        return self._range

    def set_values(self, bass: int, middle: int, treble: int) -> None:
        values = (bass, middle, treble)
        if values != self._values:
            self._values = values
            self._curve = response_db(self._freqs, *values)
            self._refit()
            self.update()

    def set_measured(
        self,
        freqs: list[float],
        db: list[float],
        valid: list[bool],
        coherence: list[float] | None = None,
    ) -> None:
        """Overlay a live measurement; only the *valid* points are drawn."""
        self._measured = (freqs, db, valid)
        self._coherence = coherence
        self._refit()
        self.update()

    def clear_measured(self) -> None:
        if self._measured is not None:
            self._measured = None
            self._coherence = None
            self._refit()
            self.update()

    def _refit(self) -> None:
        needed = max((abs(v) for v in self._curve), default=0.0)
        if self._measured is not None:
            _, db, valid = self._measured
            needed = max([needed, *(abs(v) for v, ok in zip(db, valid, strict=True) if ok)])
        self._range = pick_range(needed * 1.1, self._range)

    # -- geometry (kept separate from painting so it can be tested) -------------
    def plot_rect(self) -> QRectF:
        return QRectF(40, 10, max(self.width() - 52, 10), max(self.height() - 52, 10))

    def x_for(self, freq: float, rect: QRectF) -> float:
        return rect.left() + rect.width() * math.log(freq / F_LOW) / math.log(F_HIGH / F_LOW)

    def y_for(self, db: float, rect: QRectF) -> float:
        db = max(-self._range, min(self._range, db))
        return rect.center().y() - rect.height() / 2 * db / self._range

    def freq_at(self, x: float, rect: QRectF) -> float:
        frac = min(max((x - rect.left()) / rect.width(), 0.0), 1.0)
        return float(F_LOW * (F_HIGH / F_LOW) ** frac)

    def db_at(self, y: float, rect: QRectF) -> float:
        return (rect.center().y() - y) / (rect.height() / 2) * self._range

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        self._hover = pos if self.plot_rect().contains(pos) else None
        self.update()

    def leaveEvent(self, event: object) -> None:  # noqa: N802
        self._hover = None
        self.update()

    # -- painting ----------------------------------------------------------------
    def _line(self, p: QPainter, xs: list[float], ys: list[float], pen: QPen) -> QPainterPath:
        path = smooth_points([QPointF(x, y) for x, y in zip(xs, ys, strict=True)])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        return path

    def paintEvent(self, event: object) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.plot_rect()
        bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        bg.setColorAt(0, QColor("#1b1d22"))
        bg.setColorAt(1, QColor("#121316"))
        p.fillRect(rect, bg)
        small = p.font()
        small.setPointSize(8)
        p.setFont(small)

        step = self._range / 3
        db = -self._range
        while db <= self._range + 1e-6:  # horizontal grid and labels
            y = self.y_for(db, rect)
            zero = abs(db) < 1e-6
            p.setPen(QPen(QColor("#6a6d76"), 1.5) if zero else QPen(QColor(style.TRACK), 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(QColor("#9a9a9a"))
            label = "0 dB" if zero else f"{db:+.0f}"
            p.drawText(QRectF(0, y - 7, 36, 14), Qt.AlignmentFlag.AlignRight, label)
            db += step
        for freq, label in FREQ_TICKS:  # vertical grid and labels
            x = self.x_for(freq, rect)
            strong = freq in (100, 1000, 10000)
            p.setPen(QPen(QColor("#3f424a" if strong else "#2a2c31"), 1))
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            if freq in (20, 20000):
                continue
            p.setPen(QColor("#9a9a9a"))
            p.drawText(
                QRectF(x - 20, rect.bottom() + 3, 40, 14), Qt.AlignmentFlag.AlignCenter, label
            )

        xs = [self.x_for(f, rect) for f in self._freqs]
        model_color = QColor(style.ACCENT if self.isEnabled() else "#6a6a6a")
        ys = [self.y_for(v, rect) for v in self._curve]
        if self._measured is None:
            fill = QPainterPath(smooth_points([QPointF(x, y) for x, y in zip(xs, ys, strict=True)]))
            zero_y = self.y_for(0, rect)
            fill.lineTo(QPointF(rect.right(), zero_y))
            fill.lineTo(QPointF(rect.left(), zero_y))
            fill.closeSubpath()
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            top = QColor(model_color)
            top.setAlpha(90)
            bottom = QColor(model_color)
            bottom.setAlpha(8)
            grad.setColorAt(0, top)
            grad.setColorAt(1, bottom)
            p.fillPath(fill, grad)
            glow = QPen(QColor(model_color.red(), model_color.green(), model_color.blue(), 60), 7)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            self._line(p, xs, ys, glow)
            line = QPen(model_color, 2.6)
            line.setCapStyle(Qt.PenCapStyle.RoundCap)
            self._line(p, xs, ys, line)
        else:
            self._line(p, xs, ys, QPen(QColor("#8a7648"), 1.8, Qt.PenStyle.DashLine))
            self._paint_measured(p, rect)

        self._paint_legend(p, rect)
        self._paint_hover(p, rect)
        p.end()

    def _paint_measured(self, p: QPainter, rect: QRectF) -> None:
        assert self._measured is not None
        freqs, db, valid = self._measured
        runs: list[list[QPointF]] = []
        current: list[QPointF] = []
        for f, level, ok in zip(freqs, db, valid, strict=True):
            if ok:
                current.append(QPointF(self.x_for(f, rect), self.y_for(level, rect)))
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
        zero_y = self.y_for(0, rect)
        for run in runs:
            if len(run) < 2:
                continue
            path = smooth_points(run)
            fill = QPainterPath(path)
            fill.lineTo(QPointF(run[-1].x(), zero_y))
            fill.lineTo(QPointF(run[0].x(), zero_y))
            fill.closeSubpath()
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            top, bottom = QColor(MEASURED), QColor(MEASURED)
            top.setAlpha(95)
            bottom.setAlpha(8)
            grad.setColorAt(0, top)
            grad.setColorAt(1, bottom)
            p.fillPath(fill, grad)
            glow = QPen(QColor(110, 193, 255, 70), 8)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(glow)
            p.drawPath(path)
            line = QPen(MEASURED, 3.0)
            line.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(line)
            p.drawPath(path)
        if self._coherence is not None:  # a thin trust strip along the bottom edge
            for i in range(len(freqs) - 1):
                c = self._coherence[i]
                shade = QColor(110, 193, 255, int(40 + 180 * min(max(c, 0.0), 1.0)))
                x0, x1 = self.x_for(freqs[i], rect), self.x_for(freqs[i + 1], rect)
                p.fillRect(QRectF(x0, rect.bottom() - 5, x1 - x0 + 1, 5), shade)

    def _paint_legend(self, p: QPainter, rect: QRectF) -> None:
        items = [("model (illustrative)", QColor(style.ACCENT), Qt.PenStyle.SolidLine)]
        if self._measured is not None:
            items = [
                ("model", QColor("#8a7648"), Qt.PenStyle.DashLine),
                ("measured live", MEASURED, Qt.PenStyle.SolidLine),
            ]
        x = rect.right() - 8
        for text, color, style_ in reversed(items):
            width = p.fontMetrics().horizontalAdvance(text)
            p.setPen(QColor("#b8b8b8"))
            p.drawText(QPointF(x - width, rect.top() + 14), text)
            p.setPen(QPen(color, 2.4, style_))
            p.drawLine(
                QPointF(x - width - 26, rect.top() + 10), QPointF(x - width - 6, rect.top() + 10)
            )
            x -= width + 36

    def _paint_hover(self, p: QPainter, rect: QRectF) -> None:
        if self._hover is None:
            return
        freq = self.freq_at(self._hover.x(), rect)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DotLine))
        p.drawLine(QPointF(self._hover.x(), rect.top()), QPointF(self._hover.x(), rect.bottom()))
        shown = f"{freq / 1000:.2f} kHz" if freq >= 1000 else f"{freq:.0f} Hz"
        k = min(range(len(self._freqs)), key=lambda i: abs(self._freqs[i] - freq))
        shown += f"   model {self._curve[k]:+.1f} dB"
        if self._measured is not None:
            mf, mdb, mvalid = self._measured
            j = min(range(len(mf)), key=lambda i: abs(mf[i] - freq))
            shown += (
                f"   measured {mdb[j]:+.1f} dB" if mvalid[j] else "   measured: not trusted here"
            )
        width = p.fontMetrics().horizontalAdvance(shown) + 14
        x = min(self._hover.x() + 10, rect.right() - width)
        box = QRectF(x, max(self._hover.y() - 26, rect.top() + 18), width, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 21, 24, 230))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("#e6e6e6"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, shown)
