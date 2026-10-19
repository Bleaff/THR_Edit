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


def _disjoint(a, b):
    """True if two parameters can never both apply (different value sets of the same type)."""
    if a.applies_when is None or b.applies_when is None:
        return False
    return a.applies_when[0] == b.applies_when[0] and not set(a.applies_when[1]) & set(
        b.applies_when[1]
    )


def test_table_ids_and_dump_bytes_only_shared_between_disjoint_types():
    params = list(thr_v2.PARAMETERS.values())
    for i, a in enumerate(params):
        for b in params[i + 1 :]:
            span_a = range(a.dump_offset, a.dump_offset + a.width)
            span_b = range(b.dump_offset, b.dump_offset + b.width)
            clash = a.command_id == b.command_id or set(span_a) & set(span_b)
            assert not clash or _disjoint(a, b), (a.name, b.name)


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


# -- delay cuts and type-dependent reverb parameters (verified on a THR5A) ----------------
def test_delay_cut_and_reverb_table_entries():
    p = thr_v2.PARAMETERS
    expected = {
        "delay_high_cut": (0x34, 180, 2),
        "delay_low_cut": (0x36, 182, 2),
        "reverb_time": (0x41, 193, 2),
        "reverb_pre": (0x43, 195, 2),
        "reverb_low_cut": (0x45, 197, 2),
        "reverb_high_cut": (0x47, 199, 2),
        "reverb_high_ratio": (0x49, 201, 1),
        "reverb_low_ratio": (0x4A, 202, 1),
        "reverb_spring_reverb": (0x41, 193, 1),
        "reverb_spring_filter": (0x42, 194, 1),
    }
    for name, (cid, off, width) in expected.items():
        assert (p[name].command_id, p[name].dump_offset, p[name].width) == (cid, off, width)
    # real values read from the amp: delay cuts 4000 / 21 Hz, reverb low ratio 0
    assert p["reverb_low_ratio"].is_valid_wire(0) and p["delay_low_cut"].is_valid_wire(21)
    assert thr_v2.build_set_command("delay_high_cut", 8000).hex(" ").upper() == (
        "F0 43 7D 10 41 30 01 34 3E 40 F7"
    )  # bytes the amp itself reported for 8000


def test_shared_id_0x41_is_resolved_by_reverb_type():
    body = bytes([0x41, 0x00, 0x28])  # the same wire message either way
    hall = thr_v2.decode_command(body, {"reverb_type": 0})
    spring = thr_v2.decode_command(body, {"reverb_type": 3})
    assert (hall[0].name, hall[1]) == ("reverb_time", 40)
    assert (spring[0].name, spring[1]) == ("reverb_spring_reverb", 40)
    assert thr_v2.decode_command(body, {"amp": 1}) is None  # type unknown: do not guess
    assert thr_v2.decode_command(body) is not None  # allowlist check has no context
    ensure_allowed_message(m.COMMAND_PREFIX + body + b"\xf7")
    assert thr_v2.decode_command(bytes([0x42, 0x00, 0x05]), {"reverb_type": 0}) is None


def test_dump_decode_only_returns_parameters_for_the_active_reverb_type():
    payload = bytearray(real_payload())
    payload[192] = 0
    hall = thr_v2.decode_dump(bytes(payload))
    assert "reverb_time" in hall and "reverb_spring_reverb" not in hall
    payload[192] = 3
    spring = thr_v2.decode_dump(bytes(payload))
    assert "reverb_spring_reverb" in spring and "reverb_time" not in spring


def test_filter_applicable_drops_values_for_other_or_unknown_types():
    kept = thr_v2.filter_applicable(
        {"reverb_type": 0, "reverb_time": 30, "reverb_spring_filter": 50, "gain": 5}
    )
    assert kept == {"reverb_type": 0, "reverb_time": 30, "gain": 5}
    assert thr_v2.filter_applicable({"reverb_time": 30, "gain": 5}) == {"gain": 5}  # no type
    assert "reverb_spring_filter" in thr_v2.filter_applicable(
        {"reverb_type": 3, "reverb_spring_filter": 50}
    )


def test_controller_roundtrip_for_hall_and_spring_reverb():
    amp = FakeAmp(real_payload())
    ctl = ThrController(amp, settle=0)
    ctl.set_parameter("reverb_type", 0)
    for name, v in [
        ("reverb_time", 150),
        ("reverb_pre", 900),
        ("reverb_high_cut", 8000),
        ("reverb_low_ratio", 0),
        ("delay_low_cut", 200),
    ]:
        assert ctl.set_parameter(name, v).ok
    s = ctl.read_settings()
    assert (s["reverb_time"], s["reverb_pre"], s["reverb_high_cut"], s["delay_low_cut"]) == (
        150,
        900,
        8000,
        200,
    )
    ctl.set_parameter("reverb_type", 3)
    assert ctl.set_parameter("reverb_spring_reverb", 40).ok
    assert ctl.set_parameter("reverb_spring_filter", 60).ok
    s = ctl.read_settings()
    assert (s["reverb_spring_reverb"], s["reverb_spring_filter"]) == (40, 60)
    assert "reverb_time" not in s
