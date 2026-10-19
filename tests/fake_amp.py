"""In-memory fake THR5: applies allowlisted set commands and answers dump requests."""

from __future__ import annotations

import time
from collections.abc import Callable

from thr_control.protocol import messages as m
from thr_control.protocol import thr_v2
from thr_control.protocol.parser import SettingsDump, parse
from thr_control.protocol.safety import ensure_allowed_message


class FakeAmp:
    def __init__(self, payload: bytes | None = None) -> None:
        self.payload = bytearray(payload or bytes(m.DUMP_PAYLOAD_SIZE))
        self.sent: list[bytes] = []
        self._outbox: list[bytes] = []
        self.ignore_sets = False
        self.heartbeat_interval: float | None = None  # seconds; None = no heartbeats
        self._last_hb = time.monotonic()
        self.closed = False
        self.alive = True  # False emulates the USB ports disappearing
        self.sets: list[tuple[str, int]] = []

    def _dump(self) -> bytes:
        body = bytes(m.DUMP_HEADER[m.DUMP_CHECKSUM_START :]) + bytes(self.payload)
        return m.DUMP_HEADER + bytes(self.payload) + bytes([m.checksum(body), m.SYSEX_END])

    def send(self, data: bytes) -> None:
        ensure_allowed_message(data)  # same gate as the real transport
        self.sent.append(data)
        if data == m.build_settings_request():
            self._outbox.append(self._dump())
        elif not self.ignore_sets:
            decoded = thr_v2.decode_command(
                data[len(m.COMMAND_PREFIX) : -1], thr_v2.decode_dump(bytes(self.payload))
            )
            assert decoded is not None
            param, value = decoded
            raw = param.dump_bytes(param.to_wire(value))
            self.payload[param.dump_offset : param.dump_offset + len(raw)] = raw
            self.sets.append((param.name, value))

    def inject_event(self, name: str, value: int) -> None:
        """Emulate a knob turn on the amp: update state and emit the amp's own event."""
        param = thr_v2.PARAMETERS[name]
        raw = param.dump_bytes(param.to_wire(value))
        self.payload[param.dump_offset : param.dump_offset + len(raw)] = raw
        self._outbox.append(thr_v2.build_set_command(name, value))

    def inject_raw(self, data: bytes) -> None:
        self._outbox.append(data)

    def poll(self, timeout: float) -> bytes | None:
        if self._outbox:
            return self._outbox.pop(0)
        if self.heartbeat_interval is not None and (
            time.monotonic() - self._last_hb >= self.heartbeat_interval
        ):
            self._last_hb = time.monotonic()
            return m.build_heartbeat(m.ThrModel.THR5)
        time.sleep(min(timeout, 0.002))
        return None

    def is_alive(self) -> bool:
        return self.alive

    def close(self) -> None:
        self.closed = True

    def wait_for(self, accept: Callable[[bytes], bool], timeout: float) -> bytes | None:
        while self._outbox:
            data = self._outbox.pop(0)
            if accept(data):
                return data
        return None


def real_payload() -> bytes:
    from pathlib import Path

    lines = (Path(__file__).parent / "fixtures" / "thr5_dump_baseline.txt").read_text().splitlines()
    msg = parse(bytes.fromhex(" ".join(ln for ln in lines if not ln.startswith("#"))))
    assert isinstance(msg, SettingsDump)
    return msg.payload
