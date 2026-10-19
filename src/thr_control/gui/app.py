from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..services.preset_manager import PresetManager
from ..storage.repository import PresetRepository
from .bridge import SessionBridge
from .main_window import MainWindow
from .style import STYLESHEET

APP_ID = "io.github.bleaff.ThrControl"
ICON = Path(__file__).resolve().parent.parent / "data" / "icons" / f"{APP_ID}.svg"


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("THR Control")
    app.setDesktopFileName(APP_ID)  # lets Wayland/GNOME match the window to its launcher and icon
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    bridge = SessionBridge()
    manager = PresetManager(PresetRepository())
    manager.seed_starters()
    window = MainWindow(bridge, manager)
    window.show()
    bridge.start()
    return int(app.exec())


def main() -> None:
    """Entry point of the ``thr-control-gui`` launcher."""
    sys.exit(run())
