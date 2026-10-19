"""JSON preset storage: one file per preset, written atomically."""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from ..domain.presets import Preset

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def default_directory() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "thr-control" / "presets"


class PresetRepository:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_directory()
        self.errors: list[str] = []  # files that could not be loaded by the last load_all()

    def _path(self, preset_id: str) -> Path:
        if not _ID_RE.match(preset_id):
            raise ValueError(f"invalid preset id {preset_id!r}")
        return self.directory / f"{preset_id}.json"

    def load_all(self) -> list[Preset]:
        self.errors = []
        presets: list[Preset] = []
        if not self.directory.is_dir():
            return presets
        for path in sorted(self.directory.glob("*.json")):
            try:
                preset = Preset.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as exc:
                self.errors.append(f"{path.name}: {exc}")
                continue
            if preset.id != path.stem:
                self.errors.append(f"{path.name}: id does not match file name")
                continue
            presets.append(preset)
        return presets

    def get(self, preset_id: str) -> Preset | None:
        path = self._path(preset_id)
        if not path.is_file():
            return None
        return Preset.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, preset: Preset) -> None:
        path = self._path(preset.id)
        self.directory.mkdir(parents=True, exist_ok=True)
        text = json.dumps(preset.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def delete(self, preset_id: str) -> bool:
        path = self._path(preset_id)
        if not path.is_file():
            return False
        path.unlink()
        return True
