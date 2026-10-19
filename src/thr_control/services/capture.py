"""Guided, read-only mapping of physical knobs to settings-dump offsets.

The user moves one knob at a time; after each step we request a dump and
report which payload bytes changed. Nothing here writes settings to the amp.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TextIO

from ..protocol.parser import SettingsDump

# Knobs/controls printed on the THR5A case (knob_pos.jpg), top to bottom.
THR5A_KNOBS: tuple[str, ...] = (
    "VOLUME",
    "DLY/REV",
    "EFFECT",
    "TONE",
    "MASTER",
    "BLEND",
    "MIC TYPE",
)

Change = tuple[int, int, int]  # (payload offset, old, new)


def diff_payloads(a: bytes, b: bytes) -> list[Change]:
    return [(i, x, y) for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]


def format_changes(changes: Sequence[Change]) -> str:
    if not changes:
        return "no change"
    return ", ".join(f"[{i}] {x}->{y}" for i, x, y in changes)


def run_mapping(
    fetch: Callable[[], SettingsDump | None],
    ask: Callable[[str], str],
    out: TextIO,
    knobs: Sequence[str] = THR5A_KNOBS,
) -> dict[str, dict[str, list[Change]]]:
    """Walk through *knobs*; return {knob: {"min"/"max": changes vs the previous dump}}."""
    results: dict[str, dict[str, list[Change]]] = {}
    prev = fetch()
    if prev is None:
        print("error: no dump received for the starting state", file=out)
        return results
    print(f"Start state captured (checksum {'OK' if prev.checksum_ok else 'BAD'}).", file=out)
    for knob in knobs:
        results[knob] = {}
        for label, where in (
            ("min", "fully counter-clockwise (minimum)"),
            ("max", "fully clockwise (maximum)"),
        ):
            reply = ask(f"Turn {knob} {where}, then press Enter (or type 's' to skip this knob): ")
            if reply.strip().lower() == "s":
                break
            cur = fetch()
            if cur is None:
                print("  no dump received; skipping", file=out)
                continue
            changes = diff_payloads(prev.payload, cur.payload)
            results[knob][label] = changes
            print(f"  {knob} {label}: {format_changes(changes)}", file=out)
            prev = cur
    return results
