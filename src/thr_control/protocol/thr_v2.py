"""THR5 (V2 firmware) parameter table.

Every entry below was verified on a real THR5A running THR5 V2 firmware, either because
its command id appeared in the amp's own events and its dump offset moved in the knob map
(tests/fixtures/thr5a_knob_map.json), or because writing it changed exactly that one dump
byte and restored cleanly (delay time, gate threshold/release, compressor; see
docs/protocol.md).

Parameters not listed here are NOT writable through this application.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    # (type parameter name, types it applies to). Some command ids mean different things per
    # type, so a value is only meaningful for the types listed here.
    applies_when: tuple[str, tuple[int, ...]] | None = None

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

# Cabinet names follow the THR10 index order and are ASSUMED for the THR5 (values 0-5 were all
# accepted on a THR5A; 6 = "none" on the THR10 was deliberately not tested).
CAB_NAMES = ("us 4x12", "us 2x12", "brit 4x12", "brit 2x12", "1x12", "4x10")

# Modulation types and the labels of their parameters follow the THR10 table and are ASSUMED
# for the THR5. Verified on a THR5A: types 0-3 are accepted, each loads its own defaults, and
# parameters p1-p5 (ids 21-25) each write their own byte for every type.
MODULATION_TYPES = ("chorus", "flanger", "tremolo", "phaser")
MODULATION_LABELS: dict[int, tuple[str, ...]] = {
    0: ("Speed", "Depth", "Mix"),
    1: ("Speed", "Manual", "Depth", "Feedback", "Spread"),
    2: ("Freq", "Depth"),
    3: ("Speed", "Manual", "Depth", "Feedback"),
}

_FULL = ("reverb_type", (0, 1, 2))
_SPRING = ("reverb_type", (3,))

_PARAMS = (
    Parameter("amp", 0x00, 128, Kind.ENUM, 4, "MIC TYPE knob; also re-applies tone/cab on the amp"),
    Parameter("cab", 0x06, 134, Kind.ENUM, 5, "the amp picks its own cab when the model changes"),
    Parameter("gain", 0x01, 129, Kind.LEVEL, note="BLEND knob on the THR5A case"),
    Parameter("master", 0x02, 130, Kind.LEVEL),
    Parameter("bass", 0x03, 131, Kind.LEVEL, note="TONE knob moves bass/middle/treble together"),
    Parameter("middle", 0x04, 132, Kind.LEVEL),
    Parameter("treble", 0x05, 133, Kind.LEVEL),
    Parameter(
        "modulation_type", 0x20, 160, Kind.ENUM, 3, "chorus/flanger/tremolo/phaser order assumed"
    ),
    *(
        Parameter(
            f"modulation_p{i}",
            0x20 + i,
            160 + i,
            Kind.LEVEL,
            note="meaning depends on modulation_type; switching type resets p1-p5 to defaults",
        )
        for i in range(1, 6)
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
    Parameter(
        "delay_high_cut", 0x34, 180, Kind.LEVEL, 16001, "Hz (assumed; original 4000)", 1000, 2
    ),
    Parameter("delay_low_cut", 0x36, 182, Kind.LEVEL, 8000, "Hz (assumed; original 21)", 21, 2),
    Parameter("delay_level", 0x38, 184, Kind.LEVEL),
    Parameter("delay", 0x3F, 191, Kind.SWITCH),
    Parameter("reverb_type", 0x40, 192, Kind.ENUM, 3, "hall/room/plate/spring order assumed"),
    Parameter("reverb_level", 0x4B, 203, Kind.LEVEL),
    # Hall / room / plate (reverb_type 0-2): 14-bit values, units unverified.
    Parameter("reverb_time", 0x41, 193, Kind.LEVEL, 200, "raw units", 3, 2, _FULL),
    Parameter("reverb_pre", 0x43, 195, Kind.LEVEL, 2000, "raw units", 1, 2, _FULL),
    Parameter("reverb_low_cut", 0x45, 197, Kind.LEVEL, 8000, "Hz (assumed)", 21, 2, _FULL),
    Parameter("reverb_high_cut", 0x47, 199, Kind.LEVEL, 16001, "Hz (assumed)", 1000, 2, _FULL),
    Parameter("reverb_high_ratio", 0x49, 201, Kind.LEVEL, 10, "", 1, 1, _FULL),
    Parameter("reverb_low_ratio", 0x4A, 202, Kind.LEVEL, 14, "", 0, 1, _FULL),
    # Spring (reverb_type 3): id 0x41 is the same wire message as reverb_time but lands in a
    # different dump byte, so the two must never be mixed up.
    Parameter("reverb_spring_reverb", 0x41, 193, Kind.LEVEL, 100, "", 0, 1, _SPRING),
    Parameter("reverb_spring_filter", 0x42, 194, Kind.LEVEL, 100, "", 0, 1, _SPRING),
    Parameter("reverb", 0x4F, 207, Kind.SWITCH),
    Parameter("gate", 0x5F, 223, Kind.SWITCH, note="some amp models switch it on themselves"),
    Parameter("gate_threshold", 0x51, 209, Kind.LEVEL),
    Parameter("gate_release", 0x52, 210, Kind.LEVEL),
    Parameter("compressor", 0x1F, 159, Kind.SWITCH),
    Parameter(
        "compressor_sustain", 0x11, 145, Kind.LEVEL, note="stomp-type compressor (type 0) only"
    ),
    Parameter(
        "compressor_output", 0x12, 146, Kind.LEVEL, note="stomp-type compressor (type 0) only"
    ),
)

PARAMETERS: dict[str, Parameter] = {p.name: p for p in _PARAMS}
PARAMS_BY_ID: dict[int, list[Parameter]] = {}
for _p in _PARAMS:
    PARAMS_BY_ID.setdefault(_p.command_id, []).append(_p)


def applies(param: Parameter, settings: Mapping[str, int] | None) -> bool:
    """True if *param* is meaningful given *settings* (its type must be known and match)."""
    if param.applies_when is None:
        return True
    if settings is None:
        return True  # no context: cannot tell, so do not exclude
    type_name, types = param.applies_when
    return settings.get(type_name) in types


def filter_applicable(settings: Mapping[str, int]) -> dict[str, int]:
    """Drop type-dependent values whose own type is missing or does not match."""
    return {
        k: v
        for k, v in settings.items()
        if k not in PARAMETERS or _applies_strict(PARAMETERS[k], settings)
    }


def _applies_strict(param: Parameter, settings: Mapping[str, int]) -> bool:
    return (
        param.applies_when is None or settings.get(param.applies_when[0]) in param.applies_when[1]
    )


def build_set_command(name: str, value: int) -> bytes:
    """Build the SysEx that sets *name* to *value* (user units)."""
    param = PARAMETERS[name]
    return m.COMMAND_PREFIX + param.command_body(param.to_wire(value)) + bytes([m.SYSEX_END])


def decode_command(
    body: bytes, context: Mapping[str, int] | None = None
) -> tuple[Parameter, int] | None:
    """Interpret a command body (after the command prefix, before F7) as (parameter, user value).

    Some ids are shared by several parameters; *context* (the last known settings, which
    include the type parameters) picks the one that applies.
    """
    candidates = PARAMS_BY_ID.get(body[0], []) if body else []
    matches = []
    for param in candidates:
        wire = param.wire_from_body(body)
        if wire is not None and param.is_valid_wire(wire):
            matches.append((param, param.from_wire(wire)))
    if not matches:
        return None
    for param, value in matches:
        if applies(param, context):
            return param, value
    return None


def is_allowed_set_command(data: bytes) -> bool:
    """True if *data* is exactly a well-formed set command for a table parameter."""
    if len(data) != len(m.COMMAND_PREFIX) + 4 or data[: len(m.COMMAND_PREFIX)] != m.COMMAND_PREFIX:
        return False
    if data[-1] != m.SYSEX_END:
        return False
    return decode_command(data[len(m.COMMAND_PREFIX) : -1]) is not None


def decode_dump(payload: bytes) -> dict[str, int]:
    """Named values (user units) of every table parameter that applies to the dump's own types."""
    values = {p.name: p.from_wire(p.read_wire(payload)) for p in _PARAMS}
    return {p.name: values[p.name] for p in _PARAMS if applies(p, values)}
