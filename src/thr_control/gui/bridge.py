"""Qt adapter around :class:`DeviceSession` (signals are queued to the GUI thread)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..services.session import AlsaBackend, Backend, DeviceSession, SessionEvents


class SessionBridge(QObject):
    status = Signal(str, str)
    settings = Signal(dict)
    param = Signal(str, int)
    raw = Signal(str, bytes)
    log = Signal(str)
    busy = Signal(bool)

    def __init__(self, backend: Backend | None = None) -> None:
        super().__init__()
        self.backend: Backend = backend or AlsaBackend()
        self.session = DeviceSession(
            self.backend,
            SessionEvents(
                on_status=self.status.emit,
                on_settings=self.settings.emit,
                on_param=self.param.emit,
                on_raw=self.raw.emit,
                on_log=self.log.emit,
                on_busy=self.busy.emit,
            ),
        )

    def start(self) -> None:
        self.session.start()

    def stop(self) -> None:
        self.session.stop()

    def set_parameter(self, name: str, value: int) -> None:
        self.session.set_parameter(name, value)

    def set_port(self, port: str | None) -> None:
        if isinstance(self.backend, AlsaBackend):
            self.backend.preferred_port = port
            self.session.request_reconnect()

    def refresh(self) -> None:
        self.session.request_refresh()
