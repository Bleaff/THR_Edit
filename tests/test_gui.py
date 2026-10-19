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
def select(win, name):
    for i in range(win.browser.list.count()):
        if win.browser.list.item(i).text().startswith((name, "★ " + name)):
            win.browser.list.setCurrentRow(i)
            return
    raise AssertionError(f"{name} not listed")


def test_sidebar_lists_starters_and_filters(app, setup):
    _, win = setup(None)
    b = win.browser
    assert b.list.count() == 5
    b.search.setText("blues")
    assert b.list.count() == 1 and "Texas Blues" in b.list.item(0).text()
    b.search.setText("")
    b.genre.setCurrentText("Indie")
    assert b.list.count() == 2
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
    assert set(win.manager.get(win.active.id).settings) == set(win.controls)
    # with an active preset: Save overwrites its settings
    win.controls["treble"].knob.setValue(11)
    assert win.preset_label.text().endswith("*")
    win.save_button.click()
    assert win.manager.get(win.active.id).settings["treble"] == 11
    assert not win.preset_label.text().endswith("*")
    # sidebar button: save as new
    prompts.text = "Another"
    win.browser.save_as_button.click()
    assert win.active.name == "Another" and win.browser.list.count() == 7
    prompts.text = None  # cancelled dialog creates nothing
    win.browser.save_as_button.click()
    assert win.browser.list.count() == 7


def test_rename_duplicate_delete_favorite_via_sidebar(app, setup):
    prompts = StubPrompts()
    _, win = setup(None, prompts)
    b = win.browser
    select(win, "Golden Brown")
    prompts.text = "Golden Brownish"
    b.rename_button.click()
    assert b.list.currentItem().text().startswith("Golden Brownish")
    b.duplicate_button.click()
    assert b.list.count() == 6 and "(copy)" in b.list.currentItem().text()
    b.favorite_button.click()
    assert b.list.currentItem().text().startswith("★")
    b.favorites.setChecked(True)
    assert b.list.count() == 1
    b.favorites.setChecked(False)
    prompts.confirm_answer = False
    b.delete_button.click()
    assert b.list.count() == 6  # declined
    prompts.confirm_answer = True
    b.delete_button.click()
    assert b.list.count() == 5
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
    assert win2.browser.list.count() == 5  # export covered the whole (unfiltered) view
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
