# Firmware metadata and local storage

This directory distributes documentation and a [SHA-256 manifest](checksums.sha256) only, **no firmware**.
These are reference fingerprints from one successful THR5A → THR5 V2 experiment on Manjaro Linux, not universal guarantees
for every firmware version, device or hardware revision.

| Manifest filename | Format | Size (bytes) | Meaning |
| --- | --- | ---: | --- |
| `thr5a_original.bin` | Raw main firmware | 1048576 | Original image from the tested THR5A |
| `thr5_v2_extracted.bin` | Raw main firmware | 1048576 | Decoded THR5 V2 image; not the tested playback file |
| `THR_Firm_ver200main.bin` | Standard MIDI File | 1252328 | Official Yamaha update resource actually transmitted |

The backup guide names its two independent dumps `thr5a_backup_1.bin` and `thr5a_backup_2.bin`.
`thr5a_original.bin` in the manifest is a reference name for that experiment's original image, not an additional required dump.
Your original firmware may legitimately have a different hash; record its actual hash and require two identical dumps.

Use the [cross-flashing guide](../docs/firmware-thr5a-to-thr5-v2.md) before any update and read the
[recovery limitations](../docs/firmware-recovery.md). Restoring the original image is **untested on THR5A**.

## Obtain firmware privately

Download updates from [Yamaha's official THR downloads](https://usa.yamaha.com/products/musical_instruments/guitars_basses/amps_accessories/thr/downloads.html).
Yamaha's [V2 updater restrictions](https://europe.yamaha.com/en/support/updates/61280-en.html) exclude THR5A.
Dump your own original device as described in the guide.

Keep all artifacts in `~/yamaha-thr5a-backup` outside the source checkout, or in the gitignored directories
`firmware/local/`, `firmware/downloads/`, `firmware/extracted/`, `firmware/backups/` and `firmware/recovery/`.
Ignore rules also catch common firmware filenames, update archives, executables and binary patch formats.
Ignore rules are a convenience: review `git status` and staged files, and never force-add proprietary artifacts.

The manifest uses filenames relative to the directory containing your private files. To check all three reference artifacts
when those exact filenames exist locally, run this **from that private directory**, replacing the manifest path:

```bash
sha256sum -c /absolute/path/to/THR_Edit/firmware/checksums.sha256
```

Missing files will be reported as missing. A mismatch requires investigation; hashes identify bytes and do not establish
compatibility, download authenticity or a proven recovery method. The MIDI container and decoded raw image have different
sizes and hashes. Compare `thr5a_backup_1.bin` with the original reference entry manually rather than renaming your only backup.

## Distribution and licensing

Yamaha firmware is proprietary. This project's AGPL license does **not** grant rights to distribute Yamaha firmware.
Do not commit or upload to GitHub Releases original dumps, extracted images, update archives, updater executables,
recovery MIDI files, or binary patches derived from Yamaha firmware without distribution rights. Keep backups private.
Follow the terms accompanying the official download.

Michael Forney's independent [thr10 research and tools](https://github.com/michaelforney/thr10) made the dump and conversion
workflow possible. They remain an external dependency with their own license; no implementation code is copied here.
