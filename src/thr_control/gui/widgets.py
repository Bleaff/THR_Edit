"""Parameter controls. Each exposes ``param_name``, ``user_changed`` and ``apply``.

``apply`` is used for values coming from the amp: it never emits ``user_changed``
(no echo back to the device) and is ignored while the user is dragging.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDial,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import style


class Knob(QDial):
    """A rotary knob with a 270-degree value arc and a pointer."""

    def __init__(self, maximum: int = 100, size: int = 74) -> None:
        super().__init__()
        self.setRange(0, maximum)
        self.setWrapping(False)
        self.setNotchesVisible(False)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event: object) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        cx = cy = side / 2
        radius = side / 2 - 5
        span = max(self.maximum() - self.minimum(), 1)
        frac = (self.value() - self.minimum()) / span
        arc = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        track = QPen(QColor(style.TRACK), 4)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawArc(arc, 225 * 16, -270 * 16)
        if frac > 0:
            lit = QPen(QColor(style.ACCENT if self.isEnabled() else "#5a5a5a"), 4)
            lit.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(lit)
            p.drawArc(arc, 225 * 16, int(-270 * 16 * frac))

        body_r = radius - 8
        grad = QRadialGradient(QPointF(cx - body_r * 0.3, cy - body_r * 0.4), body_r * 1.6)
        grad.setColorAt(0, QColor(style.BODY_LIGHT))
        grad.setColorAt(1, QColor(style.BODY_DARK))
        p.setPen(QPen(QColor("#0c0c0e"), 1.5))
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), body_r, body_r)

        angle = math.radians(225 - 270 * frac)
        inner, outer = body_r * 0.25, body_r * 0.9
        pen = QPen(QColor("#f2f2f2" if self.isEnabled() else "#777777"), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(
            QPointF(cx + inner * math.cos(angle), cy - inner * math.sin(angle)),
            QPointF(cx + outer * math.cos(angle), cy - outer * math.sin(angle)),
        )
        p.end()


class ParamKnob(QWidget):
    user_changed = Signal(str, int)

    def __init__(self, param_name: str, label: str, maximum: int = 100) -> None:
        super().__init__()
        self.param_name = param_name
        self._silent = False
        self.knob = Knob(maximum)
        self.title = QLabel(label.upper())
        self.title.setObjectName("knobLabel")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.readout = QLabel("0")
        self.readout.setObjectName("knobValue")
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)
        layout.addWidget(self.title)
        layout.addWidget(self.knob, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.readout)
        self.knob.valueChanged.connect(self._on_value)

    def set_label(self, label: str) -> None:
        self.title.setText(label.upper())

    def _on_value(self, value: int) -> None:
        self.readout.setText(str(value))
        if not self._silent:
            self.user_changed.emit(self.param_name, value)

    def value(self) -> int:
        return self.knob.value()

    def get(self) -> int:
        return self.knob.value()

    def apply(self, value: int) -> None:
        if self.knob.isSliderDown():
            return
        self._silent = True
        self.knob.setValue(value)
        self._silent = False


class ParamSwitch(QPushButton):
    user_changed = Signal(str, int)

    def __init__(self, param_name: str) -> None:
        super().__init__("OFF")
        self.param_name = param_name
        self._silent = False
        self.setCheckable(True)
        self.setMinimumWidth(64)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.setText("ON" if checked else "OFF")
        if not self._silent:
            self.user_changed.emit(self.param_name, int(checked))

    def get(self) -> int:
        return int(self.isChecked())

    def apply(self, value: int) -> None:
        self._silent = True
        self.setChecked(bool(value))
        self._silent = False


class ParamCombo(QComboBox):
    user_changed = Signal(str, int)

    def __init__(self, param_name: str, items: list[str], tooltip: str = "") -> None:
        super().__init__()
        self.param_name = param_name
        self._silent = False
        self.addItems(items)
        if tooltip:
            self.setToolTip(tooltip)
        self.activated.connect(self._on_activated)

    def _on_activated(self, index: int) -> None:
        self.user_changed.emit(self.param_name, index)

    def get(self) -> int:
        return self.currentIndex()

    def apply(self, value: int) -> None:
        if 0 <= value < self.count():
            self.setCurrentIndex(value)


class AmpSelector(QWidget):
    """Row of exclusive buttons for the amp model."""

    user_changed = Signal(str, int)
    param_name = "amp"

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for i, name in enumerate(names):
            button = QPushButton(name.upper())
            button.setCheckable(True)
            button.setMinimumHeight(38)
            self._group.addButton(button, i)
            row.addWidget(button)
        self._group.idClicked.connect(lambda i: self.user_changed.emit(self.param_name, i))

    def get(self) -> int:
        return self._group.checkedId()

    def apply(self, value: int) -> None:
        button = self._group.button(value)
        if button is not None:
            button.setChecked(True)


class ParamTime(QDoubleSpinBox):
    """Delay time in milliseconds; the amp stores it in units of 0.1 ms."""

    user_changed = Signal(str, int)

    def __init__(self, param_name: str, minimum: int, maximum: int) -> None:
        super().__init__()
        self.param_name = param_name
        self._silent = False
        self.setDecimals(1)
        self.setRange(minimum / 10, maximum / 10)
        self.setSingleStep(10.0)
        self.setSuffix(" ms")
        self.setKeyboardTracking(False)  # send once on Enter/arrows, not per keystroke
        self.setToolTip("Delay time. TAP/TIME on the amp sets it too and this follows.")
        self.valueChanged.connect(self._on_value)

    def _on_value(self, value: float) -> None:
        if not self._silent:
            self.user_changed.emit(self.param_name, round(value * 10))

    def get(self) -> int:
        return round(self.value() * 10)

    def apply(self, value: int) -> None:
        self._silent = True
        self.setValue(value / 10)
        self._silent = False


class ParamSpin(QSpinBox):
    """Integer value in the amp's own units (used for 14-bit parameters like cut frequencies)."""

    user_changed = Signal(str, int)

    def __init__(
        self, param_name: str, minimum: int, maximum: int, suffix: str = "", tooltip: str = ""
    ) -> None:
        super().__init__()
        self.param_name = param_name
        self._silent = False
        self.setRange(minimum, maximum)
        if suffix:
            self.setSuffix(suffix)
        if tooltip:
            self.setToolTip(tooltip)
        self.setKeyboardTracking(False)  # send once on Enter/arrows, not per keystroke
        self.valueChanged.connect(self._on_value)

    def _on_value(self, value: int) -> None:
        if not self._silent:
            self.user_changed.emit(self.param_name, value)

    def get(self) -> int:
        return int(self.value())

    def apply(self, value: int) -> None:
        self._silent = True
        self.setValue(value)
        self._silent = False
