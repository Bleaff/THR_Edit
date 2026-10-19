import pytest

from tests.fake_amp import FakeAmp, real_payload
from thr_control import cli
from thr_control.domain import eq, tempo
from thr_control.services.controller import ThrController


def test_note_lengths():
    assert tempo.note_ms(120, "1/4") == pytest.approx(500.0)
    assert tempo.note_ms(120, "dotted 1/8") == pytest.approx(375.0)
    assert tempo.note_ms(120, "1/8") == pytest.approx(250.0)
    assert tempo.note_ms(90, "1/8 triplet") == pytest.approx(222.222, abs=0.001)
    assert tempo.delay_value(120, "dotted 1/8") == 3750  # 375.0 ms in 0.1 ms units
    assert tempo.delay_value(92, "dotted 1/8") == 4891


def test_out_of_range_tempos_are_refused_not_clamped():
    with pytest.raises(ValueError, match="allows"):
        tempo.delay_value(50, "1/4")  # 1200 ms > 999.9 ms
    with pytest.raises(ValueError, match="allows"):
        tempo.delay_value(30, "1/2")  # 4000 ms
    with pytest.raises(ValueError):
        tempo.note_ms(10, "1/4")
    with pytest.raises(ValueError):
        tempo.note_ms(120, "1/3")
    assert tempo.delay_value(300, "1/16") == 500


def test_bpm_roundtrip_and_parse_division():
    for division in tempo.DIVISIONS:
        value = (
            tempo.delay_value(100, division) if division != "1/2" else tempo.delay_value(130, "1/2")
        )
        bpm = tempo.bpm_for(value, division)
        assert bpm == pytest.approx(100 if division != "1/2" else 130, rel=0.002)
    assert tempo.parse_division("dotted-1/8") == "dotted 1/8"
    assert tempo.parse_division("1/8T") == "1/8 triplet"
    assert tempo.parse_division("Dotted_1/4") == "dotted 1/4"
    with pytest.raises(ValueError):
        tempo.parse_division("bogus")
    # real tap values captured from the amp: 3000 / 5299 (0.1 ms) are 300 / 529.9 ms
    assert tempo.bpm_for(3000, "1/4") == pytest.approx(200.0)
    assert tempo.bpm_for(5299, "1/4") == pytest.approx(113.2, abs=0.05)


def test_synced_value_reaches_the_fake_amp():
    amp = FakeAmp(real_payload())
    ctl = ThrController(amp, settle=0)
    assert ctl.set_parameter("delay_time", tempo.delay_value(92, "dotted 1/8")).ok
    assert ctl.read_settings()["delay_time"] == 4891


def test_cli_delay_sync(capsys):
    assert cli.main(["delay-sync", "120", "dotted-1/8"]) == 0
    out = capsys.readouterr().out
    assert "375.0 ms" in out and "F0 43 7D 10 41 30 01 31 1D 26 F7" in out and "Dry run" in out
    assert cli.main(["delay-sync", "50"]) == 1  # 1200 ms: too long
    assert cli.main(["delay-sync", "120", "nonsense"]) == 1


# -- EQ curve ------------------------------------------------------------------------------
FREQS = eq.log_frequencies(60)


def test_flat_eq_is_flat():
    assert all(abs(db) < 1e-6 for db in eq.response_db(FREQS, 50, 50, 50))


def test_each_band_acts_in_its_own_region():
    bass = eq.response_db(FREQS, 100, 50, 50)
    treble = eq.response_db(FREQS, 50, 50, 100)
    mid = eq.response_db(FREQS, 50, 100, 50)
    at = lambda curve, f: curve[min(range(len(FREQS)), key=lambda i: abs(FREQS[i] - f))]  # noqa: E731
    assert at(bass, 40) > 9 and abs(at(bass, 10000)) < 1
    assert at(treble, 15000) > 9 and abs(at(treble, 40)) < 1
    assert at(mid, 800) > 9 and abs(at(mid, 40)) < 2 and abs(at(mid, 15000)) < 2


def test_cut_is_the_exact_inverse_of_boost():
    for knob in range(3):
        up = [50, 50, 50]
        down = [50, 50, 50]
        up[knob], down[knob] = 80, 20
        total = [
            a + b
            for a, b in zip(eq.response_db(FREQS, *up), eq.response_db(FREQS, *down), strict=True)
        ]
        assert all(abs(t) < 1e-6 for t in total)


def test_band_gain_mapping():
    assert eq.band_gain_db(50) == 0 and eq.band_gain_db(100) == 12 and eq.band_gain_db(0) == -12
