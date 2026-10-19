import pytest

from tests.fake_amp import FakeAmp, real_payload
from thr_control import cli
from thr_control.protocol import messages as m
from thr_control.protocol import thr_v2
from thr_control.protocol.safety import UnsafeMessageError, ensure_allowed_message
from thr_control.services.controller import DeviceError, ThrController


def test_known_command_bytes():
    # Same shape as amp-emitted events in tests/fixtures/thr5_tone_knob_events.txt
    assert (
        thr_v2.build_set_command("bass", 0x35).hex(" ").upper()
        == "F0 43 7D 10 41 30 01 03 00 35 F7"
    )
    assert thr_v2.build_set_command("amp", 4).hex(" ").upper() == "F0 43 7D 10 41 30 01 00 00 04 F7"
    assert thr_v2.build_set_command("reverb", 1)[-2] == 0x00  # on
    assert thr_v2.build_set_command("reverb", 0)[-2] == 0x7F  # off


@pytest.mark.parametrize(
    ("name", "value"),
    [("master", 101), ("master", -1), ("amp", 5), ("delay", 2), ("modulation_type", 4)],
)
def test_out_of_range_rejected(name, value):
    with pytest.raises(ValueError):
        thr_v2.build_set_command(name, value)


def test_table_offsets_and_ids_unique():
    assert len({p.command_id for p in thr_v2.PARAMETERS.values()}) == len(thr_v2.PARAMETERS)
    assert len({p.dump_offset for p in thr_v2.PARAMETERS.values()}) == len(thr_v2.PARAMETERS)


def test_decode_real_dump():
    vals = thr_v2.decode_dump(real_payload())
    assert (vals["amp"], vals["gain"], vals["master"]) == (2, 0x34, 0x33)
    assert vals["modulation"] in (0, 1)


def test_allowlist_rejects_unknown_and_malformed():
    good = thr_v2.build_set_command("master", 50)
    ensure_allowed_message(good)
    bad = [
        good[:-2] + b"\x65" + good[-1:],  # value 101
        m.COMMAND_PREFIX + bytes([0x32, 0x00, 0x10, 0xF7]),  # id not in table
        m.COMMAND_PREFIX + bytes([0x02, 0x01, 0x10, 0xF7]),  # middle byte must be 00
        m.COMMAND_PREFIX + bytes([0x02, 0x00, 0x10, 0x10, 0xF7]),  # 4-byte body
        m.COMMAND_PREFIX + bytes([0x2F, 0x00, 0x10, 0xF7]),  # switch needs 00/7F
        bytes.fromhex("F0 43 7D 50 44 54 41 31 52 4F 4D 52 02 F7"),  # DTA1ROMR
        bytes.fromhex("F0 43 7D 30 41 30 00 00 F7"),  # system command (wide/lamp): not allowed
    ]
    for data in bad:
        with pytest.raises(UnsafeMessageError):
            ensure_allowed_message(data)


def test_controller_set_and_readback():
    amp = FakeAmp(real_payload())
    ctl = ThrController(amp, settle=0)
    result = ctl.set_parameter("master", 77)
    assert result.ok and result.confirmed == 77
    assert ctl.set_parameter("delay", 1).ok
    assert ctl.read_settings()["delay"] == 1
    assert ctl.set_parameter("amp", 4).ok


def test_controller_detects_mismatch():
    amp = FakeAmp(real_payload())
    amp.ignore_sets = True
    result = ThrController(amp, settle=0).set_parameter("gain", 10)
    assert not result.ok


def test_controller_no_reply():
    class Silent:
        def send(self, data):
            pass

        def wait_for(self, accept, timeout):
            return None

    with pytest.raises(DeviceError):
        ThrController(Silent(), timeout=0.01).read_dump()


def test_controller_unknown_parameter():
    with pytest.raises(KeyError):
        ThrController(FakeAmp(), settle=0).set_parameter("compressor_type", 1)


def test_cli_set_dry_run_and_validation(capsys):
    assert cli.main(["set", "master", "40"]) == 0
    out = capsys.readouterr().out
    assert "F0 43 7D 10 41 30 01 02 00 28 F7" in out and "Dry run" in out
    assert cli.main(["set", "master", "400"]) == 1
    assert cli.main(["set", "nope", "1"]) == 1
    assert cli.main(["set", "amp", "lead"]) == 0
    assert cli.main(["params"]) == 0


# -- delay time (14-bit, unit 0.1 ms) ------------------------------------------
# Real amp events captured while tapping TAP/TIME (logs/tap_delay.log); gaps between the
# messages' arrival were ~0.30 s, 0.31 s, 0.36 s, 0.34 s, 0.53 s.
REAL_TAP_EVENTS = [
    ("F0 43 7D 10 41 30 01 31 17 38 F7", 3000),
    ("F0 43 7D 10 41 30 01 31 17 37 F7", 2999),
    ("F0 43 7D 10 41 30 01 31 1C 0F F7", 3599),
    ("F0 43 7D 10 41 30 01 31 1A 47 F7", 3399),
    ("F0 43 7D 10 41 30 01 31 29 33 F7", 5299),
]


@pytest.mark.parametrize(("hexstr", "value"), REAL_TAP_EVENTS)
def test_real_tap_events_decode_and_roundtrip(hexstr, value):
    from thr_control.protocol.parser import ParameterCommand, parse

    data = bytes.fromhex(hexstr)
    msg = parse(data)
    assert isinstance(msg, ParameterCommand)
    param, decoded = thr_v2.decode_command(msg.body)
    assert (param.name, decoded) == ("delay_time", value)
    assert thr_v2.build_set_command("delay_time", value) == data  # we send what the amp sends
    ensure_allowed_message(data)


def test_delay_time_range_and_dump_decode():
    for bad in (0, 10000, -5):
        with pytest.raises(ValueError):
            thr_v2.build_set_command("delay_time", bad)
    thr_v2.build_set_command("delay_time", 1)
    thr_v2.build_set_command("delay_time", 9999)
    # a 14-bit value above the maximum on the wire is refused by the allowlist
    over = m.COMMAND_PREFIX + bytes([0x31, 0x7F, 0x7F, 0xF7])
    with pytest.raises(UnsafeMessageError):
        ensure_allowed_message(over)
    payload = bytearray(real_payload())
    payload[177:179] = bytes([70, 40])  # the dump read after the taps in the hardware test
    assert thr_v2.decode_dump(bytes(payload))["delay_time"] == 9000


def test_controller_delay_time_readback():
    amp = FakeAmp(real_payload())
    ctl = ThrController(amp, settle=0)
    result = ctl.set_parameter("delay_time", 4000)
    assert result.ok and ctl.read_settings()["delay_time"] == 4000
    amp.inject_event("delay_time", 1234)
    assert ctl.read_settings()["delay_time"] == 1234


def test_cli_delay_time_ms_suffix(capsys):
    assert cli.main(["set", "delay_time", "400ms"]) == 0
    assert "F0 43 7D 10 41 30 01 31 1F 20 F7" in capsys.readouterr().out  # 4000 = 0x1F20
    assert cli.main(["set", "delay_time", "5000ms"]) == 1  # beyond 999.9 ms


def test_gate_and_compressor_parameters_verified_on_hardware():
    # Offsets/ids checked on a THR5A: each write changed exactly this one dump byte.
    expected = {
        "gate_threshold": (0x51, 209),
        "gate_release": (0x52, 210),
        "compressor": (0x1F, 159),
        "compressor_sustain": (0x11, 145),
        "compressor_output": (0x12, 146),
    }
    for name, (cid, off) in expected.items():
        p = thr_v2.PARAMETERS[name]
        assert (p.command_id, p.dump_offset) == (cid, off)
    assert thr_v2.build_set_command("compressor", 1)[-2] == 0x00
    assert thr_v2.build_set_command("gate_threshold", 30).hex(" ").upper() == (
        "F0 43 7D 10 41 30 01 51 00 1E F7"
    )
    amp = FakeAmp(real_payload())
    ctl = ThrController(amp, settle=0)
    for name, value in [("gate_threshold", 30), ("compressor_sustain", 70), ("compressor", 1)]:
        assert ctl.set_parameter(name, value).ok
    assert ctl.read_settings()["compressor_output"] == 0x32  # untouched neighbour


# -- cab and modulation parameters (verified on a THR5A) --------------------------------
def test_cab_and_modulation_parameters_table():
    p = thr_v2.PARAMETERS
    assert (p["cab"].command_id, p["cab"].dump_offset, p["cab"].maximum) == (0x06, 134, 5)
    for i in range(1, 6):
        q = p[f"modulation_p{i}"]
        assert (q.command_id, q.dump_offset) == (0x20 + i, 160 + i)
    assert thr_v2.build_set_command("cab", 3).hex(" ").upper() == "F0 43 7D 10 41 30 01 06 00 03 F7"
    with pytest.raises(ValueError):
        thr_v2.build_set_command("cab", 6)  # "none" on the THR10: not tested on a THR5
    assert set(thr_v2.MODULATION_LABELS) == {0, 1, 2, 3}
    assert len(thr_v2.MODULATION_TYPES) == 4 and len(thr_v2.CAB_NAMES) == 6


def test_controller_cab_and_modulation_roundtrip():
    amp = FakeAmp(real_payload())
    ctl = ThrController(amp, settle=0)
    for name, value in [
        ("cab", 4),
        ("modulation_type", 2),
        ("modulation_p1", 77),
        ("modulation_p5", 12),
    ]:
        assert ctl.set_parameter(name, value).ok
    s = ctl.read_settings()
    assert (s["cab"], s["modulation_type"], s["modulation_p1"], s["modulation_p5"]) == (
        4,
        2,
        77,
        12,
    )
