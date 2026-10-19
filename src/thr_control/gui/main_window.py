from __future__ import annotations

import contextlib
from typing import Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..domain.presets import Preset, apply_order
from ..midi.discovery import list_input_ports, list_output_ports
from ..services.preset_manager import PresetError, PresetManager
from .amplifier_panel import AmplifierPanel
from .bridge import SessionBridge
from .diagnostics_view import DiagnosticsView
from .effects_panel import EffectsPanel
from .preset_browser import PresetBrowser, Prompts

AUTO = "Auto-detect"


class MainWindow(QMainWindow):
    def __init__(
        self,
        bridge: SessionBridge,
        manager: PresetManager,
        prompts: Prompts | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("THR Control")
        self.resize(1200, 760)
        self.bridge = bridge
        self.manager = manager
        self.active: Preset | None = None
        self._have_state = False
        self.browser = PresetBrowser(manager, prompts)

        self.amp_panel = AmplifierPanel()
        self.effects_panel = EffectsPanel()
        self.diagnostics = DiagnosticsView(list_input_ports, list_output_ports)

        self.controls: dict[str, Any] = {}
        for control in [*self.amp_panel.controls(), *self.effects_panel.controls()]:
            self.controls[control.param_name] = control
            control.user_changed.connect(self._on_user_changed)

        # top bar
        self.device_label = QLabel("No device")
        self.status_label = QLabel("● Disconnected")
        self.status_label.setObjectName("status")
        self.busy_label = QLabel("♪ AMP BUSY")
        self.busy_label.setObjectName("busy")
        self.busy_label.setToolTip(
            "The amp stopped sending its heartbeat but is still connected. This is what happens "
            "while its tuner is on. Changes are paused until it comes back."
        )
        self.busy_label.hide()
        self.port_combo = QComboBox()
        self.port_combo.setToolTip("Choose the MIDI port manually, or let the app detect a THR")
        self.port_combo.activated.connect(self._on_port_chosen)
        self.preset_label = QLabel("Preset: —")
        self.save_button = QPushButton("Save")
        self.save_button.setEnabled(False)
        self.save_button.setToolTip(
            "Save the amp's current settings into the active preset (or as a new preset)"
        )
        self.save_button.clicked.connect(self.save_active)
        top = QHBoxLayout()
        top.addWidget(self.device_label)
        top.addWidget(self.status_label)
        top.addWidget(self.busy_label)
        top.addWidget(self.port_combo)
        top.addStretch(1)
        top.addWidget(self.preset_label)
        top.addWidget(self.save_button)

        main_page = QWidget()
        mv = QVBoxLayout(main_page)
        mv.addWidget(self.amp_panel)
        mv.addWidget(self.effects_panel)
        mv.addStretch(1)
        tabs = QTabWidget()
        tabs.addTab(main_page, "Amp && Effects")
        tabs.addTab(self.diagnostics, "Diagnostics")

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(top)
        rv.addWidget(tabs, 1)
        split = QSplitter()
        split.addWidget(self.browser)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 920])
        self.setCentralWidget(split)

        self.browser.load_requested.connect(self.load_preset)
        self.browser.save_as_requested.connect(self.save_as)
        self.browser.library_changed.connect(self._library_changed)
        self.browser.message.connect(self.diagnostics.add_log)
        for control in self.controls.values():
            control.user_changed.connect(lambda *_: self._update_preset_label())

        bridge.status.connect(self._on_status)
        bridge.settings.connect(self._on_settings)
        bridge.param.connect(self._on_param)
        bridge.busy.connect(self.busy_label.setVisible)
        bridge.raw.connect(self.diagnostics.add_raw)
        bridge.log.connect(self.diagnostics.add_log)

        self._fill_ports()
        self.set_connected(False)

    # -- connection state --------------------------------------------------
    def set_connected(self, connected: bool) -> None:
        for control in self.controls.values():
            control.setEnabled(connected)
        if not connected:
            self._have_state = False
            self.busy_label.hide()
        self.browser.set_connected(connected)
        self._update_preset_label()

    def _on_status(self, state: str, detail: str) -> None:
        connected = state == "connected"
        self.set_connected(connected)
        if connected:
            self.device_label.setText(detail)
            self.status_label.setText("● Connected")
            self.status_label.setStyleSheet("color: #5ec26a;")
        else:
            self.device_label.setText("No device")
            self.status_label.setText("● Disconnected")
            self.status_label.setStyleSheet("color: #d9534f;")
            self.status_label.setToolTip(detail)
        self.diagnostics.add_history(state, detail)

    # -- device -> UI ------------------------------------------------------
    def _on_settings(self, settings: dict[str, int]) -> None:
        for name, value in settings.items():
            control = self.controls.get(name)
            if control is not None:
                control.apply(value)
        self._have_state = True
        self.effects_panel.update_modulation_layout()
        self._update_preset_label()

    def _on_param(self, name: str, value: int) -> None:
        control = self.controls.get(name)
        if control is not None:
            control.apply(value)
        self.effects_panel.update_modulation_layout()
        self._update_preset_label()

    # -- presets -----------------------------------------------------------
    def current_settings(self) -> dict[str, int]:
        return {name: control.get() for name, control in self.controls.items()}

    def is_modified(self) -> bool:
        if self.active is None or not self._have_state:
            return False
        current = self.current_settings()
        return any(current.get(k) != v for k, v in self.active.settings.items())

    def _update_preset_label(self) -> None:
        if self.active is None:
            self.preset_label.setText("Preset: —")
        else:
            mark = " *" if self.is_modified() else ""
            self.preset_label.setText(f"Preset: {self.active.name}{mark}")
        self.save_button.setEnabled(self._have_state)

    def load_preset(self, preset: Preset) -> None:
        """Apply a preset: show it immediately and send it to the amp (amp model first)."""
        self.active = preset
        for name, value in apply_order(preset.settings):
            control = self.controls.get(name)
            if control is not None:
                control.apply(value)
            self._on_user_changed(name, value)
        self.effects_panel.update_modulation_layout()
        self._update_preset_label()
        self.diagnostics.add_log(f"loaded preset {preset.name!r}")

    def save_active(self) -> None:
        if not self._have_state:
            return
        if self.active is None:
            self.save_as()
            return
        try:
            self.active = self.manager.update_settings(self.active.id, self.current_settings())
        except PresetError as exc:
            self.browser.prompts.show_error(self, str(exc))
            return
        self.browser.refresh(self.active.id)
        self._update_preset_label()
        self.diagnostics.add_log(f"saved preset {self.active.name!r}")

    def save_as(self) -> None:
        if not self._have_state:
            return
        default = self.active.name if self.active else "New preset"
        name = self.browser.prompts.ask_text(self, "Save preset", "Name:", default)
        if name is None:
            return
        try:
            self.active = self.manager.create(name, self.current_settings())
        except PresetError as exc:
            self.browser.prompts.show_error(self, str(exc))
            return
        self.browser.refresh(self.active.id)
        self._update_preset_label()
        self.diagnostics.add_log(f"saved new preset {self.active.name!r}")

    def _library_changed(self) -> None:
        if self.active is not None:
            self.active = self.manager.get(self.active.id)
        self._update_preset_label()

    # -- UI -> device ------------------------------------------------------
    def _on_user_changed(self, name: str, value: int) -> None:
        try:
            self.bridge.set_parameter(name, value)
        except (ValueError, KeyError) as exc:
            self.diagnostics.add_log(f"rejected {name}={value}: {exc}")

    def _fill_ports(self) -> None:
        self.port_combo.clear()
        self.port_combo.addItem(AUTO)
        with contextlib.suppress(Exception):
            self.port_combo.addItems(list_input_ports())

    def _on_port_chosen(self, index: int) -> None:
        text = self.port_combo.itemText(index)
        self.bridge.set_port(None if text == AUTO else text)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.bridge.stop()
        super().closeEvent(event)
