from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..midi.monitor import format_hex
from ..protocol.parser import Heartbeat, describe, parse


class DiagnosticsView(QWidget):
    def __init__(
        self,
        list_inputs: Callable[[], list[str]],
        list_outputs: Callable[[], list[str]],
    ) -> None:
        super().__init__()
        self._list_inputs = list_inputs
        self._list_outputs = list_outputs
        self._t0 = time.monotonic()
        self._raw_buffer: deque[str] = deque()
        self._raw_all: deque[str] = deque(maxlen=5000)
        self._history: list[str] = []
        self._protocol: deque[str] = deque(maxlen=2000)

        self.ports = QListWidget()
        refresh = QPushButton("Refresh ports")
        refresh.clicked.connect(self.refresh_ports)
        self.history = QListWidget()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("MIDI PORTS"))
        lv.addWidget(self.ports, 2)
        lv.addWidget(refresh)
        lv.addWidget(QLabel("CONNECTION HISTORY"))
        lv.addWidget(self.history, 1)

        self.monitor = QPlainTextEdit()
        self.monitor.setReadOnly(True)
        self.monitor.setMaximumBlockCount(3000)
        self.monitor.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.hide_heartbeats = QCheckBox("Hide heartbeats")
        self.hide_heartbeats.setChecked(True)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.monitor.clear)
        export = QPushButton("Export log…")
        export.clicked.connect(self._export_dialog)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("RAW MIDI MONITOR"))
        bar.addStretch(1)
        bar.addWidget(self.hide_heartbeats)
        bar.addWidget(clear)
        bar.addWidget(export)

        self.protocol_log = QPlainTextEdit()
        self.protocol_log.setReadOnly(True)
        self.protocol_log.setMaximumBlockCount(1000)
        self.protocol_log.setStyleSheet("font-size: 11px;")
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addLayout(bar)
        rv.addWidget(self.monitor, 3)
        rv.addWidget(QLabel("PROTOCOL LOG"))
        rv.addWidget(self.protocol_log, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        outer = QVBoxLayout(self)
        outer.addWidget(split)

        # Incoming traffic can reach ~300 msg/s while a knob moves; render in batches.
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.flush)
        self._timer.start()
        self.refresh_ports()

    # -- feeding -----------------------------------------------------------
    def add_raw(self, direction: str, data: bytes) -> None:
        msg = parse(data)
        line = (
            f"[{time.monotonic() - self._t0:9.3f}] {direction.upper()} "
            f"{format_hex(data)}  | {describe(msg)}"
        )
        self._raw_all.append(line)
        if not (self.hide_heartbeats.isChecked() and isinstance(msg, Heartbeat)):
            self._raw_buffer.append(line)

    def flush(self) -> None:
        if self._raw_buffer:
            lines = list(self._raw_buffer)[-500:]
            self._raw_buffer.clear()
            self.monitor.appendPlainText("\n".join(lines))

    def add_log(self, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        self._protocol.append(line)
        self.protocol_log.appendPlainText(line)

    def add_history(self, state: str, detail: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {state}: {detail}"
        self._history.append(line)
        self.history.addItem(line)
        self.history.scrollToBottom()

    def refresh_ports(self) -> None:
        self.ports.clear()
        try:
            ins, outs = self._list_inputs(), self._list_outputs()
        except Exception as exc:
            self.ports.addItem(f"error: {exc}")
            return
        for name in ins:
            self.ports.addItem(f"in   {name}")
        for name in outs:
            self.ports.addItem(f"out  {name}")
        if not ins and not outs:
            self.ports.addItem("(no MIDI ports)")

    # -- export --------------------------------------------------------------
    def export_text(self) -> str:
        parts = [
            "# THR Control diagnostic log",
            "## Connection history",
            *self._history,
            "## Protocol log",
            *self._protocol,
            "## Raw MIDI (all messages, incl. heartbeats)",
            *self._raw_all,
        ]
        return "\n".join(parts) + "\n"

    def export_to(self, path: str | Path) -> None:
        Path(path).write_text(self.export_text(), encoding="utf-8")

    def _export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostic log", "thr-diagnostics.txt")
        if path:
            self.export_to(path)
