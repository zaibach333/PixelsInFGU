# Changelog

## Unreleased

- **d100:** a d00 and a d10 rolled together with nothing pending now post one d100 to chat
  (before, only the d10 showed). A lone d00 shows a hint instead of nothing. Two d10s are never
  read as a d100.
- **d100 with only a d10:** FGU's d100 rolls ask for the d10 twice, tens then units.
- **macOS Shift nudge:** the bridge now tries several ways of sending Shift (including sending
  it straight to FGU) and keeps the first one FGU confirms, using a wake-up count the extension
  reports. `--test-nudge` lists which ways work; `--nudge-method` forces one.

## 0.3.0

- The extension can be enabled in any ruleset, not just the listed d20 ones. It switches itself
  off where CoreRPG's roll APIs are missing.
- macOS Shift nudge: the key event now carries the same flags as a real left-Shift press, and
  the bridge asks for Accessibility permission itself and starts nudging once it's granted
  (no restart). Linux likewise picks up `xdotool` once it's installed.
- New `--test-nudge` option checks the nudge step by step: permission, which app is in front,
  and one Shift tap you can confirm with `/pixels` (the *wake-ups* count).
- The bridge log names the front app when it's waiting for FGU, to help diagnose the nudge.

## 0.2.0

- **Experimental macOS and Linux support** for the bridge. Releases now include builds for
  Windows, macOS (Apple silicon and Intel) and Linux (x86-64).
  - macOS: Shift nudge via CoreGraphics (needs Accessibility permission); finds FGU's
    data folder at `~/SmiteWorks/Fantasy Grounds`.
  - Linux: Shift nudge via `xdotool` on X11; data folder `~/.smiteworks/fgdata`.
  - Closing the terminal marks the bridge stopped, so FGU switches back to normal dice.
- CI runs the tests on Windows, macOS and Linux.

## 0.1.0

First public version.

- Bridge connects to Pixels dice over Bluetooth LE and writes rolls for FGU.
- Rolls with a die type you own open FGU's manual roll window and fill from your physical dice.
  Unowned dice are rolled digitally; rolls with no owned dice use FGU's 3D dice.
- Manual entry is locked while Pixels handles a roll; **Roll** falls back to FGU's 3D dice.
- Dice FGU is waiting on blink blue.
- Sleeping dice still count; the roll that wakes a die is read from its advertisement.
- d100 from a d00 + d10 pair.
- Works with the Requested Rolls extension.
- Rulesets: 5E (tested); CoreRPG, 2E, 3.5E, 4E, PFRPG, PFRPG2, PFRPG2-Legacy, SFRPG, SFRPG2
  (expected to work). The extension switches itself off on rulesets without CoreRPG's roll APIs.
- Diagnostics: `/pixels`, `/pixels probe`, `/pixels reset`, bridge log file.
