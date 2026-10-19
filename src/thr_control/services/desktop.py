"""Install / remove a launcher (menu entry and icon) for the current user on Linux."""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

APP_ID = "io.github.bleaff.ThrControl"

DESKTOP = """[Desktop Entry]
Type=Application
Name=THR Control
GenericName=Amplifier Editor
Comment=Unofficial editor for Yamaha THR guitar amplifiers
Exec={exec}
Icon={icon}
Terminal=false
Categories=AudioVideo;Audio;Midi;Music;
Keywords=Yamaha;THR;guitar;amplifier;editor;MIDI;presets;
StartupNotify=true
StartupWMClass={app_id}
"""


class DesktopError(Exception):
    pass


def launcher_command() -> str:
    """Absolute path of the ``thr-control-gui`` launcher belonging to this installation."""
    beside = Path(sys.executable).parent / "thr-control-gui"
    if beside.exists():
        return str(beside)
    found = shutil.which("thr-control-gui")
    if found:
        return found
    raise DesktopError("cannot find the thr-control-gui launcher; is the package installed?")


def _dirs(data_home: Path) -> tuple[Path, Path]:
    return data_home / "applications", data_home / "icons" / "hicolor" / "scalable" / "apps"


def install(data_home: Path, exec_path: str) -> list[Path]:
    """Write the launcher and icon under *data_home* (normally ``~/.local/share``)."""
    apps, icons = _dirs(data_home)
    apps.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    icon_src = resources.files("thr_control.data").joinpath(f"icons/{APP_ID}.svg")
    icon_path = icons / f"{APP_ID}.svg"
    icon_path.write_bytes(icon_src.read_bytes())
    desktop_path = apps / f"{APP_ID}.desktop"
    quoted = f'"{exec_path}"' if " " in exec_path else exec_path
    desktop_path.write_text(
        DESKTOP.format(exec=quoted, icon=APP_ID, app_id=APP_ID), encoding="utf-8"
    )
    return [desktop_path, icon_path]


def remove(data_home: Path) -> list[Path]:
    apps, icons = _dirs(data_home)
    removed = []
    for path in (apps / f"{APP_ID}.desktop", icons / f"{APP_ID}.svg"):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def refresh_caches(data_home: Path) -> None:
    """Best effort: ask the desktop to notice the new files (silently ignored if unavailable)."""
    for cmd in (
        ["update-desktop-database", str(data_home / "applications")],
        ["gtk-update-icon-cache", "-q", "-t", str(data_home / "icons" / "hicolor")],
    ):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True, timeout=20, check=False)
