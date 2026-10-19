"""MIDI transport for the read-only request/response phase.

The only way bytes leave this class is :meth:`send`, which enforces
the allowlist in :mod:`thr_control.protocol.safety`: the settings request and
validated parameter-set commands.
"""

from __future__ import annotations

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

    def open(self) -> None:
        import mido

        # Polled, not callback-driven: closing a port that has a Python callback while a message
        # arrives can deadlock python-rtmidi (the native thread waits for the GIL that the
        # closing thread holds). Messages queue inside rtmidi until poll() takes them.
        self._in = mido.open_input(self.input_port)
        self._out = mido.open_output(self.output_port)

    def close(self) -> None:
        for port in (self._in, self._out):
            if port is not None:
                port.close()
        self._in = self._out = None

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
        deadline = time.monotonic() + timeout
        while True:
            if self._in is None:
                return None
            msg = self._in.poll()
            if msg is not None:
                if msg.type == "sysex":
                    return bytes(msg.bytes())
                continue  # other message types are not used
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.002, remaining))

    def wait_for(self, accept: Callable[[bytes], bool], timeout: float) -> bytes | None:
        """Return the first received SysEx for which *accept* is true, or None on timeout."""
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            data = self.poll(remaining)
            if data is None:
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
