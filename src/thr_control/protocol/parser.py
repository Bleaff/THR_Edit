"""Pure SysEx parser: bytes in, typed message out. No I/O."""

from __future__ import annotations

from dataclasses import dataclass

from . import messages as m


@dataclass(frozen=True)
class Heartbeat:
    model: m.ThrModel | None
    model_byte: int


@dataclass(frozen=True)
class SettingsDump:
    """A full settings dump. *payload* is the raw 256 bytes.

    The field layout inside the payload is only documented for THR10; for THR5
    it is unverified, so only the raw bytes and the (THR10-layout) name are given.
    """

    payload: bytes
    checksum_ok: bool

    @property
    def name(self) -> str:
        """Preset name (payload[0:64], NUL-terminated ASCII). THR10 layout; unverified on THR5."""
        raw = self.payload[:64].split(b"\x00", 1)[0]
        return "".join(chr(b) for b in raw if 0x20 <= b <= 0x7E)

    def control_values(self) -> dict[str, int]:
        """Amp/EQ fields at the THR10 payload offsets.

        ASSUMPTION: THR5 appears to use the same offsets (values in a real THR5
        dump are all in range 0-100 and plausible) but this is NOT yet confirmed
        against known knob positions.
        """
        p = self.payload
        return {
            "amp": p[128],
            "gain": p[129],
            "master": p[130],
            "bass": p[131],
            "middle": p[132],
            "treble": p[133],
            "cab": p[134],
        }


@dataclass(frozen=True)
class ParameterCommand:
    """A single-parameter message. *body* is everything after the command prefix."""

    body: bytes

    @property
    def single_value(self) -> tuple[int, int] | None:
        """(parameter id, value) for the verified 3-byte form ``<id> 00 <value>``, else None."""
        if len(self.body) == 3 and self.body[1] == 0x00:
            return self.body[0], self.body[2]
        return None


@dataclass(frozen=True)
class SystemMessage:
    """System-type message. *body* is the two bytes after the system prefix. Meaning unknown."""

    body: bytes


@dataclass(frozen=True)
class Unknown:
    data: bytes
    reason: str


Message = Heartbeat | SettingsDump | ParameterCommand | SystemMessage | Unknown


def parse(data: bytes) -> Message:
    """Classify one complete SysEx message (including F0 and F7)."""
    if len(data) < 5 or data[0] != m.SYSEX_START or data[-1] != m.SYSEX_END:
        return Unknown(data, "not a complete SysEx message")
    if data[:3] != m.PREFIX:
        return Unknown(data, "not a THR message (prefix F0 43 7D)")

    kind = data[3]
    if kind == m.TYPE_HEARTBEAT and data[4:7] == b"DTA" and len(data) == 9:
        try:
            model: m.ThrModel | None = m.ThrModel(data[7])
        except ValueError:
            model = None
        return Heartbeat(model, data[7])
    if kind == m.TYPE_DUMP:
        if len(data) == m.DUMP_SIZE and data[: len(m.DUMP_HEADER)] == m.DUMP_HEADER:
            body = data[m.DUMP_CHECKSUM_START : -2]
            ok = m.checksum(body) == data[-2]
            return SettingsDump(data[len(m.DUMP_HEADER) : -2], ok)
        return Unknown(data, f"dump-type message with unexpected size {len(data)}")
    if data[: len(m.SYSTEM_PREFIX)] == m.SYSTEM_PREFIX and len(data) == len(m.SYSTEM_PREFIX) + 3:
        return SystemMessage(data[len(m.SYSTEM_PREFIX) : -1])
    if data[: len(m.COMMAND_PREFIX)] == m.COMMAND_PREFIX:
        return ParameterCommand(data[len(m.COMMAND_PREFIX) : -1])
    return Unknown(data, f"unrecognized message type 0x{kind:02X}")


def describe(msg: Message) -> str:
    """One-line human description for logs / the probe."""
    if isinstance(msg, Heartbeat):
        return f"heartbeat {msg.model.name if msg.model else f'model 0x{msg.model_byte:02X}?'}"
    if isinstance(msg, SettingsDump):
        status = "checksum OK" if msg.checksum_ok else "CHECKSUM BAD"
        return f"settings dump, name={msg.name!r}, {status}"
    if isinstance(msg, ParameterCommand):
        if (sv := msg.single_value) is not None:
            return f"parameter id=0x{sv[0]:02X} value={sv[1]}"
        return f"parameter command body={msg.body.hex(' ').upper()} (form not understood)"
    if isinstance(msg, SystemMessage):
        return f"system message body={msg.body.hex(' ').upper()} (meaning unknown)"
    return f"unknown: {msg.reason}"
