"""Discovery of MIDI ports and Yamaha THR amplifiers.

Port names and numbers are dynamic under ALSA, so devices are identified by
name at runtime. Listing ports only queries the system; it opens nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# "THR5 MIDI 1", "THR10C MIDI 1", "THR5:THR5 MIDI 1 24:0", ...
_THR_RE = re.compile(r"\bTHR(5A|10C|10X|10|5)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DetectedDevice:
    """A supported THR amplifier found among the MIDI ports."""

    model: str
    input_port: str | None
    output_port: str | None


def identify_model(port_name: str) -> str | None:
    """Return the THR model (e.g. ``"THR5"``) for a port name, or None."""
    match = _THR_RE.search(port_name)
    return f"THR{match.group(1).upper()}" if match else None


def detect_devices(input_names: Iterable[str], output_names: Iterable[str]) -> list[DetectedDevice]:
    """Group matching input/output ports into one device per model."""
    ins: dict[str, str] = {}
    outs: dict[str, str] = {}
    for name in input_names:
        if (model := identify_model(name)) and model not in ins:
            ins[model] = name
    for name in output_names:
        if (model := identify_model(name)) and model not in outs:
            outs[model] = name
    return [DetectedDevice(m, ins.get(m), outs.get(m)) for m in sorted(ins.keys() | outs.keys())]


def list_input_ports() -> list[str]:
    import mido

    return list(mido.get_input_names())


def list_output_ports() -> list[str]:
    import mido

    return list(mido.get_output_names())
