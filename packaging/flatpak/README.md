# Flatpak

Status: **draft, not built yet.** The manifest is written against Flathub's `org.kde.Platform//6.11` and
`io.qt.PySide.BaseApp//6.11` (both exist on Flathub). Nobody has built or run it.

## Build and test locally

```sh
flatpak install --user flathub org.flatpak.Builder org.kde.Platform//6.11 org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
flatpak run --command=flatpak-builder org.flatpak.Builder --user --install --force-clean \
    build-dir packaging/flatpak/io.github.bleaff.ThrControl.yaml
flatpak run io.github.bleaff.ThrControl
```

That downloads roughly 2 to 3 GB into `~/.local/share/flatpak` (remove it again with `flatpak uninstall --user --delete-data`).

## Permissions

- `--device=all` is needed for MIDI: the amp is reached through the ALSA sequencer, which a sandbox only gets with
  device access. No other devices are touched.
- No network, no home-folder access: presets and measurements live in the app's own data folder.

## Known limits of the sandboxed version

- **Recording and the live response plot are unavailable inside the sandbox.** They need PipeWire's command-line tools
  (not in the runtime) or a PortAudio that can pick the amp's 4-channel input (not possible through PulseAudio). The app
  reports this instead of failing. A Flatpak-capable audio path (for example Qt Multimedia) is future work.
- `python-rtmidi` is built from source with JACK disabled, because the PyPI wheel needs `libjack.so.0`.

## Before submitting to Flathub

1. Replace the `--share=network` pip steps with offline sources (`flatpak-pip-generator` writes them with hashes).
2. Use a git tag as the source instead of `type: dir`.
3. Add screenshots and a homepage URL to the AppStream file, then run `appstreamcli validate`.
4. Pick the final runtime version.
