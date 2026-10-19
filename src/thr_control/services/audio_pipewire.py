"""PipeWire backend: pw-dump / pw-play / pw-record (Linux).

Using the PipeWire command-line tools keeps this free of audio libraries and works while the
desktop session already owns the device.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..domain import measure
from .audio_core import (
    RECORD_CHANNELS,
    AudioError,
    BlockSource,
    Node,
    read_wav,
    write_wav,
)

CHUNK_FRAMES = 4096


def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        ).stdout
    except FileNotFoundError as exc:
        raise AudioError(f"{cmd[0]} not found; PipeWire tools are required") from exc
    except subprocess.CalledProcessError as exc:
        raise AudioError(f"{' '.join(cmd)} failed: {exc.stderr.strip() or exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"{cmd[0]} timed out") from exc


def parse_nodes(pw_dump_text: str) -> list[Node]:
    """Extract audio sinks and sources from ``pw-dump`` JSON."""
    nodes: list[Node] = []
    for obj in json.loads(pw_dump_text):
        props = (obj.get("info") or {}).get("props") or {}
        media = props.get("media.class", "")
        if obj.get("type") != "PipeWire:Interface:Node" or media not in (
            "Audio/Sink",
            "Audio/Source",
        ):
            continue
        nodes.append(
            Node(
                int(obj["id"]),
                str(props.get("node.name", "")),
                str(props.get("node.description", props.get("node.name", ""))),
                "sink" if media == "Audio/Sink" else "source",
                int(props.get("audio.channels", 0) or 0),
            )
        )
    return nodes


def _record_cmd(source: Node, fs: int, channels: int, target: str, *extra: str) -> list[str]:
    return [
        "pw-record",
        "--target",
        source.name,
        "--rate",
        str(fs),
        "--channels",
        str(channels),
        "--format",
        "s32",
        *extra,
        target,
    ]


class PipeWireCapture:
    """Live capture from ``pw-record --raw`` on stdout (raw little-endian 32-bit frames)."""

    def __init__(
        self,
        source: Node,
        fs: int = measure.SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._channels = channels
        self._leftover = b""
        try:
            self._proc = popen(
                _record_cmd(source, fs, channels, "-", "--raw", "--latency", "20ms"),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise AudioError(f"cannot start pw-record: {exc}") from exc

    def read(self) -> np.ndarray | None:
        width = self._channels * 4
        while True:
            data = self._proc.stdout.read1(CHUNK_FRAMES * width)
            if not data:
                return None
            data = self._leftover + data
            usable = len(data) // width * width
            self._leftover = data[usable:]
            if usable:
                frames = np.frombuffer(data[:usable], dtype="<i4").reshape(-1, self._channels)
                return frames / 2147483648.0

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            with contextlib.suppress(OSError):
                self._proc.kill()


class PipeWireBackend:
    name = "pipewire"

    def list_nodes(self) -> list[Node]:
        return parse_nodes(_run(["pw-dump"]))

    def play_and_record(
        self,
        sweep: np.ndarray,
        sink: Node,
        source: Node,
        fs: int = measure.SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
        lead: float = 0.6,
        tail: float = 1.5,
    ) -> np.ndarray:
        """Play *sweep* on *sink* while recording *source*; returns [frames, channels].

        Recording starts first and ends after a tail, so the sweep and the amp's response fit
        inside it however large the latency is.
        """
        with tempfile.TemporaryDirectory(prefix="thr-measure-") as tmp:
            play_path, rec_path = Path(tmp) / "sweep.wav", Path(tmp) / "rec.wav"
            write_wav(play_path, sweep, fs)
            rec = subprocess.Popen(
                _record_cmd(source, fs, channels, str(rec_path)), stderr=subprocess.PIPE
            )
            try:
                time.sleep(lead)
                _run(
                    ["pw-play", "--target", sink.name, str(play_path)],
                    timeout=len(sweep) / fs + 15,
                )
                time.sleep(tail)
            finally:
                rec.terminate()
                try:
                    rec.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    rec.kill()
            if not rec_path.exists():
                raise AudioError(
                    "recording produced no file: "
                    + (rec.stderr.read().decode() if rec.stderr else "")
                )
            data, rate = read_wav(rec_path)
        if rate != fs:
            raise AudioError(f"recorded at {rate} Hz, expected {fs}")
        return data

    def record(
        self,
        source: Node,
        seconds: float,
        path: Path,
        fs: int = measure.SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
    ) -> None:
        """Record *seconds* from *source* into *path* (s32 WAV); Ctrl+C keeps what was recorded."""
        rec = subprocess.Popen(_record_cmd(source, fs, channels, str(path)), stderr=subprocess.PIPE)
        try:
            time.sleep(seconds)
        except KeyboardInterrupt:
            pass
        finally:
            rec.terminate()
            try:
                rec.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rec.kill()
        if not path.exists() or path.stat().st_size < 100:
            raise AudioError(
                "recording produced no file: " + (rec.stderr.read().decode() if rec.stderr else "")
            )

    def open_capture(
        self, source: Node, fs: int = measure.SAMPLE_RATE, channels: int = RECORD_CHANNELS
    ) -> BlockSource:
        return PipeWireCapture(source, fs, channels)
