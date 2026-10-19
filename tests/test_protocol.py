from pathlib import Path

import pytest

from thr_control.protocol import messages as m
from thr_control.protocol.parser import Heartbeat, ParameterCommand, SettingsDump, Unknown, parse
from thr_control.protocol.safety import (
    UnsafeMessageError,
    ensure_read_only_request,
    ensure_safe_to_send,
)

FIXTURES = Path(__file__).parent / "fixtures"


def synthetic_dump(name: str = "Test Preset") -> bytes:
    """SYNTHETIC dump built from the documented layout (not captured from hardware)."""
    payload = bytearray(m.DUMP_PAYLOAD_SIZE)
    payload[: len(name)] = name.encode()
    body = bytes(m.DUMP_HEADER[m.DUMP_CHECKSUM_START :]) + bytes(payload)
    return m.DUMP_HEADER + bytes(payload) + bytes([m.checksum(body), m.SYSEX_END])


def captured(name: str) -> bytes:
    lines = [ln for ln in (FIXTURES / name).read_text().splitlines() if not ln.startswith("#")]
    return bytes.fromhex(" ".join(lines))


def test_captured_thr5_heartbeat():
    msg = parse(captured("thr5_idle_heartbeat.txt"))
    assert msg == Heartbeat(m.ThrModel.THR5, 0x30)
    assert m.build_heartbeat(m.ThrModel.THR5) == captured("thr5_idle_heartbeat.txt")


def test_unknown_heartbeat_model():
    msg = parse(bytes.fromhex("F0 43 7D 60 44 54 41 7F F7"))
    assert msg == Heartbeat(None, 0x7F)


def test_dump_constants():
    assert len(m.DUMP_HEADER) == 18
    assert m.DUMP_SIZE == 276


def test_footswitch_prefix_checksum():
    # THR_Footswitch hardcodes a running sum of 0x71 over the header after F0 43 7D 00 02 0C.
    assert sum(m.DUMP_HEADER[m.DUMP_CHECKSUM_START :]) & 0xFF == 0x71


def test_parse_synthetic_dump():
    msg = parse(synthetic_dump())
    assert isinstance(msg, SettingsDump)
    assert msg.checksum_ok and msg.name == "Test Preset" and len(msg.payload) == 256


def test_dump_bad_checksum():
    raw = bytearray(synthetic_dump())
    raw[-2] ^= 0x01
    msg = parse(bytes(raw))
    assert isinstance(msg, SettingsDump) and not msg.checksum_ok


def test_dump_wrong_size_is_unknown():
    assert isinstance(parse(synthetic_dump()[:-5] + b"\xf7"), Unknown)


def test_parameter_command():
    msg = parse(m.COMMAND_PREFIX + bytes([0x01, 0x00, 0x32, m.SYSEX_END]))
    assert msg == ParameterCommand(bytes([0x01, 0x00, 0x32]))


@pytest.mark.parametrize("data", [b"", b"\xf0\xf7", b"\x90\x3c\x40", b"\xf0\x41\x00\x00\x00\xf7"])
def test_garbage_is_unknown(data):
    assert isinstance(parse(data), Unknown)


def test_settings_request_bytes():
    # Verified on a THR5: model-independent, "DTA1" + "AllP".
    expected = "F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7"
    assert m.build_settings_request().hex(" ").upper() == expected
    assert m.build_settings_request(m.ThrModel.THR5) == m.build_settings_request()


def test_allowlist_accepts_only_requests():
    ensure_read_only_request(m.build_settings_request())
    with pytest.raises(UnsafeMessageError):
        ensure_read_only_request(bytes.fromhex("F0 43 7D 20 44 54 41 30 41 6C 6C 50 F7"))
    for bad in (synthetic_dump(), m.build_heartbeat(m.ThrModel.THR5), b"\xf0\x43\x7d\x10\xf7"):
        with pytest.raises(UnsafeMessageError):
            ensure_read_only_request(bad)


def test_bootloader_dump_command_blocked_even_if_framed_like_reference():
    # DTA1ROMR command from the thr10 firmware README.
    rom = bytes.fromhex("F0 43 7D 50 44 54 41 31 52 4F 4D 52 02 F7")
    with pytest.raises(UnsafeMessageError):
        ensure_safe_to_send(rom)
    with pytest.raises(UnsafeMessageError):
        ensure_read_only_request(rom)


def test_normal_dump_header_is_not_flagged_as_forbidden():
    # Real preset dumps contain "DTA1AllP"; that must not trip the denylist.
    ensure_safe_to_send(synthetic_dump())


def test_real_thr5_dump_fixture():
    msg = parse(captured("thr5_dump_baseline.txt"))
    assert isinstance(msg, SettingsDump)
    assert msg.checksum_ok
    # Layout assumption (THR10 offsets); update once confirmed against known knob positions.
    assert msg.control_values() == {
        "amp": 2,
        "gain": 0x34,
        "master": 0x33,
        "bass": 0x3B,
        "middle": 0x32,
        "treble": 0x3E,
        "cab": 2,
    }


def test_post_request_system_message_is_a_system_message_with_unknown_meaning():
    from thr_control.protocol.parser import SystemMessage

    msg = parse(captured("thr5_post_request_system.txt"))
    assert isinstance(msg, SystemMessage) and msg.body == b"\x02\x02"


def test_real_tone_knob_events():
    lines = [ln for ln in (FIXTURES / "thr5_tone_knob_events.txt").read_text().splitlines()]
    msgs = [parse(bytes.fromhex(ln)) for ln in lines if not ln.startswith("#")]
    assert len(msgs) == 9
    pairs = [x.single_value for x in msgs if isinstance(x, ParameterCommand)]
    assert len(pairs) == 9
    assert [p[0] for p in pairs[:3]] == [3, 4, 5]  # bass, middle, treble slots (THR10 ids)
    assert all(0 <= v <= 100 for _, v in pairs)


def test_system_messages_parse_but_have_no_known_meaning():
    from thr_control.protocol.parser import SystemMessage, describe

    lines = (FIXTURES / "thr5_system_messages_gui_session.txt").read_text().splitlines()
    msgs = [parse(bytes.fromhex(ln)) for ln in lines if not ln.startswith("#")]
    assert msgs == [SystemMessage(b"\x00\x01"), SystemMessage(b"\x00\x00")]
    assert "meaning unknown" in describe(msgs[0])
