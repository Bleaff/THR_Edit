"""Read-only MIDI monitor.

Opens an *input* port only. Nothing is ever written to the device.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any


@dataclass(frozen=True)
class CapturedMessage:
    """One received MIDI message with a monotonic receive time (seconds)."""

    timestamp: float
    kind: str
    data: bytes


def format_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def format_message(msg: CapturedMessage, t0: float = 0.0) -> str:
    rel = msg.timestamp - t0
    label = "SYSEX" if msg.kind == "sysex" else msg.kind.upper()
    return f"[{rel:10.3f}s] {label:<14} ({len(msg.data):3d} B) {format_hex(msg.data)}"


class MidiMonitor:
    """Receive messages from one input port and hand them to a callback.

    Callbacks run on the rtmidi thread; keep them short and thread-safe.
    """

    def __init__(self, port_name: str, on_message: Callable[[CapturedMessage], None]) -> None:
        self.port_name = port_name
        self._on_message = on_message
        self._port: Any = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def open(self) -> None:
        import mido

        # Polled on our own thread rather than through a rtmidi callback: closing a port with a
        # callback while a message arrives can deadlock python-rtmidi.
        self._port = mido.open_input(self.port_name)
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, name="midi-monitor", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            port, self._port = self._port, None
        if port is not None:
            port.close()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            port = self._port
            msg = port.poll() if port is not None else None
            if msg is None:
                time.sleep(0.002)
            else:
                self._handle(msg)

    @property
    def is_open(self) -> bool:
        return self._port is not None

    def _handle(self, msg: Any) -> None:
        kind = "sysex" if msg.type == "sysex" else msg.type
        # bytes() of a mido message gives the raw wire bytes, incl. F0/F7 for sysex.
        data = bytes(msg.bytes())
        self._on_message(CapturedMessage(time.monotonic(), kind, data))

    def __enter__(self) -> MidiMonitor:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
