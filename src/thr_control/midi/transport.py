"""MIDI transport for the read-only request/response phase.

The only way bytes leave this class is :meth:`send`, which enforces
the allowlist in :mod:`thr_control.protocol.safety`: the settings request and
validated parameter-set commands.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ..protocol.safety import ensure_allowed_message


class RequestTransport:
    def __init__(self, input_port: str, output_port: str) -> None:
        self.input_port = input_port
        self.output_port = output_port
        self._in: Any = None
        self._out: Any = None
        self._queue: queue.Queue[bytes] = queue.Queue()

    def open(self) -> None:
        import mido

        self._in = mido.open_input(self.input_port, callback=self._on_message)
        self._out = mido.open_output(self.output_port)

    def close(self) -> None:
        for port in (self._in, self._out):
            if port is not None:
                port.close()
        self._in = self._out = None

    def _on_message(self, msg: Any) -> None:
        if msg.type == "sysex":
            self._queue.put(bytes(msg.bytes()))

    def send(self, data: bytes) -> None:
        """Send *data* if (and only if) it passes the allowlist."""
        ensure_allowed_message(data)
        import mido

        self._out.send(mido.Message.from_bytes(list(data)))

    def is_alive(self) -> bool:
        """True while the amp's ALSA ports still exist (they vanish when USB is unplugged)."""
        import mido

        try:
            return self.input_port in mido.get_input_names() and (
                self.output_port in mido.get_output_names()
            )
        except Exception:
            return True  # cannot tell; do not drop the connection on a failed query

    def poll(self, timeout: float) -> bytes | None:
        """Return the next received SysEx message, or None after *timeout* seconds."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for(self, accept: Callable[[bytes], bool], timeout: float) -> bytes | None:
        """Return the first received SysEx for which *accept* is true, or None on timeout."""
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                data = self._queue.get(timeout=remaining)
            except queue.Empty:
                return None
            if accept(data):
                return data
        return None

    def __enter__(self) -> RequestTransport:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
