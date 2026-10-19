import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.fake_amp import FakeAmp, real_payload  # noqa: E402
from thr_control.gui.bridge import SessionBridge  # noqa: E402
from thr_control.gui.main_window import MainWindow  # noqa: E402
from thr_control.gui.style import STYLESHEET  # noqa: E402
from thr_control.services.preset_manager import PresetManager  # noqa: E402
from thr_control.storage.repository import PresetRepository  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLESHEET)
    return app


def pump(app, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


class Backend:
    def __init__(self, amp):
        self.amp = amp

    def connect(self):
        if self.amp is None:
            raise ConnectionError("no THR amplifier found")
        return self.amp, "THR5 (fake)"


class StubPrompts:
    def __init__(self):
        self.text = None
        self.confirm_answer = True
        self.open_path = None
        self.save_path = None
        self.errors = []

    def ask_text(self, parent, title, label, default=""):
        return self.text

    def confirm(self, parent, text):
        return self.confirm_answer

    def open_file(self, parent):
        return self.open_path

    def save_file(self, parent, default):
        return self.save_path

    def show_error(self, parent, text):
        self.errors.append(text)


@pytest.fixture
def setup(app, tmp_path):
    made = []
    counter = iter(range(1000))

    def make(amp, prompts=None):
        if amp is not None:
            amp.heartbeat_interval = 0.1
        bridge = SessionBridge(Backend(amp))
        manager = PresetManager(PresetRepository(tmp_path / f"lib{next(counter)}"))
        manager.seed_starters()
        win = MainWindow(bridge, manager, prompts)
        win.show()
        bridge.start()
        made.append((bridge, win))
        return bridge, win

    yield make
    for bridge, win in made:
        win.close()
        bridge.stop()


def test_disabled_without_amp(app, setup):
    _, win = setup(None)
    assert pump(app, lambda: win.diagnostics.history.count() >= 1)
    assert "Disconnected" in win.status_label.text()
    assert all(not c.isEnabled() for c in win.controls.values())
    assert win.centralWidget() is not None  # window stays usable


def test_shows_amp_state_when_connected(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(
        app,
        lambda: "Connected" in win.status_label.text() and win.controls["master"].value() == 0x33,
    )
    assert win.controls["gain"].value() == 0x34
    assert all(c.isEnabled() for c in win.controls.values())
    assert "THR5 (fake)" in win.device_label.text()


def test_user_change_reaches_amp(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    win.controls["master"].knob.setValue(80)  # same signal path as a user drag
    assert pump(app, lambda: ("master", 80) in amp.sets)
    win.controls["delay"].setChecked(True)
    assert pump(app, lambda: ("delay", 1) in amp.sets)
    win.controls["amp"]._group.button(3).click()
    assert pump(app, lambda: ("amp", 3) in amp.sets)


def test_amp_knob_turn_updates_ui_without_echo(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    amp.inject_event("bass", 7)
    amp.inject_event("amp", 4)
    amp.inject_event("reverb", 1)
    assert pump(
        app,
        lambda: (
            win.controls["bass"].value() == 7
            and win.controls["amp"]._group.checkedId() == 4
            and win.controls["reverb"].isChecked()
        ),
    )
    time.sleep(0.15)
    app.processEvents()
    assert amp.sets == []  # no feedback loop


def test_dragging_knob_ignores_device_updates(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["gain"].value() == 0x34)
    knob = win.controls["gain"]
    knob.knob.setSliderDown(True)
    knob.apply(5)
    assert knob.value() == 0x34
    knob.knob.setSliderDown(False)
    knob.apply(5)
    assert knob.value() == 5


def test_diagnostics_monitor_and_export(app, setup, tmp_path):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    win.diagnostics.flush()
    text = win.diagnostics.monitor.toPlainText()
    assert "TX F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7" in text  # settings request
    assert "settings dump" in text
    assert "HEARTBEAT" not in text.upper() and "heartbeat" not in text  # filtered by default
    assert pump(app, lambda: "heartbeat THR5" in win.diagnostics.export_text())
    out = tmp_path / "diag.txt"
    win.diagnostics.export_to(out)
    exported = out.read_text()
    assert "heartbeat THR5" in exported and "connected: THR5 (fake)" in exported


def test_window_renders(app, setup, tmp_path):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    assert win.grab().save(str(tmp_path / "shot.png"))


# -- presets ---------------------------------------------------------------
import json  # noqa: E402
import math  # noqa: E402
from importlib import resources  # noqa: E402

STARTERS = json.loads(
    resources.files("thr_control.data").joinpath("starter_presets.json").read_text("utf-8")
)["presets"]
N0 = len(STARTERS)


def select(win, name):
    for i in range(win.browser.list.count()):
        if win.browser.list.item(i).text().startswith((name, "★ " + name)):
            win.browser.list.setCurrentRow(i)
            return
    raise AssertionError(f"{name} not listed")


def test_sidebar_lists_starters_and_filters(app, setup):
    _, win = setup(None)
    b = win.browser
    assert b.list.count() == N0
    b.search.setText("blues")
    assert b.list.count() == 3 and "Texas Blues" in b.list.item(2).text()
    b.search.setText("")
    b.genre.setCurrentText("Indie")
    assert b.list.count() == sum(e["genre"] == "Indie" for e in STARTERS)
    b.genre.setCurrentText("All genres")
    b.favorites.setChecked(True)
    assert b.list.count() == 0
    # not connected: cannot load or save
    assert not b.load_button.isEnabled() and not win.save_button.isEnabled()


def test_load_preset_sends_amp_first_and_updates_ui(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    select(win, "Texas Blues")
    assert win.browser.load_button.isEnabled()
    win.browser.load_button.click()
    assert win.active.name == "Texas Blues"
    assert win.controls["gain"].value() == 48 and win.controls["amp"].get() == 1
    assert pump(app, lambda: ("reverb_level", 38) in amp.sets)
    assert amp.sets[0] == ("amp", 1)
    assert pump(app, lambda: "modified" not in win.preset_label.text())
    assert win.preset_label.text() == "Preset: Texas Blues"  # confirmed by readback, not modified


def test_active_preset_shows_modified_marker(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    select(win, "Warm Jazz")
    win.browser.load_button.click()
    assert win.preset_label.text() == "Preset: Warm Jazz"
    win.controls["master"].knob.setValue(win.controls["master"].value() + 3)
    assert win.preset_label.text() == "Preset: Warm Jazz *"
    amp.inject_event("master", 45)  # turning the amp's own knob back
    assert pump(app, lambda: win.preset_label.text() == "Preset: Warm Jazz")


def test_save_updates_active_and_save_as_creates(app, setup):
    prompts = StubPrompts()
    amp = FakeAmp(real_payload())
    _, win = setup(amp, prompts)
    assert pump(app, lambda: win.save_button.isEnabled())
    # no active preset: Save asks for a name and creates one from the current controls
    prompts.text = "My Tone"
    win.save_button.click()
    assert win.active.name == "My Tone"
    assert win.manager.get(win.active.id).settings["master"] == 0x33
    saved = win.manager.get(win.active.id).settings
    assert set(saved) == set(win.current_settings())
    spring_only = {"reverb_spring_reverb", "reverb_spring_filter"}
    assert not spring_only & set(saved)  # real dump is hall: spring values are not stored
    assert set(win.controls) - spring_only <= set(saved)
    # with an active preset: Save overwrites its settings
    win.controls["treble"].knob.setValue(11)
    assert win.preset_label.text().endswith("*")
    win.save_button.click()
    assert win.manager.get(win.active.id).settings["treble"] == 11
    assert not win.preset_label.text().endswith("*")
    # sidebar button: save as new
    prompts.text = "Another"
    win.browser.save_as_button.click()
    assert win.active.name == "Another" and win.browser.list.count() == N0 + 2
    prompts.text = None  # cancelled dialog creates nothing
    win.browser.save_as_button.click()
    assert win.browser.list.count() == N0 + 2


def test_rename_duplicate_delete_favorite_via_sidebar(app, setup):
    prompts = StubPrompts()
    _, win = setup(None, prompts)
    b = win.browser
    select(win, "Golden Brown")
    prompts.text = "Golden Brownish"
    b.rename_button.click()
    assert b.list.currentItem().text().startswith("Golden Brownish")
    b.duplicate_button.click()
    assert b.list.count() == N0 + 1 and "(copy)" in b.list.currentItem().text()
    b.favorite_button.click()
    assert b.list.currentItem().text().startswith("★")
    b.favorites.setChecked(True)
    assert b.list.count() == 1
    b.favorites.setChecked(False)
    prompts.confirm_answer = False
    b.delete_button.click()
    assert b.list.count() == N0 + 1  # declined
    prompts.confirm_answer = True
    b.delete_button.click()
    assert b.list.count() == N0
    prompts.text = "   "  # invalid name is reported, not crashed on
    select(win, "Warm Jazz")
    b.rename_button.click()
    assert prompts.errors


def test_deleting_active_preset_clears_label(app, setup):
    amp = FakeAmp(real_payload())
    prompts = StubPrompts()
    _, win = setup(amp, prompts)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    select(win, "Indie Rock")
    win.browser.load_button.click()
    assert "Indie Rock" in win.preset_label.text()
    win.browser.delete_button.click()
    assert win.active is None and win.preset_label.text() == "Preset: —"


def test_import_export_via_sidebar(app, setup, tmp_path):
    prompts = StubPrompts()
    _, win = setup(None, prompts)
    select(win, "Warm Jazz")
    prompts.save_path = str(tmp_path / "out.json")
    win.browser.export_button.click()
    assert (tmp_path / "out.json").exists()
    _, win2 = setup(None, prompts)
    for p in win2.manager.all():
        win2.manager.delete(p.id)
    win2.browser.refresh()
    assert win2.browser.list.count() == 0
    prompts.open_path = str(tmp_path / "out.json")
    win2.browser.import_button.click()
    assert win2.browser.list.count() == N0  # export covered the whole (unfiltered) view
    prompts.open_path = str(tmp_path / "missing.json")
    win2.browser.import_button.click()
    assert prompts.errors


def test_window_with_sidebar_renders(app, setup, tmp_path):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    select(win, "Warm Jazz")
    win.resize(1200, 760)
    assert win.grab().save(str(tmp_path / "shot.png"))


def test_busy_badge_while_amp_pauses_heartbeat(app, setup, monkeypatch):
    monkeypatch.setattr("thr_control.services.session.HEARTBEAT_TIMEOUT", 0.2)
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    assert win.busy_label.isHidden()
    amp.heartbeat_interval = None
    assert pump(app, lambda: not win.busy_label.isHidden())
    assert "Connected" in win.status_label.text()  # still connected
    amp.heartbeat_interval = 0.05
    assert pump(app, lambda: win.busy_label.isHidden())


def test_delay_time_follows_taps_and_sends_user_edits(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    spin = win.controls["delay_time"]
    amp.inject_event("delay_time", 5299)  # what TAP/TIME produces
    assert pump(app, lambda: abs(spin.value() - 529.9) < 0.01)
    time.sleep(0.15)
    app.processEvents()
    assert amp.sets == []  # following the amp never writes back
    spin.setValue(400.0)  # user edit
    assert pump(app, lambda: ("delay_time", 4000) in amp.sets)
    assert spin.get() == 4000


def test_modulation_knobs_follow_type_and_cab_selector(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    panel = win.effects_panel
    visible = lambda: [k.title.text() for k in panel.mod_knobs if not k.isHidden()]  # noqa: E731
    amp.inject_event("modulation_type", 1)  # flanger: 5 parameters
    assert pump(app, lambda: visible() == ["SPEED", "MANUAL", "DEPTH", "FEEDBACK", "SPREAD"])
    amp.inject_event("modulation_type", 2)  # tremolo: 2 parameters
    assert pump(app, lambda: visible() == ["FREQ", "DEPTH"])
    amp.inject_event("modulation_p2", 33)
    assert pump(app, lambda: win.controls["modulation_p2"].value() == 33)
    win.controls["modulation_p1"].knob.setValue(61)
    assert pump(app, lambda: ("modulation_p1", 61) in amp.sets)
    # cab selector shows the amp's cab and sends user changes
    amp.inject_event("cab", 3)
    assert pump(app, lambda: win.controls["cab"].currentIndex() == 3)
    win.controls["cab"].setCurrentIndex(5)
    win.controls["cab"].activated.emit(5)
    assert pump(app, lambda: ("cab", 5) in amp.sets)


def test_reverb_controls_follow_reverb_type_and_delay_cuts(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    panel = win.effects_panel
    amp.inject_event("reverb_type", 0)
    assert pump(app, lambda: not panel._reverb_full.isHidden() and panel._reverb_spring.isHidden())
    amp.inject_event("reverb_time", 150)
    amp.inject_event("delay_high_cut", 8000)
    assert pump(
        app,
        lambda: (
            win.controls["reverb_time"].value() == 150
            and win.controls["delay_high_cut"].value() == 8000
        ),
    )
    time.sleep(0.15)
    app.processEvents()
    assert amp.sets == []  # following the amp never writes back
    win.controls["reverb_pre"].setValue(900)
    assert pump(app, lambda: ("reverb_pre", 900) in amp.sets)
    amp.inject_event("reverb_type", 3)
    assert pump(app, lambda: panel._reverb_full.isHidden() and not panel._reverb_spring.isHidden())
    amp.inject_event("reverb_spring_filter", 66)  # same wire id family as reverb_time
    assert pump(app, lambda: win.controls["reverb_spring_filter"].value() == 66)
    assert win.controls["reverb_time"].value() == 150  # hall value untouched by spring events
    # presets saved while on spring contain only spring values
    saved = win.current_settings()
    assert "reverb_spring_reverb" in saved and "reverb_time" not in saved


def test_eq_curve_follows_knobs_and_amp_events(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    curve = win.amp_panel.eq_curve
    assert curve.values() == (0x3B, 0x32, 0x3E)  # the amp's bass/middle/treble at connect
    amp.inject_event("bass", 100)
    assert pump(app, lambda: curve.values()[0] == 100)
    win.controls["treble"].knob.setValue(10)  # user drag
    assert pump(app, lambda: curve.values()[2] == 10)
    assert curve.curve()[0] > 5 and curve.curve()[-1] < -5  # bass boost, treble cut


def test_tempo_sync_sets_delay_time_and_shows_tap_tempo(app, setup):
    amp = FakeAmp(real_payload())
    _, win = setup(amp)
    assert pump(app, lambda: win.controls["master"].value() == 0x33)
    panel = win.effects_panel
    panel.bpm.setValue(120.0)
    panel.division.setCurrentText("dotted 1/8")
    panel.sync_button.click()
    assert pump(app, lambda: ("delay_time", 3750) in amp.sets)
    assert abs(win.controls["delay_time"].value() - 375.0) < 0.01
    # a tap on the amp changes the time; the readout shows it as a tempo for the chosen division
    amp.inject_event("delay_time", 3000)
    assert pump(app, lambda: "Current delay = 150.0 BPM as dotted 1/8" in panel.sync_info.text())
    # out-of-range requests are explained, not sent
    sent = len(amp.sets)
    panel.bpm.setValue(40.0)
    panel.division.setCurrentText("1/2")
    panel.sync_button.click()
    assert "allows" in panel.sync_info.text() and len(amp.sets) == sent


def test_preset_notes_are_edited_saved_searchable_and_shown(app, setup):
    prompts = StubPrompts()
    _, win = setup(None, prompts)
    b = win.browser
    assert not b.notes.isEnabled()
    select(win, "Studio Clean")
    assert b.notes.isEnabled() and "Neutral" in b.notes.toPlainText()
    preset = b.selected()
    b.notes.setPlainText("my own words about this tone")
    b.flush_notes()  # normally fires 0.7 s after the last keystroke
    assert win.manager.get(preset.id).notes == "my own words about this tone"
    b.search.setText("own words")
    assert b.list.count() == 1 and "Studio Clean" in b.list.item(0).text()
    assert b.list.item(0).toolTip() == "my own words about this tone"
    b.search.setText("")
    # switching selection saves pending edits to the preset they belong to
    select(win, "Studio Clean")
    b.notes.setPlainText("edited, then switched away")
    select(win, "Funk Clean")
    assert win.manager.get(preset.id).notes == "edited, then switched away"
    assert "Tight" in b.notes.toPlainText()


# -- live measurement ----------------------------------------------------------------------------
from thr_control.domain import eq as eq_domain  # noqa: E402
from thr_control.domain.live import LiveResult  # noqa: E402
from thr_control.services.live import LiveSnapshot  # noqa: E402

LIVE_FREQS = eq_domain.log_frequencies(120)


class ScriptedStream:
    """Stands in for LiveStream: returns whatever snapshot the test sets."""

    def __init__(self):
        self.started = self.stopped = False
        self.current = LiveSnapshot("waiting for signal", None, None, -90.0, -90.0, None)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return self.current


def live_result(valid_from=0, valid_to=None):
    n = len(LIVE_FREQS)
    valid = [valid_from <= i < (valid_to or n) for i in range(n)]
    db = [6.0 if f < 300 else 0.0 for f in LIVE_FREQS]
    return LiveResult(LIVE_FREQS, db, [0.95] * n, valid, 100)


def test_live_button_shows_status_and_overlays_only_trusted_points(app, setup, tmp_path):
    stream = ScriptedStream()
    _, win = setup(None)
    win.live_meter._factory = lambda: stream
    panel, curve = win.amp_panel, win.amp_panel.eq_curve
    panel.live_button.setChecked(True)
    assert stream.started and win.live_meter.running
    win.live_meter.update_now()
    assert "Play your guitar" in panel.live_status.text() and curve.measured() is None
    stream.current = LiveSnapshot("calibrating", None, None, -30.0, -28.0, None)
    win.live_meter.update_now()
    assert "latency" in panel.live_status.text()
    stream.current = LiveSnapshot("measuring", None, live_result(valid_to=3), -30.0, -28.0, 569)
    win.live_meter.update_now()
    assert curve.measured() is None and "not enough signal" in panel.live_status.text()
    stream.current = LiveSnapshot(
        "measuring", None, live_result(valid_from=20, valid_to=100), -30, -28, 569
    )
    win.live_meter.update_now()
    freqs, db, valid = curve.measured()
    assert sum(valid) == 80 and "80 of 120 bands trusted" in panel.live_status.text()
    assert "11.9 ms" in panel.live_status.text()  # 569 samples at 48 kHz
    assert win.grab().save(str(tmp_path / "live.png"))  # painting with the overlay works
    panel.live_button.setChecked(False)
    assert stream.stopped and curve.measured() is None and panel.live_status.text() == ""
    assert not win.live_meter.running


def test_live_reports_errors_and_unavailable_audio(app, setup):
    from thr_control.services.audio import AudioError

    _, win = setup(None)

    def unavailable():
        raise AudioError("the THR's USB audio is not available")

    win.live_meter._factory = unavailable
    win.amp_panel.live_button.setChecked(True)
    assert not win.amp_panel.live_button.isChecked()  # switches itself back off
    assert "unavailable" in win.amp_panel.live_status.text()
    stream = ScriptedStream()
    win.live_meter._factory = lambda: stream
    win.amp_panel.live_button.setChecked(True)
    stream.current = LiveSnapshot("error", "pipe closed", None, -90.0, -90.0, None)
    win.live_meter.update_now()
    assert "failed: pipe closed" in win.amp_panel.live_status.text()
    stream.current = LiveSnapshot("ended", None, None, -90.0, -90.0, None)
    win.live_meter.update_now()
    assert "ended" in win.amp_panel.live_status.text()


def test_closing_the_window_stops_a_running_live_stream(app, setup):
    stream = ScriptedStream()
    _, win = setup(None)
    win.live_meter._factory = lambda: stream
    win.amp_panel.live_button.setChecked(True)
    win.close()
    assert stream.stopped


# -- the plot itself -----------------------------------------------------------------------------
from PySide6.QtCore import QPointF  # noqa: E402

from thr_control.gui import eq_curve  # noqa: E402


def test_pick_range_grows_at_once_and_shrinks_only_when_well_below():
    assert eq_curve.pick_range(8.0, 12.0) == 12.0  # fits, but not far enough below to shrink
    assert eq_curve.pick_range(5.0, 12.0) == 6.0  # well below 55% of the range: shrink
    assert eq_curve.pick_range(13.0, 12.0) == 18.0  # needs more: grow immediately
    assert eq_curve.pick_range(40.0, 12.0) == 36.0  # capped at the largest step
    assert eq_curve.pick_range(3.0, 18.0) == 6.0  # far below: shrink to the smallest fit
    assert eq_curve.pick_range(10.0, 18.0) == 18.0  # 10 > 55% of 18: keep, avoid flicker
    steps = eq_curve.RANGE_STEPS
    assert list(steps) == sorted(steps) and steps[0] <= 6


def test_smooth_path_passes_through_its_points():
    pts = [QPointF(0, 0), QPointF(10, 8), QPointF(20, -4), QPointF(30, 2)]
    path = eq_curve.smooth_points(pts)
    assert path.elementCount() == 1 + 3 * 3  # moveTo + a cubic (3 elements) per segment
    ends = [(path.elementAt(i).x, path.elementAt(i).y) for i in range(3, path.elementCount(), 3)]
    assert ends == [(10.0, 8.0), (20.0, -4.0), (30.0, 2.0)]
    assert eq_curve.smooth_points([]).elementCount() == 0


def test_plot_geometry_roundtrips_and_the_scale_adapts_to_data(app):
    curve = eq_curve.EqCurve()
    curve.resize(700, 300)
    rect = curve.plot_rect()
    for f in (20, 100, 1000, 20000):
        assert curve.freq_at(curve.x_for(f, rect), rect) == pytest.approx(f, rel=1e-6)
    assert curve.db_at(curve.y_for(0, rect), rect) == pytest.approx(0, abs=1e-9)
    assert curve.height() > 0 and curve.minimumHeight() >= 240  # a large plot
    flat_range = curve.half_range()
    curve.set_values(100, 50, 100)  # +12 dB shelves: the model alone needs more room
    assert curve.half_range() > flat_range or curve.half_range() >= 12
    n = 60
    freqs = eq_domain.log_frequencies(n)
    big = [30.0] * n
    curve.set_measured(freqs, big, [True] * n)
    assert curve.half_range() == 36.0  # +30 dB measured: the scale grows to fit
    curve.set_measured(freqs, big, [False] * n)  # nothing trusted: the data no longer counts
    curve.set_values(50, 50, 50)
    assert curve.half_range() < 36.0
    curve.clear_measured()
    assert curve.measured() is None


def test_plot_paints_every_state_without_error(app, tmp_path):
    curve = eq_curve.EqCurve()
    curve.resize(760, 320)
    freqs = eq_domain.log_frequencies(120)
    db = [6 * math.sin(i / 9) for i in range(120)]
    valid = [8 <= i < 50 or 62 <= i < 110 for i in range(120)]
    coherence = [0.95 if v else 0.3 for v in valid]
    for i, state in enumerate(("model", "measured", "measured+coherence", "hover", "disabled")):
        if state == "measured":
            curve.set_measured(freqs, db, valid)
        if state == "measured+coherence":
            curve.set_measured(freqs, db, valid, coherence)
        if state == "hover":
            rect = curve.plot_rect()
            curve._hover = QPointF(rect.center().x(), rect.center().y())
        if state == "disabled":
            curve.setEnabled(False)
        assert curve.grab().save(str(tmp_path / f"{i}-{state}.png"))
