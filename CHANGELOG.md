# Changelog

## Unreleased

- **Experimental macOS and Linux support** for the bridge. Releases now include builds for
  Windows, macOS (Apple silicon) and Linux (x86-64).
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
