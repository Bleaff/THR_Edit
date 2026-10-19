"""Saved frequency-response measurements (JSON, one file per run)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


def default_directory() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "thr-control" / "measurements"


@dataclass
class ChannelResult:
    channel: int
    freqs: list[float]
    db: list[float]  # normalised to 0 dB at 1 kHz
    latency_ms: float
    detection_db: float


@dataclass
class Measurement:
    created: str
    settings: dict[str, int]  # the amp's parameters when measured (empty if MIDI was not available)
    sink: str
    source: str
    level_dbfs: float
    channels: list[ChannelResult] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "format": "thr-control-measurement",
            "version": 1,
            "created": self.created,
            "settings": self.settings,
            "sink": self.sink,
            "source": self.source,
            "level_dbfs": self.level_dbfs,
            "channels": [vars(c) for c in self.channels],
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Measurement:
        if data.get("format") != "thr-control-measurement":
            raise ValueError("not a THR Control measurement file")
        channels = [ChannelResult(**c) for c in data["channels"]]  # type: ignore[attr-defined]
        return cls(
            str(data["created"]),
            dict(data["settings"]),  # type: ignore[call-overload]
            str(data["sink"]),
            str(data["source"]),
            float(data["level_dbfs"]),  # type: ignore[arg-type]
            channels,
        )


def save(measurement: Measurement, directory: Path | None = None) -> Path:
    directory = directory or default_directory()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    amp = measurement.settings.get("amp")
    path = directory / f"{stamp}-amp{amp if amp is not None else 'x'}.json"
    path.write_text(json.dumps(measurement.to_json(), indent=1) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Measurement:
    return Measurement.from_json(json.loads(path.read_text(encoding="utf-8")))


def list_saved(directory: Path | None = None) -> list[Path]:
    directory = directory or default_directory()
    return sorted(directory.glob("*.json")) if directory.is_dir() else []
