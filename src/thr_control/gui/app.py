from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..services.preset_manager import PresetManager
from ..storage.repository import PresetRepository
from .bridge import SessionBridge
from .main_window import MainWindow
from .style import STYLESHEET


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    bridge = SessionBridge()
    manager = PresetManager(PresetRepository())
    manager.seed_starters()
    window = MainWindow(bridge, manager)
    window.show()
    bridge.start()
    return int(app.exec())
