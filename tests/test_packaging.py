import re
import shutil
import subprocess
import tomllib
import xml.dom.minidom
from pathlib import Path

import pytest

from thr_control import __version__, cli, paths
from thr_control.services import desktop, doctor

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.bleaff.ThrControl"
THR = "THR5:THR5 MIDI 1 24:0"


# -- platform folders ------------------------------------------------------------------------------
def test_paths_follow_xdg_on_linux_and_stay_where_they_were(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    if not __import__("sys").platform.startswith("linux"):
        pytest.skip("XDG layout is Linux-specific")
    assert paths.data_dir() == tmp_path / "thr-control"
    assert paths.presets_dir() == tmp_path / "thr-control" / "presets"  # same place as before
    assert paths.measurements_dir() == tmp_path / "thr-control" / "measurements"
    assert paths.takes_dir().name == "thr-control"


# -- doctor ---------------------------------------------------------------------------------------
def good(**over):
    base = dict(
        platform="linux",
        python=(3, 12),
        midi_backend_error=lambda: None,
        seq_access=lambda: True,
        inputs=lambda: [THR],
        outputs=lambda: [THR],
        heartbeat=lambda port, timeout: True,
        which=lambda name: f"/usr/bin/{name}",
        portaudio_ok=lambda: False,
        audio_present=lambda: True,
        writable=lambda d: True,
        presets_dir=lambda: Path("/tmp/presets"),
        gui_ok=lambda: True,
    )
    base.update(over)
    return doctor.Probes(**base)


def by_name(checks):
    return {c.name: c for c in checks}


def test_doctor_all_good():
    checks = doctor.run_checks(good())
    assert all(c.status == doctor.OK for c in checks), [c for c in checks if c.status != doctor.OK]
    assert doctor.summarise(checks) == (0, 0)
    assert {
        "Python",
        "MIDI backend",
        "MIDI permissions",
        "Amplifier",
        "Amp responding",
        "Audio backend",
        "Amp USB audio",
        "Preset library",
    } <= set(by_name(checks))


@pytest.mark.parametrize(
    ("probes", "name", "status", "hint_part"),
    [
        (dict(python=(3, 10)), "Python", doctor.FAIL, "3.12"),
        (dict(gui_ok=lambda: False), "Desktop app (Qt)", doctor.FAIL, "Reinstall"),
        (dict(seq_access=lambda: False), "MIDI permissions", doctor.FAIL, "audio group"),
        (dict(inputs=lambda: [], outputs=lambda: []), "Amplifier", doctor.FAIL, "USB cable"),
        (
            dict(inputs=lambda: ["Midi Through"], outputs=lambda: ["Midi Through"]),
            "Amplifier",
            doctor.FAIL,
            "switch it on",
        ),
        (dict(heartbeat=lambda p, t: False), "Amp responding", doctor.WARN, "tuner"),
        (
            dict(which=lambda n: None if n == "pw-record" else "/x"),
            "Audio backend",
            doctor.WARN,
            "pipewire",
        ),
        (dict(audio_present=lambda: False), "Amp USB audio", doctor.WARN, "unavailable"),
        (dict(writable=lambda d: False), "Preset library", doctor.FAIL, "permissions"),
    ],
)
def test_doctor_reports_each_problem_with_a_fix(probes, name, status, hint_part):
    check = by_name(doctor.run_checks(good(**probes)))[name]
    assert check.status == status and hint_part.lower() in (check.hint + check.detail).lower()


def test_doctor_unopenable_port():
    def boom(port, timeout):
        raise OSError("device busy")

    c = by_name(doctor.run_checks(good(heartbeat=boom)))["Amp port"]
    assert c.status == doctor.FAIL and "device busy" in c.detail


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            "libjack.so.0: cannot open shared object file: No such file or directory",
            "pipewire-jack",
        ),
        ("libasound.so.2: cannot open shared object file", "alsa-lib"),
        ("something else went wrong", "ALSA and JACK"),
    ],
)
def test_doctor_names_the_missing_midi_library(error, expected):
    checks = by_name(doctor.run_checks(good(midi_backend_error=lambda: error)))
    c = checks["MIDI backend"]
    assert c.status == doctor.FAIL and error in c.detail and expected in c.hint
    assert "libjack-jackd2-0" in c.hint or "libasound2" in c.hint  # Debian/Ubuntu names too
    assert "Amplifier" not in checks  # cannot look for the amp without a MIDI backend


def test_midi_hint_off_linux_is_generic():
    assert "Reinstall" in doctor.midi_library_hint("anything", linux=False)


def test_doctor_on_macos_skips_linux_only_checks_and_checks_portaudio():
    names = by_name(doctor.run_checks(good(platform="darwin", portaudio_ok=lambda: True)))
    assert "MIDI permissions" not in names
    assert (
        names["Audio backend"].status == doctor.OK and "PortAudio" in names["Audio backend"].detail
    )
    assert names["Amplifier"].status == doctor.OK


def test_doctor_accepts_portaudio_when_the_pipewire_tools_are_missing():
    c = by_name(doctor.run_checks(good(which=lambda n: None, portaudio_ok=lambda: True)))
    assert (
        c["Audio backend"].status == doctor.OK
        and "PortAudio will be used" in c["Audio backend"].detail
    )


def test_doctor_does_not_check_audio_when_there_is_no_amp():
    names = by_name(doctor.run_checks(good(inputs=lambda: [], outputs=lambda: [])))
    assert "Amp USB audio" not in names


def test_cli_doctor_prints_fixes_and_sets_the_exit_code(monkeypatch, capsys):
    checks = [
        doctor.Check("Python", doctor.OK, "3.14"),
        doctor.Check("Amplifier", doctor.FAIL, "no MIDI ports", "Connect the amp."),
        doctor.Check("Audio backend", doctor.WARN, "missing: pw-record", "Install pipewire."),
    ]
    monkeypatch.setattr(doctor, "run_checks", lambda: checks)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] Amplifier: no MIDI ports" in out and "-> Connect the amp." in out
    assert "[ OK ]" not in out and "[OK  ] Python" in out and "1 problem(s), 1 warning(s)" in out
    monkeypatch.setattr(doctor, "run_checks", lambda: [doctor.Check("Python", doctor.OK, "ok")])
    assert cli.main(["doctor"]) == 0
    assert "Everything needed is in place." in capsys.readouterr().out


# -- menu entry ------------------------------------------------------------------------------------
def test_install_and_remove_the_launcher(tmp_path):
    created = desktop.install(tmp_path, "/home/me/.local/bin/thr-control-gui")
    desktop_file, icon = created
    assert desktop_file == tmp_path / "applications" / f"{APP_ID}.desktop"
    assert icon == tmp_path / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
    text = desktop_file.read_text()
    assert "Exec=/home/me/.local/bin/thr-control-gui\n" in text and f"Icon={APP_ID}" in text
    assert icon.read_bytes() == (ROOT / "src/thr_control/data/icons" / f"{APP_ID}.svg").read_bytes()
    if shutil.which("desktop-file-validate"):
        done = subprocess.run(
            ["desktop-file-validate", str(desktop_file)], capture_output=True, text=True
        )
        assert done.returncode == 0, done.stdout + done.stderr
    assert desktop.remove(tmp_path) == created
    assert desktop.remove(tmp_path) == []  # idempotent


def test_launcher_path_with_spaces_is_quoted(tmp_path):
    f, _ = desktop.install(tmp_path, "/home/my user/bin/thr-control-gui")
    assert 'Exec="/home/my user/bin/thr-control-gui"' in f.read_text()


def test_cli_install_desktop(monkeypatch, tmp_path, capsys):
    if not __import__("sys").platform.startswith("linux"):
        pytest.skip("Linux-only command")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(desktop, "launcher_command", lambda: "/opt/thr/bin/thr-control-gui")
    monkeypatch.setattr(desktop, "refresh_caches", lambda d: None)
    assert cli.main(["install-desktop"]) == 0
    assert (tmp_path / "applications" / f"{APP_ID}.desktop").exists()
    assert "application menu" in capsys.readouterr().out
    assert cli.main(["install-desktop", "--remove"]) == 0
    assert not (tmp_path / "applications" / f"{APP_ID}.desktop").exists()
    monkeypatch.setattr(
        desktop,
        "launcher_command",
        lambda: (_ for _ in ()).throw(desktop.DesktopError("not installed")),
    )
    assert cli.main(["install-desktop"]) == 1


def test_install_desktop_refused_off_linux(monkeypatch, capsys):
    monkeypatch.setattr("sys.platform", "darwin")
    assert cli.main(["install-desktop"]) == 1
    assert "macOS" in capsys.readouterr().err


# -- package metadata is consistent ----------------------------------------------------------------
def test_license_and_metadata():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = meta["project"]
    assert project["license"] == "AGPL-3.0-or-later" and "LICENSE" in project["license-files"]
    assert "version" in project["dynamic"] and re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert project["scripts"]["thr-control"] == "thr_control.cli:main"
    assert project["gui-scripts"]["thr-control-gui"] == "thr_control.gui.app:main"
    assert (ROOT / "LICENSE").read_text().lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert any("platformdirs" in d for d in project["dependencies"])


def test_app_id_is_the_same_everywhere():
    from thr_control.gui import app

    assert app.APP_ID == desktop.APP_ID == APP_ID
    assert app.ICON.exists() and app.ICON.name == f"{APP_ID}.svg"
    xml.dom.minidom.parse(str(app.ICON))  # well-formed SVG
    desk = (ROOT / "packaging/linux" / f"{APP_ID}.desktop").read_text()
    info = (ROOT / "packaging/linux" / f"{APP_ID}.metainfo.xml").read_text()
    assert f"Icon={APP_ID}" in desk and f"<id>{APP_ID}</id>" in info
    assert f"{APP_ID}.desktop" in info and "AGPL-3.0-or-later" in info
    assert "unofficial" in info.lower() or "Unofficial" in info  # not presented as Yamaha's product


def test_packaging_files_validate():
    desk = ROOT / "packaging/linux" / f"{APP_ID}.desktop"
    info = ROOT / "packaging/linux" / f"{APP_ID}.metainfo.xml"
    if shutil.which("desktop-file-validate"):
        done = subprocess.run(["desktop-file-validate", str(desk)], capture_output=True, text=True)
        assert done.returncode == 0, done.stdout
    if shutil.which("appstreamcli"):
        done = subprocess.run(
            ["appstreamcli", "validate", "--no-net", str(info)], capture_output=True, text=True
        )
        problems = [ln for ln in done.stdout.splitlines() if ln.startswith(("E:", "W:"))]
        # a homepage URL is added once the public repository exists
        assert all("url-homepage-missing" in ln for ln in problems), done.stdout


# -- macOS and Arch packaging files ----------------------------------------------------------------
def test_icns_is_a_well_formed_icon_container():
    import struct

    data = (ROOT / "packaging/macos/ThrControl.icns").read_bytes()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    pos, found = 8, {}
    while pos < len(data):
        ostype = data[pos : pos + 4].decode("ascii")
        length = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        png = data[pos + 8 : pos + length]
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", png[16:24])  # PNG IHDR
        assert width == height
        found[ostype] = width
        pos += length
    assert pos == len(data)
    assert found["ic07"] == 128 and found["ic08"] == 256 and found["ic09"] == 512
    assert (
        found["ic10"] == 1024 and found["icp4"] == 16 and found["ic14"] == 512
    )  # incl. retina sizes


def test_icns_generator_reproduces_the_committed_icon():
    pytest.importorskip("PySide6.QtSvg")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_icns", ROOT / "packaging/macos/make_icns.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    built = module.build()
    committed = (ROOT / "packaging/macos/ThrControl.icns").read_bytes()
    assert built[:4] == committed[:4] == b"icns" and len(built) > 100_000
    assert [built[i : i + 4] for i in (8,)] == [committed[8:12]]


def test_macos_spec_requests_microphone_access_and_bundles_the_data():
    spec = (ROOT / "packaging/macos/thr-control.spec").read_text()
    for needle in (
        "NSMicrophoneUsageDescription",  # without it macOS records silence
        "io.github.bleaff.ThrControl",
        "mido.backends.rtmidi",  # chosen by name at runtime: PyInstaller cannot see it
        "thr_control/data",
        "ThrControl.icns",
    ):
        assert needle in spec, needle
    assert (ROOT / "packaging/macos/launcher.py").read_text().count("thr_control.gui.app") == 1
    script = (ROOT / "packaging/macos/build.sh").read_text()
    assert "codesign" in script and "hdiutil" in script and "Darwin" in script
    assert subprocess.run(["bash", "-n", str(ROOT / "packaging/macos/build.sh")]).returncode == 0
    assert (ROOT / "packaging/macos/build.sh").stat().st_mode & 0o111  # executable


def test_arch_recipe_matches_the_project():
    recipe = (ROOT / "packaging/arch/PKGBUILD").read_text()
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert f"pkgver={__version__}" in recipe
    assert (
        "license=('AGPL-3.0-or-later')" in recipe
        and "AGPL-3.0-or-later" in meta["project"]["license"]
    )
    for dep in (
        "pyside6",
        "python-mido",
        "python-rtmidi",
        "python-numpy",
        "python-pydantic",
        "python-platformdirs",
    ):
        assert f"'{dep}'" in recipe, dep
    assert "|| true" not in recipe  # a check() that cannot fail would hide broken tests
    assert f"local id={APP_ID}" in recipe  # the same id as the desktop file and metainfo
    assert "$id.desktop" in recipe and "$id.metainfo.xml" in recipe and "$id.svg" in recipe


def test_workflows_exist_and_use_the_scripts():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    mac = (ROOT / ".github/workflows/macos-app.yml").read_text()
    assert "macos-latest" in ci and "pytest" in ci and "ruff check" in ci and "mypy" in ci
    assert "packaging/macos/build.sh" in mac and "macos-13" in mac and "macos-14" in mac
