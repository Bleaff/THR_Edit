from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from ..protocol.thr_v2 import MODULATION_LABELS, PARAMETERS
from .widgets import ParamCombo, ParamKnob, ParamSwitch, ParamTime

ASSUMED = "Type names follow the THR10 order; unverified on THR5"


class _EffectBox(QGroupBox):
    def __init__(self, title: str, switch_name: str) -> None:
        super().__init__(title)
        self.switch = ParamSwitch(switch_name)
        self.row = QHBoxLayout()
        self.row.addWidget(self.switch)
        self.body = QHBoxLayout()
        layout = QVBoxLayout(self)
        layout.addLayout(self.row)
        layout.addLayout(self.body)


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
        self.mod_type.activated.connect(lambda _i: self.update_modulation_layout())

        delay = _EffectBox("DELAY", "delay")
        self.delay_feedback = ParamKnob("delay_feedback", "Feedback")
        self.delay_level = ParamKnob("delay_level", "Level")
        dt = PARAMETERS["delay_time"]
        self.delay_time = ParamTime("delay_time", dt.minimum, dt.maximum)
        time_label = QLabel("TIME")
        time_label.setObjectName("knobLabel")
        delay.row.addWidget(time_label)
        delay.row.addWidget(self.delay_time)
        delay.body.addWidget(self.delay_feedback)
        delay.body.addWidget(self.delay_level)

        reverb = _EffectBox("REVERB", "reverb")
        self.reverb_type = ParamCombo("reverb_type", ["Hall", "Room", "Plate", "Spring"], ASSUMED)
        reverb.row.addWidget(self.reverb_type, 1)
        self.reverb_level = ParamKnob("reverb_level", "Level")
        reverb.body.addWidget(self.reverb_level)

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

    def update_modulation_layout(self) -> None:
        """Label and show only the parameter knobs the current modulation type uses."""
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
            self.reverb_type,
            self.reverb_level,
            self.gate_threshold,
            self.gate_release,
            self.comp_sustain,
            self.comp_output,
        ]
