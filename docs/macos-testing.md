# Testing THR Control on a Mac

macOS support is **untested on real hardware**. The MIDI side should work through CoreMIDI and the audio side uses
PortAudio (`sounddevice`) instead of the Linux PipeWire tools, but nothing here has been run on a Mac with an amp yet. This is
a checklist for the first run. Please send back what each step printed, especially the failures.

## Install

```sh
# Python 3.12 or newer is required
git clone <repository-url> thr-control && cd thr-control
pipx install .          # or: uv tool install .
thr-control --version
```

## Steps (the amp connected by USB and switched on)

1. `thr-control doctor` — every line should be `OK`. Note which lines are not, and what they say.
2. `thr-control probe --list` — the amp should appear under "Detected THR devices". **Copy the exact port names**: macOS
   names them differently from Linux, and detection relies on "THR5" (or THR10 / THR5A ...) appearing in the name.
3. `thr-control show` — prints the amp's current settings (this sends one settings request).
4. `thr-control set master 40` is a dry run; add `--yes` to change the amp, then `thr-control show` to check it, and set it
   back. Turning a knob on the amp while `thr-control probe` runs should print messages.
5. `thr-control-gui` — connect, move a knob in the app and on the amp; check presets, the plot and the diagnostics tab.
6. Audio (the first attempt may trigger macOS's *microphone permission* prompt for Terminal / the app: allow it):
   - `thr-control audio devices` — look for the amp as an input with 4 channels and as an output.
   - `thr-control audio record --seconds 10 --name mactest` while you play. It should report four channels; the
     processed sound is expected on channels 1+2 and the dry guitar on 3+4, as on Linux. **This channel layout is the main
     thing to confirm on macOS.**
   - `thr-control audio live --seconds 30` while you play, and the "Measure live" button in the app.

## What to send back

The output of each step, the macOS version, the Mac's chip (Intel or Apple silicon), and anything that looked wrong.
If `doctor` or `probe` misses the amp, include the output of `thr-control probe --list` and of
`python3 -c "import mido; print(mido.get_input_names())"`.

## Known unknowns

- CoreMIDI port names (see step 2).
- Whether macOS exposes all four capture channels of the amp, and at 48 kHz.
- Packaging as a `.app`/DMG, code signing and notarization are not done yet.
