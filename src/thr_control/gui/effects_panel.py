from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..protocol.thr_v2 import MODULATION_LABELS, PARAMETERS
from .widgets import ParamCombo, ParamKnob, ParamSpin, ParamSwitch, ParamTime

ASSUMED = "Type names follow the THR10 order; unverified on THR5"


def _table_spin(name: str, suffix: str = "", tooltip: str = "") -> ParamSpin:
    p = PARAMETERS[name]
    return ParamSpin(name, p.minimum, p.maximum, suffix, tooltip or p.note)


def _labelled(text: str, widget: QWidget) -> QWidget:
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    label = QLabel(text)
    label.setObjectName("knobLabel")
    row.addWidget(label)
    row.addWidget(widget, 1)
    return box


class _EffectBox(QGroupBox):
    def __init__(self, title: str, switch_name: str) -> None:
        super().__init__(title)
        self.switch = ParamSwitch(switch_name)
        self.row = QHBoxLayout()
        self.row.addWidget(self.switch)
        self.body = QHBoxLayout()
        self.extra = QVBoxLayout()
        layout = QVBoxLayout(self)
        layout.addLayout(self.row)
        layout.addLayout(self.body)
        layout.addLayout(self.extra)
        layout.addStretch(1)  # keep contents compact when a neighbour box is taller


class EffectsPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("EFFECTS")
        modulation = _EffectBox("MODULATION", "modulation")
        self.mod_type = ParamCombo(
            "modulation_type", ["Chorus", "Flanger", "Tremolo", "Phaser"], ASSUMED
        )
        modulation.row.addWidget(self.mod_type, 1)
        self.mod_knobs = [ParamKnob(f"modulation_p{i}", f"P{i}") for i in range(1, 6)]
        for knob in self.mod_knobs:
            modulation.body.addWidget(knob)
        self.mod_type.activated.connect(lambda _i: self.update_layouts())

        delay = _EffectBox("DELAY", "delay")
        self.delay_feedback = ParamKnob("delay_feedback", "Feedback")
        self.delay_level = ParamKnob("delay_level", "Level")
        dt = PARAMETERS["delay_time"]
        self.delay_time = ParamTime("delay_time", dt.minimum, dt.maximum)
        time_label = QLabel("TIME")
        time_label.setObjectName("knobLabel")
        delay.row.addWidget(time_label)
        delay.row.addWidget(self.delay_time)
        self.delay_high_cut = _table_spin("delay_high_cut", " Hz")
        self.delay_low_cut = _table_spin("delay_low_cut", " Hz")
        delay.extra.addWidget(_labelled("HIGH CUT", self.delay_high_cut))
        delay.extra.addWidget(_labelled("LOW CUT", self.delay_low_cut))
        delay.body.addWidget(self.delay_feedback)
        delay.body.addWidget(self.delay_level)

        reverb = _EffectBox("REVERB", "reverb")
        self.reverb_type = ParamCombo("reverb_type", ["Hall", "Room", "Plate", "Spring"], ASSUMED)
        reverb.row.addWidget(self.reverb_type, 1)
        self.reverb_level = ParamKnob("reverb_level", "Level")
        reverb.body.addWidget(self.reverb_level)

        # Hall / room / plate: 14-bit values plus two ratios. Spring: reverb amount and filter.
        self.reverb_time = _table_spin("reverb_time")
        self.reverb_pre = _table_spin("reverb_pre")
        self.reverb_low_cut = _table_spin("reverb_low_cut", " Hz")
        self.reverb_high_cut = _table_spin("reverb_high_cut", " Hz")
        self.reverb_high_ratio = ParamKnob("reverb_high_ratio", "High ratio", 10)
        self.reverb_low_ratio = ParamKnob("reverb_low_ratio", "Low ratio", 14)
        self._reverb_full = QWidget()
        full = QVBoxLayout(self._reverb_full)
        full.setContentsMargins(0, 0, 0, 0)
        full.addWidget(_labelled("TIME", self.reverb_time))
        full.addWidget(_labelled("PRE-DELAY", self.reverb_pre))
        full.addWidget(_labelled("LOW CUT", self.reverb_low_cut))
        full.addWidget(_labelled("HIGH CUT", self.reverb_high_cut))
        ratios = QHBoxLayout()
        ratios.addWidget(self.reverb_high_ratio)
        ratios.addWidget(self.reverb_low_ratio)
        full.addLayout(ratios)
        self.spring_reverb = ParamKnob("reverb_spring_reverb", "Spring reverb")
        self.spring_filter = ParamKnob("reverb_spring_filter", "Spring filter")
        self._reverb_spring = QWidget()
        spring = QHBoxLayout(self._reverb_spring)
        spring.setContentsMargins(0, 0, 0, 0)
        spring.addWidget(self.spring_reverb)
        spring.addWidget(self.spring_filter)
        reverb.extra.addWidget(self._reverb_full)
        reverb.extra.addWidget(self._reverb_spring)
        self.reverb_type.activated.connect(lambda _i: self.update_layouts())

        gate = _EffectBox("NOISE GATE", "gate")
        self.gate_threshold = ParamKnob("gate_threshold", "Threshold")
        self.gate_release = ParamKnob("gate_release", "Release")
        gate.body.addWidget(self.gate_threshold)
        gate.body.addWidget(self.gate_release)

        compressor = _EffectBox("COMPRESSOR", "compressor")
        self.comp_sustain = ParamKnob("compressor_sustain", "Sustain")
        self.comp_output = ParamKnob("compressor_output", "Output")
        compressor.body.addWidget(self.comp_sustain)
        compressor.body.addWidget(self.comp_output)
        compressor.setToolTip(
            "Software-only: the THR5A has no compressor knob. Sustain/output apply to the "
            "stomp-type compressor."
        )

        grid = QGridLayout(self)
        grid.addWidget(modulation, 0, 0)
        grid.addWidget(delay, 0, 1)
        grid.addWidget(reverb, 1, 0)
        grid.addWidget(gate, 1, 1)
        grid.addWidget(compressor, 2, 0)
        self._boxes = (modulation, delay, reverb, gate, compressor)

    def update_layouts(self) -> None:
        """Show only the controls that apply to the current modulation and reverb types."""
        self._update_modulation()
        spring = self.reverb_type.get() == 3
        self._reverb_spring.setVisible(spring)
        self._reverb_full.setVisible(not spring)

    def _update_modulation(self) -> None:
        labels = MODULATION_LABELS.get(self.mod_type.get(), ())
        for i, knob in enumerate(self.mod_knobs):
            knob.setVisible(i < len(labels))
            if i < len(labels):
                knob.set_label(labels[i])

    def controls(self) -> list[Any]:
        return [
            *(box.switch for box in self._boxes),
            self.mod_type,
            *self.mod_knobs,
            self.delay_time,
            self.delay_feedback,
            self.delay_level,
            self.delay_high_cut,
            self.delay_low_cut,
            self.reverb_type,
            self.reverb_level,
            self.reverb_time,
            self.reverb_pre,
            self.reverb_low_cut,
            self.reverb_high_cut,
            self.reverb_high_ratio,
            self.reverb_low_ratio,
            self.spring_reverb,
            self.spring_filter,
            self.gate_threshold,
            self.gate_release,
            self.comp_sustain,
            self.comp_output,
        ]
