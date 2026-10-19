"""Where THR Control keeps its files, following each platform's conventions.

Linux: ``~/.local/share/thr-control`` (honours ``$XDG_DATA_HOME``); macOS:
``~/Library/Application Support/thr-control``; Windows: ``%LOCALAPPDATA%``.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs

APP = "thr-control"


def data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP, appauthor=False))


def presets_dir() -> Path:
    return data_dir() / "presets"


def measurements_dir() -> Path:
    return data_dir() / "measurements"


def takes_dir() -> Path:
    """Where recorded takes go: the user's Music folder."""
    return Path(platformdirs.user_music_dir()) / APP
