# Flatpak

Status: **builds and runs.** The manifest builds against Flathub's `org.kde.Platform//6.11` and
`io.qt.PySide.BaseApp//6.11` and was installed and tested on the author's machine (Linux, a THR5A connected): `doctor`,
MIDI, the amp's USB audio devices and the live stream all work inside the sandbox. The GUI itself was started
headless only. It is still the *local development* variant (it downloads Python packages while building), so it is not
ready for Flathub yet (see the end).

## Build and test locally

```sh
flatpak install --user flathub org.flatpak.Builder org.kde.Platform//6.11 org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
W=$HOME/.cache/thr-control-flatpak && mkdir -p $W
flatpak run --env=FLATPAK_USER_DIR=$HOME/.local/share/flatpak --command=flatpak-builder org.flatpak.Builder \
    --user --install --force-clean --state-dir=$W/state --disable-rofiles-fuse \
    $W/build-dir packaging/flatpak/io.github.bleaff.ThrControl.yaml
flatpak run io.github.bleaff.ThrControl
```

Notes from doing this for real:

- The first install downloads **about 8 GB** into `~/.local/share/flatpak` (the runtime, the SDK, Flatpak Builder, and graphics
  extensions pulled in alongside them). Remove it with `flatpak uninstall --user --delete-unused` and delete `$W`.
- Keep the state and build directories under your home folder: flatpak-builder runs build commands on the *host*, which cannot
  see a sandboxed `/tmp`.
- `--env=FLATPAK_USER_DIR=...` is needed because the Builder sandbox otherwise looks for the user installation in its own data folder
  and reports the SDK as "not installed".
- Do not let the build run as a background process that is cut off with its shell: it stops halfway through installing.

## Permissions

- `--device=all`: MIDI. The amp is reached through the ALSA sequencer, which a sandbox only gets with device access.
- `--filesystem=xdg-run/pipewire-0`: the PipeWire socket, for recording and the live response plot.
- `--filesystem=xdg-music`: recorded takes are saved in `~/Music/thr-control`. Without it the sandbox writes them to a
  throwaway filesystem and they are lost when the program exits (found by testing).
- No network and no access to the rest of the home folder: presets and measurements live in the app's own data folder
  (`~/.var/app/io.github.bleaff.ThrControl/`).

## Notes

- `python-rtmidi` is built from source with JACK disabled (`-Djack=false`), because the PyPI wheel links `libjack.so.0`.
- The runtime's PipeWire tools (`pw-record`, `pw-play`, `pw-dump`) are used as they are.

## Before submitting to Flathub

1. Replace the `--share=network` pip steps with offline sources (`flatpak-pip-generator` writes them with hashes).
2. Use a git tag as the source instead of `type: dir`.
3. Add screenshots and a homepage URL to the AppStream file, then run `appstreamcli validate`.
4. Pick the final runtime version.
