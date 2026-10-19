import pytest

from thr_control.protocol.safety import (
    FORBIDDEN_COMMANDS,
    UnsafeMessageError,
    contains_forbidden_command,
    ensure_safe_to_send,
)


@pytest.mark.parametrize("cmd", FORBIDDEN_COMMANDS)
def test_forbidden_commands_blocked(cmd):
    msg = [0xF0, 0x43, *cmd, 0xF7]
    assert contains_forbidden_command(msg)
    with pytest.raises(UnsafeMessageError):
        ensure_safe_to_send(msg)


def test_all_three_named_commands_present():
    assert set(FORBIDDEN_COMMANDS) == {b"DTA1ERASE", b"DTA1MAIN", b"DTA1ROMR"}


def test_harmless_message_allowed():
    ensure_safe_to_send([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])
