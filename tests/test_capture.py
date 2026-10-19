import io

from tests.test_protocol import synthetic_dump
from thr_control.protocol.parser import SettingsDump, parse
from thr_control.services.capture import diff_payloads, run_mapping


def dump_with(offset: int, value: int) -> SettingsDump:
    raw = bytearray(synthetic_dump())
    raw[18 + offset] = value
    body = bytes(raw[6:-2])
    from thr_control.protocol.messages import checksum

    raw[-2] = checksum(body)
    msg = parse(bytes(raw))
    assert isinstance(msg, SettingsDump)
    return msg


def test_diff_payloads():
    assert diff_payloads(b"\x00\x01\x02", b"\x00\x05\x02") == [(1, 1, 5)]


def test_run_mapping_reports_changed_offsets():
    dumps = iter([dump_with(130, 10), dump_with(130, 0), dump_with(130, 100)])
    out = io.StringIO()
    res = run_mapping(lambda: next(dumps), lambda _p: "", out, knobs=["MASTER"])
    assert res["MASTER"]["min"] == [(130, 10, 0)]
    assert res["MASTER"]["max"] == [(130, 0, 100)]
    assert "[130] 10->0" in out.getvalue()


def test_run_mapping_skip():
    dumps = iter([dump_with(0, 0)])
    res = run_mapping(lambda: next(dumps), lambda _p: "s", io.StringIO(), knobs=["TONE"])
    assert res == {"TONE": {}}


def test_real_knob_map_fixture():
    """Captured on a THR5A with THR5 V2 firmware via `thr-control map` (see docs/protocol.md)."""
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent / "fixtures" / "thr5a_knob_map.json").read_text())
    offsets = {k: {o for ch in v.values() for o, _, _ in ch} for k, v in data.items()}
    assert offsets["VOLUME"] == set()  # analog knob, not in the dump
    assert offsets["MASTER"] == {130}
    assert offsets["BLEND"] == {129}
    assert {128, 134} <= offsets["MIC TYPE"]
    assert {131, 132, 133} <= offsets["TONE"]
