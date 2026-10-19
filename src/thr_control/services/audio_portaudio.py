"""PortAudio backend (via ``sounddevice``): macOS and Windows, or Linux without PipeWire tools.

Uses two independent streams (one to play, one to record) instead of a single full-duplex
stream, because duplex across two different devices is not supported by every host API. The
sweep analysis finds the delay between them on its own, so the two need not start together.
"""

from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..domain import measure
from .audio_core import RECORD_CHANNELS, AudioError, BlockSource, Node, write_pcm32


def _import_sounddevice() -> Any:
    try:
        import sounddevice
    except (ImportError, OSError) as exc:  # OSError: the PortAudio library itself is missing
        raise AudioError(
            "sounddevice (PortAudio) is not available; install it with `pip install sounddevice`"
        ) from exc
    return sounddevice


class PortAudioCapture:
    """Live capture through an input stream; blocks arrive on a queue from PortAudio's thread."""

    def __init__(self, sd: Any, device: int, fs: int, channels: int) -> None:
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=512)
        self._closed = False
        self.dropped = 0
        try:
            self._stream = sd.InputStream(
                device=device,
                channels=channels,
                samplerate=fs,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise AudioError(f"cannot open the audio input: {exc}") from exc

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        try:
            self._queue.put_nowait(indata.copy())
        except queue.Full:
            self.dropped += 1  # never block PortAudio's real-time thread

    def read(self) -> np.ndarray | None:
        while not self._closed:
            try:
                return self._queue.get(timeout=0.2).astype(np.float64)
            except queue.Empty:
                continue
        return None

    def close(self) -> None:
        self._closed = True
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


class PortAudioBackend:
    name = "portaudio"

    def __init__(self, sd: Any = None) -> None:
        self._sd = sd if sd is not None else _import_sounddevice()

    def list_nodes(self) -> list[Node]:
        try:
            devices = self._sd.query_devices()
        except Exception as exc:
            raise AudioError(f"cannot list audio devices: {exc}") from exc
        nodes: list[Node] = []
        for index, dev in enumerate(devices):
            name = str(dev["name"])
            if dev["max_input_channels"] > 0:
                nodes.append(Node(index, name, name, "source", int(dev["max_input_channels"])))
            if dev["max_output_channels"] > 0:
                nodes.append(Node(index, name, name, "sink", int(dev["max_output_channels"])))
        return nodes

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
        total = int((len(sweep) / fs + lead + tail) * fs)
        buf = np.zeros((total, channels), dtype=np.float32)
        pos = 0

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            nonlocal pos
            n = min(frames, total - pos)
            if n > 0:
                buf[pos : pos + n] = indata[:n]
                pos += n

        out_channels = min(2, sink.channels or 2)
        out = np.repeat(sweep.astype(np.float32)[:, None], out_channels, axis=1)
        sd = self._sd
        try:
            with sd.InputStream(
                device=source.id,
                channels=channels,
                samplerate=fs,
                dtype="float32",
                callback=callback,
            ):
                time.sleep(lead)
                with sd.OutputStream(
                    device=sink.id, channels=out_channels, samplerate=fs, dtype="float32"
                ) as player:
                    player.write(out)
                time.sleep(tail)
        except Exception as exc:
            raise AudioError(f"audio playback/recording failed: {exc}") from exc
        return buf[:pos].astype(np.float64)

    def record(
        self,
        source: Node,
        seconds: float,
        path: Path,
        fs: int = measure.SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
    ) -> None:
        """Record *seconds* from *source* into *path* (32-bit WAV); Ctrl+C keeps the take."""
        capture = PortAudioCapture(self._sd, source.id, fs, channels)
        blocks: list[np.ndarray] = []
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                block = capture.read()
                if block is None:
                    break
                blocks.append(block)
        except KeyboardInterrupt:
            pass
        finally:
            capture.close()
        if not blocks:
            raise AudioError("recording produced no audio")
        write_pcm32(path, np.concatenate(blocks), fs)

    def open_capture(
        self, source: Node, fs: int = measure.SAMPLE_RATE, channels: int = RECORD_CHANNELS
    ) -> BlockSource:
        return PortAudioCapture(self._sd, source.id, fs, channels)
