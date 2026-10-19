"""THR5 (V2 firmware) parameter table.

Every entry below was observed on a real THR5A running THR5 V2 firmware:
  * its command id appeared in the amp's own knob/button events
    (tests/fixtures + logs/knobs2.log), and
  * its dump offset changed in the knob map (tests/fixtures/thr5a_knob_map.json)
    or matches the THR10 layout for the same id.

Parameters not listed here are NOT writable through this application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import messages as m

SWITCH_ON = 0x00
SWITCH_OFF = 0x7F


class Kind(Enum):
    LEVEL = "level"  # integer 0..max
    ENUM = "enum"  # integer 0..max (index)
    SWITCH = "switch"  # 0 = on, 0x7F = off (user value 1/0)


@dataclass(frozen=True)
class Parameter:
    name: str
    command_id: int
    dump_offset: int
    kind: Kind
    maximum: int = 100
    note: str = ""
    minimum: int = 0
    width: int = 1  # 1: command body ``<id> 00 <v>``; 2: 14-bit ``<id> <v>>>7 <v>&7F``

    def to_wire(self, value: int) -> int:
        """Convert a user value (switch: 1/0) to the wire/dump byte; raise ValueError if invalid."""
        if self.kind is Kind.SWITCH:
            if value not in (0, 1):
                raise ValueError(f"{self.name}: expected 0 (off) or 1 (on), got {value}")
            return SWITCH_ON if value else SWITCH_OFF
        if not self.minimum <= value <= self.maximum:
            raise ValueError(f"{self.name}: {value} outside {self.minimum}..{self.maximum}")
        return value

    def command_body(self, wire: int) -> bytes:
        """The three bytes after the command prefix's ``01``: id plus the encoded value."""
        if self.width == 2:
            return bytes([self.command_id, (wire >> 7) & 0x7F, wire & 0x7F])
        return bytes([self.command_id, 0x00, wire])

    def wire_from_body(self, body: bytes) -> int | None:
        """Decode a 3-byte command body for this parameter; None if malformed."""
        if len(body) != 3 or body[0] != self.command_id:
            return None
        if self.width == 2:
            return None if body[1] > 0x7F or body[2] > 0x7F else (body[1] << 7) | body[2]
        return body[2] if body[1] == 0x00 else None

    def dump_bytes(self, wire: int) -> bytes:
        return bytes([(wire >> 7) & 0x7F, wire & 0x7F]) if self.width == 2 else bytes([wire])

    def read_wire(self, payload: bytes) -> int:
        o = self.dump_offset
        return (payload[o] << 7) | payload[o + 1] if self.width == 2 else payload[o]

    def from_wire(self, wire: int) -> int:
        if self.kind is Kind.SWITCH:
            return 1 if wire == SWITCH_ON else 0
        return wire

    def is_valid_wire(self, wire: int) -> bool:
        if self.kind is Kind.SWITCH:
            return wire in (SWITCH_ON, SWITCH_OFF)
        return self.minimum <= wire <= self.maximum


# Amp model names are in THR10 index order; the order on THR5 is ASSUMED, not verified.
AMP_NAMES = ("clean", "crunch", "lead", "brit hi", "modern")

_PARAMS = (
    Parameter("amp", 0x00, 128, Kind.ENUM, 4, "MIC TYPE knob; also re-applies tone/cab on the amp"),
    Parameter("gain", 0x01, 129, Kind.LEVEL, note="BLEND knob on the THR5A case"),
    Parameter("master", 0x02, 130, Kind.LEVEL),
    Parameter("bass", 0x03, 131, Kind.LEVEL, note="TONE knob moves bass/middle/treble together"),
    Parameter("middle", 0x04, 132, Kind.LEVEL),
    Parameter("treble", 0x05, 133, Kind.LEVEL),
    Parameter(
        "modulation_type", 0x20, 160, Kind.ENUM, 3, "chorus/flanger/tremolo/phaser order assumed"
    ),
    Parameter("modulation", 0x2F, 175, Kind.SWITCH),
    Parameter(
        "delay_time",
        0x31,
        177,
        Kind.LEVEL,
        9999,
        "unit 0.1 ms (3000 = 300 ms); TAP/TIME sets it; range from the THR10 table, "
        "taps seen 3000-9000",
        minimum=1,
        width=2,
    ),
    Parameter("delay_feedback", 0x33, 179, Kind.LEVEL),
    Parameter("delay_level", 0x38, 184, Kind.LEVEL),
    Parameter("delay", 0x3F, 191, Kind.SWITCH),
    Parameter("reverb_type", 0x40, 192, Kind.ENUM, 3, "hall/room/plate/spring order assumed"),
    Parameter("reverb_level", 0x4B, 203, Kind.LEVEL),
    Parameter("reverb", 0x4F, 207, Kind.SWITCH),
    Parameter("gate", 0x5F, 223, Kind.SWITCH),
)

PARAMETERS: dict[str, Parameter] = {p.name: p for p in _PARAMS}
BY_COMMAND_ID: dict[int, Parameter] = {p.command_id: p for p in _PARAMS}


def build_set_command(name: str, value: int) -> bytes:
    """Build the SysEx that sets *name* to *value* (user units)."""
    param = PARAMETERS[name]
    return m.COMMAND_PREFIX + param.command_body(param.to_wire(value)) + bytes([m.SYSEX_END])


def decode_command(body: bytes) -> tuple[Parameter, int] | None:
    """Interpret a command body (after the command prefix, before F7) as (parameter, user value)."""
    param = BY_COMMAND_ID.get(body[0]) if body else None
    if param is None:
        return None
    wire = param.wire_from_body(body)
    if wire is None or not param.is_valid_wire(wire):
        return None
    return param, param.from_wire(wire)


def is_allowed_set_command(data: bytes) -> bool:
    """True if *data* is exactly a well-formed set command for a table parameter."""
    if len(data) != len(m.COMMAND_PREFIX) + 4 or data[: len(m.COMMAND_PREFIX)] != m.COMMAND_PREFIX:
        return False
    if data[-1] != m.SYSEX_END:
        return False
    return decode_command(data[len(m.COMMAND_PREFIX) : -1]) is not None


def decode_dump(payload: bytes) -> dict[str, int]:
    """Named values (user units) of every table parameter in a dump payload."""
    return {p.name: p.from_wire(p.read_wire(payload)) for p in _PARAMS}
