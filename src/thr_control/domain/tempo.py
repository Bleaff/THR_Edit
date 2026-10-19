"""Tempo-synced delay: note lengths to the amp's delay-time unit (0.1 ms)."""

from __future__ import annotations

from ..protocol.thr_v2 import PARAMETERS

# Length of each division in quarter-note beats.
DIVISIONS: dict[str, float] = {
    "1/2": 2.0,
    "dotted 1/4": 1.5,
    "1/4": 1.0,
    "dotted 1/8": 0.75,
    "1/8": 0.5,
    "1/8 triplet": 1 / 3,
    "1/16": 0.25,
}
MIN_BPM = 20.0
MAX_BPM = 300.0


def note_ms(bpm: float, division: str) -> float:
    """Length of *division* at *bpm*, in milliseconds."""
    if division not in DIVISIONS:
        raise ValueError(f"unknown division {division!r}")
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"tempo must be {MIN_BPM:g}-{MAX_BPM:g} BPM")
    return 60000.0 / bpm * DIVISIONS[division]


def delay_value(bpm: float, division: str) -> int:
    """The ``delay_time`` value (0.1 ms units) for *division* at *bpm*.

    Raises ValueError if the result is outside what the amp accepts.
    """
    ms = note_ms(bpm, division)
    value = round(ms * 10)
    p = PARAMETERS["delay_time"]
    if not p.minimum <= value <= p.maximum:
        raise ValueError(
            f"{division} at {bpm:g} BPM is {ms:.1f} ms; the amp allows "
            f"{p.minimum / 10:g}-{p.maximum / 10:g} ms"
        )
    return value


def bpm_for(value: int, division: str) -> float:
    """The tempo at which *division* equals the delay time *value* (0.1 ms units)."""
    if value <= 0:
        raise ValueError("delay time must be positive")
    return 60000.0 * DIVISIONS[division] / (value / 10)


_ALIASES = {
    "1/8t": "1/8 triplet",
    "1/8 t": "1/8 triplet",
    "d1/4": "dotted 1/4",
    "d1/8": "dotted 1/8",
}


def parse_division(text: str) -> str:
    """Accept ``dotted-1/8``, ``dotted_1/8``, ``1/8T`` and the canonical names."""
    key = " ".join(text.lower().replace("-", " ").replace("_", " ").split())
    key = _ALIASES.get(key, key)
    if key not in DIVISIONS:
        raise ValueError(f"unknown division {text!r}; choose from: {', '.join(DIVISIONS)}")
    return key
