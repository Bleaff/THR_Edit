"""Known THR SysEx framing, constants and message builders.

Sources (see docs/protocol.md for verification status of each item):
  * sysex_tones (AGPL-3.0) -- protocol *facts* only; no code is copied.
  * THR_Footswitch -- dump header and checksum.
  * Observed THR5 heartbeat (tests/fixtures/thr5_idle_heartbeat.txt).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum

SYSEX_START = 0xF0
SYSEX_END = 0xF7
YAMAHA_ID = 0x43
THR_DEVICE_ID = 0x7D

# Message-type byte following F0 43 7D.
TYPE_DUMP = 0x00
TYPE_COMMAND = 0x10
TYPE_REQUEST = 0x20
TYPE_SYSTEM = 0x30
TYPE_HEARTBEAT = 0x60

_DTA = b"DTA"  # 44 54 41
_ALLP = b"AllP"  # 41 6C 6C 50

PREFIX = bytes([SYSEX_START, YAMAHA_ID, THR_DEVICE_ID])

# Fixed 18-byte header of a full-settings dump (sysex_tones, THR_Footswitch).
DUMP_HEADER = (
    PREFIX + bytes([TYPE_DUMP, 0x02, 0x0C]) + _DTA + b"1" + _ALLP + bytes([0x00, 0x00, 0x7F, 0x7F])
)
DUMP_PAYLOAD_SIZE = 256
DUMP_SIZE = len(DUMP_HEADER) + DUMP_PAYLOAD_SIZE + 2  # + checksum + F7 == 276
DUMP_CHECKSUM_START = 6  # checksum covers bytes [6 : -2]

# Prefix of system-type messages (``F0 43 7D 30 41 30 <a> <b> F7``).
SYSTEM_PREFIX = PREFIX + bytes([TYPE_SYSTEM, 0x41, 0x30])

# Prefix of a single-parameter change message sent by the amp / editor.
COMMAND_PREFIX = PREFIX + bytes([TYPE_COMMAND, 0x41, 0x30, 0x01])


class ThrModel(IntEnum):
    """Model byte used in heartbeats and settings requests."""

    THR5 = 0x30
    THR10 = 0x31
    THR10X = 0x32
    THR10C = 0x33
    THR5A = 0x34


def checksum(data: Sequence[int]) -> int:
    """Yamaha 7-bit two's-complement checksum."""
    return ((~sum(data)) + 1) & 0x7F


def build_settings_request(model: ThrModel | None = None) -> bytes:
    """Request a dump of the current settings ("AllP").

    VERIFIED on a THR5 (THR5A with V2 firmware): the amp answers with a
    276-byte dump. The byte after ``DTA`` is the constant ``0x31`` ("DTA1"),
    not the model byte: the model-byte form (``0x30``) gets no reply.
    *model* is accepted for API symmetry and ignored.
    """
    return PREFIX + bytes([TYPE_REQUEST]) + _DTA + b"1" + _ALLP + bytes([SYSEX_END])


def build_heartbeat(model: ThrModel) -> bytes:
    """The amp's periodic keep-alive (what the amp sends; used for test data)."""
    return PREFIX + bytes([TYPE_HEARTBEAT]) + _DTA + bytes([model, SYSEX_END])
