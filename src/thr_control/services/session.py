"""Background device session: connection lifecycle, coalesced writes, live events.

Qt-free. All MIDI I/O happens on one worker thread; the GUI only calls the
thread-safe methods (:meth:`set_parameter`, :meth:`request_refresh`, ...) and
receives results through the callbacks in :class:`SessionEvents`.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ..midi.discovery import detect_devices, list_input_ports, list_output_ports
from ..midi.transport import RequestTransport
from ..protocol import messages, thr_v2
from ..protocol.parser import Heartbeat, ParameterCommand, SettingsDump, parse

WRITE_INTERVAL = 0.02  # min seconds between write bursts (knob drags are coalesced)
REFRESH_DELAY = 0.4  # read the amp back this long after the last write
HEARTBEAT_TIMEOUT = 3.0  # amp sends ~2 heartbeats/s; silence means it is gone
DUMP_TIMEOUT = 3.0
RECONNECT_DELAY = 1.0


class SessionTransport(Protocol):
    def send(self, data: bytes) -> None: ...
    def poll(self, timeout: float) -> bytes | None: ...
    def close(self) -> None: ...


class Backend(Protocol):
    def connect(self) -> tuple[SessionTransport, str]:
        """Open the amp; return (transport, label). Raise ConnectionError if unavailable."""
        ...


def _noop(*_: object) -> None:
    return None


@dataclass
class SessionEvents:
    on_status: Callable[[str, str], None] = _noop  # ("connected"|"disconnected", detail)
    on_settings: Callable[[dict[str, int]], None] = _noop  # full state after a dump
    on_param: Callable[[str, int], None] = _noop  # single change reported by the amp
    on_raw: Callable[[str, bytes], None] = _noop  # ("rx"|"tx", sysex bytes)
    on_log: Callable[[str], None] = _noop
    on_busy: Callable[[bool], None] = _noop  # amp stopped/resumed its heartbeat (e.g. tuner)


class AlsaBackend:
    """Finds the amp through ALSA MIDI (optionally pinned to a user-chosen port)."""

    def __init__(self) -> None:
        self.preferred_port: str | None = None

    def connect(self) -> tuple[SessionTransport, str]:
        try:
            ins, outs = list_input_ports(), list_output_ports()
        except Exception as exc:
            raise ConnectionError(f"cannot query MIDI ports: {exc}") from exc
        if self.preferred_port:
            in_name = next((p for p in ins if self.preferred_port in p), None)
            out_name = next((p for p in outs if self.preferred_port in p), None)
            if in_name is None or out_name is None:
                raise ConnectionError(f"port {self.preferred_port!r} not available")
            label = in_name
        else:
            devices = [d for d in detect_devices(ins, outs) if d.input_port and d.output_port]
            if not devices:
                raise ConnectionError("no THR amplifier found")
            in_name, out_name = devices[0].input_port, devices[0].output_port
            assert in_name and out_name
            label = f"{devices[0].model} ({in_name})"
        transport = RequestTransport(in_name, out_name)
        try:
            transport.open()
        except Exception as exc:
            raise ConnectionError(f"cannot open {in_name!r}: {exc}") from exc
        return transport, label


@dataclass
class _State:
    pending: dict[str, int] = field(default_factory=dict)
    written: dict[str, int] = field(default_factory=dict)
    refresh_now: bool = False
    reconnect: bool = False


class DeviceSession:
    def __init__(
        self,
        backend: Backend,
        events: SessionEvents | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self.events = events or SessionEvents()
        self._clock = clock
        self._lock = threading.Lock()
        self._state = _State()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- thread-safe API ---------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="thr-session", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def set_parameter(self, name: str, value: int) -> None:
        """Queue a write (latest per parameter wins); ValueError/KeyError if invalid."""
        thr_v2.build_set_command(name, value)  # validate now, on the caller's thread
        with self._lock:
            self._state.pending[name] = value

    def request_refresh(self) -> None:
        with self._lock:
            self._state.refresh_now = True

    def request_reconnect(self) -> None:
        with self._lock:
            self._state.reconnect = True

    # -- worker ------------------------------------------------------------
    def _run(self) -> None:
        last_detail = None
        while not self._stop.is_set():
            try:
                transport, label = self._backend.connect()
            except ConnectionError as exc:
                if str(exc) != last_detail:
                    self.events.on_status("disconnected", str(exc))
                    last_detail = str(exc)
                self._stop.wait(RECONNECT_DELAY)
                continue
            last_detail = None
            self.events.on_status("connected", label)
            detail = "connection closed"
            try:
                self._run_connected(transport)
            except Exception as exc:  # any failure drops back to reconnecting
                detail = str(exc) or type(exc).__name__
                self.events.on_log(f"connection lost: {detail}")
            finally:
                with contextlib.suppress(Exception):
                    transport.close()
            if not self._stop.is_set():
                self.events.on_status("disconnected", detail)
                last_detail = detail
                self._stop.wait(RECONNECT_DELAY)

    @staticmethod
    def _is_alive(transport: SessionTransport) -> bool:
        check = getattr(transport, "is_alive", None)
        return True if check is None else bool(check())

    def _send(self, transport: SessionTransport, data: bytes) -> None:
        transport.send(data)
        self.events.on_raw("tx", data)

    def _run_connected(self, transport: SessionTransport) -> None:
        now = self._clock()
        last_heartbeat = now
        last_write = 0.0
        refresh_at: float | None = now  # initial read
        dump_since: float | None = None
        busy = False
        with self._lock:
            self._state.reconnect = False
        while not self._stop.is_set():
            data = transport.poll(0.01)
            now = self._clock()
            if data is not None:
                self.events.on_raw("rx", data)
                msg = parse(data)
                if isinstance(msg, Heartbeat):
                    last_heartbeat = now
                elif isinstance(msg, SettingsDump):
                    dump_since = None
                    self._on_dump(msg)
                elif isinstance(msg, ParameterCommand):
                    self._on_command(msg)
            if now - last_heartbeat > HEARTBEAT_TIMEOUT:
                # The amp pauses its heartbeat for the whole time its tuner is on (observed:
                # 12.5 s), so silence alone is not a disconnect. Unplugging removes the ALSA
                # ports; only then do we drop the connection.
                if not self._is_alive(transport):
                    raise ConnectionError("amp disconnected")
                if not busy:
                    busy = True
                    self.events.on_busy(True)
                    self.events.on_log("no heartbeat but the amp is still present (tuner mode?)")
            elif busy:
                busy = False
                self.events.on_busy(False)
                refresh_at = now  # state may have changed while the amp was busy

            with self._lock:
                reconnect = self._state.reconnect
                refresh_now, self._state.refresh_now = self._state.refresh_now, False
                pending: dict[str, int] = {}
                if self._state.pending and not busy and now - last_write >= WRITE_INTERVAL:
                    pending, self._state.pending = self._state.pending, {}
            if reconnect:
                raise ConnectionError("reconnecting")
            if refresh_now:
                refresh_at = now
            for name, value in pending.items():
                self._send(transport, thr_v2.build_set_command(name, value))
                self._state.written[name] = value
                last_write = now
                refresh_at = now + REFRESH_DELAY
            if refresh_at is not None and now >= refresh_at and not busy:
                self._send(transport, messages.build_settings_request())
                refresh_at = None
                dump_since = now
            if dump_since is not None and now - dump_since > DUMP_TIMEOUT:
                self.events.on_log("no settings dump received from the amp")
                dump_since = None

    def _on_dump(self, dump: SettingsDump) -> None:
        if not dump.checksum_ok:
            self.events.on_log("settings dump failed its checksum; ignored")
            return
        settings = thr_v2.decode_dump(dump.payload)
        for name, value in self._state.written.items():
            if settings.get(name) != value:
                self.events.on_log(f"amp reports {name}={settings.get(name)}, expected {value}")
        self._state.written.clear()
        self.events.on_settings(settings)

    def _on_command(self, cmd: ParameterCommand) -> None:
        decoded = thr_v2.decode_command(cmd.body)
        if decoded is not None:
            self.events.on_param(decoded[0].name, decoded[1])
