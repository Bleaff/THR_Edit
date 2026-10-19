"""Shared audio types and WAV helpers used by every audio backend."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..domain import measure

THR_SINK_HINT = "THR"
RECORD_CHANNELS = 4  # the THR5's USB capture exposes four channels


class AudioError(Exception):
    pass


@dataclass(frozen=True)
class Node:
    """An audio output ("sink") or input ("source").

    *id* is what the user passes to ``--sink`` / ``--source``. A duplex device appears twice
    (once per kind), so an id is only unique together with its kind.
    """

    id: int
    name: str  # backend-specific handle (PipeWire node.name, PortAudio device name)
    description: str
    kind: str  # "sink" or "source"
    channels: int = 0  # channel count when the backend reports it


class BlockSource(Protocol):
    """A live capture: blocks of frames shaped [n, channels], floats in -1..1."""

    def read(self) -> np.ndarray | None:
        """The next block, or None when the stream has ended or been closed."""
        ...

    def close(self) -> None: ...


class AudioBackend(Protocol):
    name: str

    def list_nodes(self) -> list[Node]: ...

    def play_and_record(
        self,
        sweep: np.ndarray,
        sink: Node,
        source: Node,
        fs: int = measure.SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
        lead: float = 0.6,
        tail: float = 1.5,
    ) -> np.ndarray: ...

    def record(
        self,
        source: Node,
        seconds: float,
        path: Path,
        fs: int = measure.SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
    ) -> None: ...

    def open_capture(
        self, source: Node, fs: int = measure.SAMPLE_RATE, channels: int = RECORD_CHANNELS
    ) -> BlockSource: ...


def write_wav(path: Path, samples: np.ndarray, fs: int, channels: int = 2) -> None:
    pcm = np.clip(np.round(samples * 2147483648.0), -2147483648, 2147483647).astype("<i4")
    frames = np.repeat(pcm[:, None], channels, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(4)
        w.setframerate(fs)
        w.writeframes(frames.tobytes())


def write_pcm24(path: Path, samples: np.ndarray, fs: int) -> None:
    """Write [frames, channels] floats (-1..1) as a 24-bit PCM WAV."""
    # Round (not truncate) and use the same scale the reader divides by: error <= half a step.
    pcm = np.clip(np.round(samples * 8388608.0), -8388608, 8388607).astype("<i4")
    raw = pcm.view(np.uint8).reshape(-1, 4)[:, :3]  # keep the low 3 bytes (little endian)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(3)
        w.setframerate(fs)
        w.writeframes(raw.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Return (samples shaped [frames, channels] in -1..1, sample rate); 16/24/32-bit PCM."""
    with wave.open(str(path), "rb") as w:
        width, channels = w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
        rate = w.getframerate()
    if width == 4:
        data = np.frombuffer(raw, dtype="<i4") / 2147483648.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        value = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        data = np.where(value >= 1 << 23, value - (1 << 24), value) / 8388608.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2") / 32768.0
    else:
        raise AudioError(f"unexpected sample width {width}")
    return data.reshape(-1, channels), rate


def write_pcm32(path: Path, samples: np.ndarray, fs: int) -> None:
    """Write [frames, channels] floats (-1..1) as a 32-bit PCM WAV."""
    pcm = np.clip(np.round(samples * 2147483648.0), -2147483648, 2147483647).astype("<i4")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(4)
        w.setframerate(fs)
        w.writeframes(np.ascontiguousarray(pcm).tobytes())
