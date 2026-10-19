"""Write-safety guard.

Firmware update, erase and bootloader traffic must never be sent by this
application. Every outgoing message must pass a check here before it reaches
a MIDI transport.

Layers:
  * :func:`ensure_safe_to_send` -- denylist of known bootloader commands.
  * :func:`ensure_read_only_request` -- allowlist: only the exact settings request.
  * :func:`ensure_allowed_message` -- the transport's gate: settings request, or a
    set command for a parameter in ``thr_v2`` with a valid value. Nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import messages, thr_v2

# Bootloader command names identified during research. Matched as ASCII
# inside SysEx payloads.
FORBIDDEN_COMMANDS: tuple[bytes, ...] = (b"DTA1ERASE", b"DTA1MAIN", b"DTA1ROMR")


class UnsafeMessageError(Exception):
    """Raised when an outgoing message must not be transmitted."""


def contains_forbidden_command(data: Sequence[int]) -> bool:
    """Return True if *data* embeds any forbidden bootloader command."""
    raw = bytes(b & 0xFF for b in data)
    return any(cmd in raw for cmd in FORBIDDEN_COMMANDS)


def ensure_safe_to_send(data: Sequence[int]) -> None:
    """Raise :class:`UnsafeMessageError` if *data* contains a forbidden command."""
    if contains_forbidden_command(data):
        raise UnsafeMessageError("refusing to send firmware/bootloader command")


_ALLOWED_REQUESTS = frozenset({messages.build_settings_request()})


def ensure_read_only_request(data: Sequence[int]) -> None:
    """Allow only a known settings request; reject everything else."""
    ensure_safe_to_send(data)
    if bytes(data) not in _ALLOWED_REQUESTS:
        raise UnsafeMessageError("message is not on the read-only request allowlist")


def ensure_allowed_message(data: Sequence[int]) -> None:
    """Allow only the settings request or a table-validated parameter set command."""
    ensure_safe_to_send(data)
    raw = bytes(data)
    if raw in _ALLOWED_REQUESTS or thr_v2.is_allowed_set_command(raw):
        return
    raise UnsafeMessageError("message is not on the allowlist (request or known parameter set)")
