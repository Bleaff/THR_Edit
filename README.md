# THR Control

An **unofficial** editor for first-generation Yamaha THR guitar amplifiers (THR5, THR5A, THR10 family). Developed and tested on a
THR5A running THR5 V2 firmware.

Yamaha's official editor for these amps is no longer supported and has no Linux version. THR Control fills that gap: connect the
amp over USB and control it from your computer, with no Wine and no official software.

## What it does

- **Full amp control**: amp model, gain, master, EQ, cabinet and every effect (modulation, delay, reverb, gate, compressor).
  Turning a knob on the amp moves the knob on screen, and the other way round.
- **Preset library**: unlimited presets stored on your computer, with search, genres, favorites, notes, import and export.
  20 starter presets (blues, jazz, bossa nova, indie, rock, ambient, clean) are included.
- **Tempo-synced delay**: type a tempo and a note length, get the right delay time.
- **EQ curve**: a plot of bass / middle / treble that follows the amp live.
- **Recorder**: the amp is also a USB sound card; THR Control records the finished tone and the dry guitar at the same time, so
  the dry track can be re-amped later in a DAW.
- **Frequency response measurement**: sweeps the amp and plots its real response (experimental, see below).
- **Command line** for everything above, plus `thr-control doctor` to diagnose a setup.

**Safe by design:** the app only sends the amp's settings request and validated parameter changes. Firmware, erase and bootloader
commands are blocked in code and covered by tests.

*Yamaha and THR are trademarks of their owner. This project is independent and is not affiliated with or endorsed by Yamaha.*

## Install

You need Python 3.12 or newer.

```sh
git clone https://github.com/Bleaff/THR_Edit.git && cd THR_Edit
pipx install .                    # or: uv tool install .
thr-control doctor                # checks everything and tells you what to fix
thr-control install-desktop       # adds "THR Control" to your application menu (Linux)
thr-control-gui                   # or start it from the menu
```

Plug the amp in with its USB cable and switch it on. If something is missing, `thr-control doctor` explains it in plain words.

| Platform | Status |
| --- | --- |
| **Linux** | Supported (developed on Manjaro). Needs the ALSA and JACK *client libraries* (Arch: `alsa-lib`, `pipewire-jack`; Debian/Ubuntu: `libasound2`, `libjack-jackd2-0`); recording also needs the PipeWire tools (`pw-record`, `pw-play`, `pw-dump`) |
| **macOS** | Control, presets and recording work. Build the app with `packaging/macos/build.sh`. The live response plot does not work yet |
| **Windows** | Not supported (the THR needs a Yamaha driver there) |

Packaging recipes for Arch (`packaging/arch`), macOS (`packaging/macos`) and Flatpak (`packaging/flatpak`) are in the repository.

## Known limitations

- The **live frequency-response plot** is experimental: it does not work on macOS yet, and on Linux it works best with clean tones.
- The EQ curve is illustrative: the amp's real filter frequencies are not known.
- Some amp and effect type names are assumed to follow the THR10 order and are unverified on the THR5.
- The amp's tuner pitch is not available over MIDI; tune with the amp's own display.

## Documentation

- [Usage](docs/usage.md): every feature and command in detail.
- [Protocol notes](docs/protocol.md): what is known about the amp's USB-MIDI protocol, verified on real hardware.
- [macOS testing](docs/macos-testing.md): checklist for Mac users.

## Development

```sh
sudo pacman -S --needed alsa-lib alsa-utils uv    # Arch / Manjaro; use your distribution's equivalents
uv sync
uv run pytest                                     # no amplifier needed
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## License

GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`); see `LICENSE`. Protocol facts were learned from the
reference projects listed in `docs/protocol.md`; no code was copied from them.
