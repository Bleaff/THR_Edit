"""Safety-aware device controller: the only place parameter writes originate."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..domain.presets import Preset, apply_order
from ..protocol import messages, thr_v2
from ..protocol.parser import SettingsDump, parse


class Transport(Protocol):
    def send(self, data: bytes) -> None: ...

    def wait_for(self, accept: Callable[[bytes], bool], timeout: float) -> bytes | None: ...


class DeviceError(Exception):
    pass


@dataclass(frozen=True)
class SetResult:
    name: str
    requested: int
    confirmed: int | None  # value read back from the amp, None if no readback

    @property
    def ok(self) -> bool:
        return self.confirmed == self.requested


class ThrController:
    def __init__(self, transport: Transport, timeout: float = 3.0, settle: float = 0.05) -> None:
        self._t = transport
        self._timeout = timeout
        self._settle = settle

    def read_dump(self) -> SettingsDump:
        self._t.send(messages.build_settings_request())
        data = self._t.wait_for(lambda d: isinstance(parse(d), SettingsDump), self._timeout)
        msg = parse(data) if data else None
        if not isinstance(msg, SettingsDump):
            raise DeviceError(f"no settings dump received within {self._timeout:g}s")
        if not msg.checksum_ok:
            raise DeviceError("settings dump failed its checksum")
        return msg

    def read_settings(self) -> dict[str, int]:
        return thr_v2.decode_dump(self.read_dump().payload)

    def set_parameter(self, name: str, value: int, verify: bool = True) -> SetResult:
        if name not in thr_v2.PARAMETERS:
            raise KeyError(f"unknown or unsupported parameter {name!r}")
        command = thr_v2.build_set_command(name, value)  # validates range
        self._t.send(command)
        if not verify:
            return SetResult(name, value, None)
        time.sleep(self._settle)
        return SetResult(name, value, self.read_settings()[name])


def apply_preset(
    controller: ThrController, preset: Preset, amp_settle: float = 0.15
) -> list[SetResult]:
    """Write *preset* to the amp (amp model first), then read back and return every mismatch."""
    items = apply_order(preset.settings)
    for name, value in items:
        controller.set_parameter(name, value, verify=False)
        if name == "amp":
            time.sleep(amp_settle)  # the amp re-applies its cab/tone defaults on a model change
    time.sleep(0.1)
    actual = controller.read_settings()
    results = [SetResult(name, value, actual[name]) for name, value in items]
    return [r for r in results if not r.ok]
