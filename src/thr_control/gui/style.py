"""Dark, amplifier-inspired look (QSS)."""

ACCENT = "#e8a33d"
TRACK = "#3a3d44"
BODY_LIGHT = "#4a4d55"
BODY_DARK = "#17181b"

STYLESHEET = f"""
QLabel {{ background: transparent; }}
QMainWindow, QWidget {{ background: #1e1f23; color: #d8d8d8; font-size: 13px; }}
QGroupBox {{ border: 1px solid #34363c; border-radius: 8px; margin-top: 14px; padding: 12px 8px 8px 8px;
  background: #24262b; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {ACCENT};
  font-weight: bold; letter-spacing: 1px; }}
QLabel#status {{ font-weight: bold; padding: 2px 8px; }}
QLabel#busy {{ background: {ACCENT}; color: #1a1a1a; font-weight: bold; border-radius: 6px; padding: 3px 10px; }}
QLabel#knobLabel {{ color: #b8b8b8; font-size: 11px; font-weight: bold; letter-spacing: 1px; }}
QLabel#knobValue {{ color: {ACCENT}; font-family: monospace; }}
QPushButton {{ background: #2f3238; border: 1px solid #44474f; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ background: #383b42; }}
QPushButton:checked {{ background: {ACCENT}; color: #1a1a1a; font-weight: bold; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #6a6a6a; background: #2a2c31; }}
QComboBox, QPlainTextEdit, QListWidget {{ background: #17181b; border: 1px solid #34363c; border-radius: 4px; }}
QTabWidget::pane {{ border: 1px solid #34363c; border-radius: 6px; }}
QTabBar::tab {{ background: #2a2c31; padding: 8px 18px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabBar::tab:selected {{ background: #34363c; color: {ACCENT}; }}
"""
