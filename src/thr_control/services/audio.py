"""Audio facade: picks a backend and holds the analysis helpers.

Backends: PipeWire command-line tools (Linux) or PortAudio through ``sounddevice`` (macOS,
Windows, or Linux without the PipeWire tools). ``THR_AUDIO_BACKEND=pipewire|portaudio`` or
:func:`use_backend` overrides the automatic choice. The play/record functions are plain
module-level functions so callers (and tests) can use or replace them without caring which
backend is active.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..domain import measure
from .audio_core import (
    RECORD_CHANNELS,
    THR_SINK_HINT,
    AudioBackend,
    AudioError,
    BlockSource,
    Node,
    read_wav,
    write_pcm24,
    write_pcm32,
    write_wav,
)
from .audio_pipewire import PipeWireBackend, parse_nodes

__all__ = [
    "ACTIVE_DBFS",
    "CLIP_DBFS",
    "RECORD_CHANNELS",
    "THR_SINK_HINT",
    "AudioBackend",
    "AudioError",
    "BlockSource",
    "ChannelLevel",
    "ChannelReport",
    "Node",
    "PipeWireBackend",
    "analyse_channels",
    "choose_backend",
    "correlation",
    "find_thr",
    "get_backend",
    "is_dual_mono",
    "level_report",
    "list_nodes",
    "open_capture",
    "pair_relation",
    "parse_nodes",
    "play_and_record",
    "read_wav",
    "record",
    "sanitize_name",
    "spectral_centroid",
    "use_backend",
    "write_pcm24",
    "write_pcm32",
    "write_wav",
]

_backend: AudioBackend | None = None

PIPEWIRE_TOOLS = ("pw-record", "pw-play", "pw-dump")


def choose_backend(
    preferred: str | None = None,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> AudioBackend:
    """The backend to use: *preferred* (or ``$THR_AUDIO_BACKEND``), else by platform."""
    platform = platform or sys.platform
    wanted = (preferred or os.environ.get("THR_AUDIO_BACKEND") or "auto").lower()
    if wanted not in ("auto", "pipewire", "portaudio"):
        raise AudioError(f"unknown audio backend {wanted!r} (use pipewire or portaudio)")
    if wanted == "pipewire":
        return PipeWireBackend()
    if wanted == "portaudio":
        from .audio_portaudio import PortAudioBackend

        return PortAudioBackend()
    if platform.startswith("linux") and all(which(t) for t in PIPEWIRE_TOOLS):
        return PipeWireBackend()
    from .audio_portaudio import PortAudioBackend

    return PortAudioBackend()


def get_backend() -> AudioBackend:
    global _backend
    if _backend is None:
        _backend = choose_backend()
    return _backend


def use_backend(name: str | None) -> None:
    """Select a backend explicitly ("auto"/None re-runs the automatic choice)."""
    global _backend
    _backend = None if name in (None, "auto") else choose_backend(name)


def list_nodes() -> list[Node]:
    return get_backend().list_nodes()


def find_thr(nodes: list[Node]) -> tuple[Node | None, Node | None]:
    """The THR's playback sink and capture source, if present."""
    sink = next((n for n in nodes if n.kind == "sink" and THR_SINK_HINT in n.description), None)
    source = next((n for n in nodes if n.kind == "source" and THR_SINK_HINT in n.description), None)
    return sink, source


def play_and_record(
    sweep: np.ndarray,
    sink: Node,
    source: Node,
    fs: int = measure.SAMPLE_RATE,
    channels: int = RECORD_CHANNELS,
    lead: float = 0.6,
    tail: float = 1.5,
) -> np.ndarray:
    """Play *sweep* on *sink* while recording *source*; returns [frames, channels]."""
    return get_backend().play_and_record(sweep, sink, source, fs, channels, lead, tail)


def record(
    source: Node,
    seconds: float,
    path: Path,
    fs: int = measure.SAMPLE_RATE,
    channels: int = RECORD_CHANNELS,
) -> None:
    """Record *seconds* from *source* into a WAV file; Ctrl+C keeps what was recorded."""
    get_backend().record(source, seconds, path, fs, channels)


def open_capture(
    source: Node, fs: int = measure.SAMPLE_RATE, channels: int = RECORD_CHANNELS
) -> BlockSource:
    return get_backend().open_capture(source, fs, channels)


@dataclass(frozen=True)
class ChannelReport:
    channel: int
    rms_dbfs: float
    detection_db: float

    @property
    def carries_sweep(self) -> bool:
        return self.detection_db > measure.DETECTION_THRESHOLD_DB


def analyse_channels(
    recorded: np.ndarray, sweep: np.ndarray, fs: int = measure.SAMPLE_RATE
) -> list[ChannelReport]:
    out = []
    for ch in range(recorded.shape[1]):
        x = recorded[:, ch]
        rms = float(np.sqrt(np.mean(x**2))) or 1e-12
        ir = measure.impulse_response(x, sweep, fs)
        out.append(ChannelReport(ch + 1, 20 * np.log10(rms), ir.peak_to_noise_db))
    return out


def sanitize_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")[:60]


ACTIVE_DBFS = -60.0  # a channel quieter than this is treated as silent
CLIP_DBFS = -0.2


@dataclass(frozen=True)
class ChannelLevel:
    channel: int
    rms_dbfs: float
    peak_dbfs: float

    @property
    def active(self) -> bool:
        return self.peak_dbfs > ACTIVE_DBFS

    @property
    def clipping(self) -> bool:
        return self.peak_dbfs >= CLIP_DBFS


def level_report(data: np.ndarray) -> list[ChannelLevel]:
    out = []
    for ch in range(data.shape[1]):
        x = data[:, ch]
        rms = float(np.sqrt(np.mean(x**2))) or 1e-12
        peak = float(np.max(np.abs(x))) or 1e-12
        out.append(ChannelLevel(ch + 1, 20 * np.log10(rms), 20 * np.log10(peak)))
    return out


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised correlation of two equal-length signals (1 = identical, 0 = unrelated)."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0


def spectral_centroid(x: np.ndarray, fs: int = measure.SAMPLE_RATE) -> float:
    """Brightness: the spectrum's centre of mass in Hz (0 for silence)."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    total = float(mag.sum())
    return float((np.fft.rfftfreq(len(x), 1 / fs) * mag).sum() / total) if total > 0 else 0.0


def pair_relation(
    first: np.ndarray, second: np.ndarray, fs: int = measure.SAMPLE_RATE, max_ms: float = 20.0
) -> tuple[int, float]:
    """Strongest cross-correlation of two signals within +-*max_ms*.

    Returns (lag in samples, normalised correlation). A positive lag means *first* is later than
    *second*; the correlation is signed (negative: the signals are polarity-inverted).
    """
    n = 1 << (len(first) + len(second) - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(first, n) * np.conj(np.fft.rfft(second, n)), n)
    reach = int(max_ms / 1000 * fs)
    lags = np.concatenate([np.arange(0, reach), np.arange(-reach, 0)])
    values = np.concatenate([corr[:reach], corr[n - reach :]])
    k = int(np.argmax(np.abs(values)))
    norm = float(np.linalg.norm(first) * np.linalg.norm(second))
    return int(lags[k]), float(values[k] / norm) if norm > 0 else 0.0


def is_dual_mono(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.allclose(left, right, atol=1e-6))
