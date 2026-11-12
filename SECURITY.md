# Security

PixelsInFGU runs on your computer next to Fantasy Grounds and talks to your dice over Bluetooth.
This page lists everything it does, so you can check the claims against the source.

## What the bridge (`PixelsFGU-Bridge.exe`) does

| Area | Exactly what happens | Source |
|---|---|---|
| Bluetooth | Scans for Pixels dice, connects, and sends only these commands: *who are you*, *battery level*, *blink LEDs*. It never changes die settings, profiles or firmware. | `bridge/pixels_bridge.py`, `bridge/pixels_protocol.py` |
| Registry | Reads one value, `HKCU\Software\SmiteWorks\Fantasy Grounds\DataDir`, to find the FGU data folder. Writes nothing. | `default_data_dir()` |
| Files | In the FGU data folder only: writes `PixelsFGU_inbox.json` (and a `.tmp` beside it) and `PixelsFGU_bridge.log`; reads `PixelsFGU_outbox.json`. | `bridge/inbox.py`, `bridge/outbox.py` |
| Keyboard | After a roll, if `FantasyGrounds.exe` is the active window, it presses and releases **Shift** for about 60 ms so FGU notices the roll (FGU's scripting has no timer). If FGU isn't active, it posts the same Shift press to FGU's window. It reads only whether Shift is already held. It never records or reads other keys. | `bridge/nudge.py` |
| Windows/processes | Reads the process name of the active window and lists top-level windows to find FGU's. | `bridge/nudge.py` |
| Network | **None.** No internet access, telemetry or update checks. | (no networking code) |
| System | Needs no admin rights. Installs nothing, adds no autostart entry and runs no services. Closing it stops everything. | |

Antivirus tools sometimes flag single-file PyInstaller executables, and the simulated Shift
key press can look suspicious. If you'd rather not trust a binary, run the bridge from source
(see the README) or build the `.exe` yourself.

## What the FGU extension (`PixelsFGU.ext`) does

- Reads `PixelsFGU_inbox.json` and writes `PixelsFGU_outbox.json` in the FGU data folder,
  using FGU's own `File` API.
- Wraps `ActionsManager.roll` and `ManualRollManager.addRoll` so rolls go to the manual roll
  window when you have matching Pixels, and layers onto the `manualroll_entry` window.
- Dice you don't own physically are filled with Lua's `math.random`, not FGU's 3D dice. The
  window's **Roll** button still sends the whole roll to FGU's 3D dice.
- It has no network access. FGU's sandbox doesn't allow it.

## Verifying a release

Every release on GitHub is built by GitHub Actions from the tagged source
(`.github/workflows/release.yml`). Nothing is uploaded from a developer's machine.

1. **Checksums:** compare against `SHA256SUMS.txt` from the release. It covers the zip and
   both individual files:
   ```powershell
   Get-FileHash .\PixelsInFGU-*-windows.zip, .\PixelsFGU-Bridge.exe, .\PixelsFGU.ext -Algorithm SHA256
   ```
2. **Build provenance:** each file has a signed attestation linking it to the workflow run
   and commit that built it. With the [GitHub CLI](https://cli.github.com):
   ```powershell
   gh attestation verify .\PixelsFGU-Bridge.exe --repo zaibach333/PixelsInFGU
   gh attestation verify .\PixelsFGU.ext --repo zaibach333/PixelsInFGU
   ```
3. **Rebuild the extension yourself.** `PixelsFGU.ext` is reproducible: check out the release
   tag and run `python tools/package_ext.py`. The SHA-256 it prints must match the release.
4. **Build the bridge yourself.** Run `tools/build-bridge.ps1`, or skip the `.exe` and run
   `python bridge/pixels_bridge.py` directly.

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** button on the
repository's Security tab, not in a public issue.
