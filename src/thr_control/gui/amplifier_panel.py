from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from ..protocol.thr_v2 import AMP_NAMES, CAB_NAMES
from .eq_curve import CAPTION, EqCurve
from .widgets import AmpSelector, ParamCombo, ParamKnob


class AmplifierPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("AMPLIFIER")
        self.selector = AmpSelector([n for n in AMP_NAMES])
        self.selector.setToolTip(
            "Amp model names follow the THR10 order and are unverified on THR5"
        )
        self.cab = ParamCombo(
            "cab",
            [n.upper() for n in CAB_NAMES],
            "Speaker cabinet. Names follow the THR10 order and are unverified on THR5. "
            "The amp picks its own cab when you change the amp model.",
        )
        cab_label = QLabel("CABINET")
        cab_label.setObjectName("knobLabel")
        cab_row = QHBoxLayout()
        cab_row.addWidget(cab_label)
        cab_row.addWidget(self.cab, 1)
        self.knobs = [
            ParamKnob("gain", "Gain"),
            ParamKnob("master", "Master"),
            ParamKnob("bass", "Bass"),
            ParamKnob("middle", "Middle"),
            ParamKnob("treble", "Treble"),
        ]
        row = QHBoxLayout()
        for knob in self.knobs:
            row.addWidget(knob)
        note = QLabel(
            "Output volume is an analog knob on the amp and cannot be read or set over MIDI."
        )
        note.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.selector)
        layout.addLayout(cab_row)
        layout.addLayout(row)
        self.eq_curve = EqCurve()
        eq_note = QLabel(CAPTION)
        eq_note.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        layout.addWidget(self.eq_curve)
        layout.addWidget(eq_note)
        layout.addWidget(note)

    def update_eq_curve(self) -> None:
        """Redraw the curve from the bass / middle / treble knobs."""
        by_name = {k.param_name: k for k in self.knobs}
        self.eq_curve.set_values(
            by_name["bass"].get(), by_name["middle"].get(), by_name["treble"].get()
        )

    def controls(self) -> list[Any]:
        return [self.selector, self.cab, *self.knobs]
