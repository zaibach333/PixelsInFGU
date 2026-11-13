# PixelsInFGU

Roll physical [Pixels](https://gamewithpixels.com/) smart dice and have the results count in
[Fantasy Grounds Unity](https://www.fantasygrounds.com/). Modifiers, advantage, targeting, effects
and damage all work, because FGU resolves each roll exactly as it normally would.

> Not affiliated with Systemic Games (Pixels) or SmiteWorks (Fantasy Grounds).

## How it works

```
 Pixels dice  --Bluetooth-->  PixelsFGU Bridge  --PixelsFGU_inbox.json-->  FGU extension
                                    ^      <--PixelsFGU_outbox.json--       (dice FGU wants)
                                    +-- taps Shift so FGU notices the roll
```

1. You click an attack, save, damage roll, etc. in FGU.
2. If the roll includes a die type you own as a Pixel, FGU's **manual roll** window opens and
   your matching dice blink blue. Dice you don't own (e.g. the d6 damage when you only have
   d20s) are rolled digitally straight away. If you own none of the dice in the roll, FGU uses
   its normal 3D dice.
3. Roll your Pixels. The window fills in and submits itself.

You can't type values into the window while Pixels is handling a roll. Its **Roll** button
sends the whole roll to FGU's 3D dice instead, and **Cancel** works as usual. Pixels rolls made
with nothing pending go to chat as plain rolls.

Also works with the *Requested Rolls* extension: its roll requests appear in the same window and
fill from your dice.

## Supported rulesets

| Ruleset | Status |
|---|---|
| D&D 5E | Tested with physical dice |
| CoreRPG, 2E (AD&D), 3.5E, 4E, Pathfinder 1E (PFRPG), Pathfinder 2E (PFRPG2, PFRPG2-Legacy), Starfinder (SFRPG, SFRPG2) | Should work: they use CoreRPG's standard roll pipeline, which automated tests cover. Not yet tried in a live game. |
| Any other ruleset | The extension can be enabled everywhere. It works if the ruleset rolls through CoreRPG's `ActionsManager` and manual roll window (most do), and switches itself off if those are missing. |

If you play one of the untested rulesets, a quick report (works, or doesn't) helps a lot.

## Supported dice

| Pixels die | In FGU | Notes |
|---|---|---|
| d4, d6, d8, d12, d20 | same | |
| d6 (pipped) | d6 | |
| d10 | d10 | The face showing 0 counts as 10 |
| d00 (percentile) + d10 | d100 | Needs both. Roll them in either order: 00 + 0 = 100 |
| d6 Fudge | — | Not supported yet; ignored |

Every die type is covered by automated tests. Only d20s have been tested with physical dice so far.

## Requirements

- A computer with Bluetooth LE:

  | Platform | Status | Notes |
  |---|---|---|
  | Windows 10/11 | Tested | |
  | macOS 12+ (Apple silicon or Intel) | **Experimental** | Allow your terminal app under Privacy & Security → **Bluetooth** and → **Accessibility**. |
  | Linux x86-64 (BlueZ) | **Experimental** | Install `xdotool` for the Shift nudge. It needs X11; on pure Wayland, tap Shift in FGU yourself after rolling. |

- Fantasy Grounds Unity with one of the [supported rulesets](#supported-rulesets).
- Pixels dice disconnected from the Pixels phone app (a die talks to one app at a time).

## Install

1. From the [latest release](../../releases/latest), download the zip for your computer
   (**`PixelsInFGU-<version>-windows.zip`**, `-macos-arm64.zip` for Apple silicon,
   `-macos-x86_64.zip` for Intel Macs, or `-linux-x86_64.zip`) and
   unzip it. It contains the bridge, the extension and a quick-start guide. (The files are
   also attached separately.) You can check them first: see [SECURITY.md](SECURITY.md).
2. Copy `PixelsFGU.ext` into your FGU data folder's `extensions` folder. FGU shows the data
   folder under Settings; the defaults are `%APPDATA%\SmiteWorks\Fantasy Grounds` (Windows),
   `~/SmiteWorks/Fantasy Grounds` (macOS) and `~/.smiteworks/fgdata` (Linux).
3. Enable **Feature: Pixels Dice** when loading your campaign.
4. Pick up your Pixels to wake them, then run the bridge and leave it open: double-click
   `PixelsFGU-Bridge.exe` on Windows, or run `./PixelsFGU-Bridge` in a terminal on macOS/Linux.
   On macOS the first run needs `xattr -d com.apple.quarantine PixelsFGU-Bridge` (the app
   isn't notarized).

## Using it

- **FGU must be the active window** when a roll lands. If it isn't, the roll lands as soon
  as you click back into FGU. If the Shift nudge can't run (see [Requirements](#requirements)),
  tap Shift in FGU after rolling. If you always have to tap Shift, run the bridge with
  `--test-nudge` and follow what it prints.
- Dice that fall asleep still count as yours. The roll that wakes one is read straight from
  its Bluetooth broadcast.
- **Options → Pixels Dice:** use physical dice, submit automatically, auto-roll dice I don't
  own, post unrequested rolls to chat.
- **Chat commands:** `/pixels` (status, dice, battery), `/pixels probe` (diagnostics),
  `/pixels reset`.
- **Bridge options:** `--list` (show dice in range), `--names Bob Amy` (only these dice),
  `--simulate d20 d6` (no dice: type rolls like `d20 17`), `--data-dir <folder>` (if FGU's
  data folder isn't found automatically), `--test-nudge` (check that the Shift nudge reaches
  FGU), `--no-blink`, `--no-nudge`, `-v`.
- The bridge writes `PixelsFGU_bridge.log` in the FGU data folder, which is useful for bug reports.

## Run from source

```powershell
py -m venv bridge\.venv
bridge\.venv\Scripts\python -m pip install -r bridge\requirements.txt
bridge\.venv\Scripts\python bridge\pixels_bridge.py
bridge\.venv\Scripts\python tools\package_ext.py      # builds dist\PixelsFGU.ext
```

macOS / Linux:

```sh
python3 -m venv bridge/.venv
bridge/.venv/bin/python -m pip install -r bridge/requirements.txt
bridge/.venv/bin/python bridge/pixels_bridge.py       # add --data-dir if FGU's folder isn't found
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and releases, and
[docs/protocol.md](docs/protocol.md) for how the bridge and extension talk to each other.

## Known limitations

- macOS and Linux support is experimental and hasn't been tried with real dice yet. Reports welcome.
  The extension itself is the same on every platform.
- Player clients (each player running their own bridge) should work but haven't been tested.
- Fudge dice aren't supported.

## License

[MIT](LICENSE). Includes protocol details ported from the MIT-licensed Pixels SDK; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
