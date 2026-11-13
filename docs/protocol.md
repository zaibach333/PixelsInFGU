# Bridge ↔ extension protocol

FGU's sandboxed Lua can't open sockets, so the bridge and the extension communicate
through two small JSON files in the FGU data folder, plus a Shift-key nudge.

## Inbox (bridge → FGU)

The bridge writes `PixelsFGU_inbox.json` in the root of the FGU data folder
(`File.getDataFolder()` on the FGU side). The whole file is rewritten atomically
(write `.tmp`, then rename) on every change.

```json
{
  "version": 1,
  "session": "ee36f9338ba24cffb0cc1ef7a45b5b50",
  "updated": 1794417719.178,
  "running": true,
  "lastseq": 3,
  "dice": [
    { "name": "Bob", "die": "d20", "pixels_type": "d20", "battery": 87, "connected": false, "state": "asleep" }
  ],
  "rolls": [
    { "seq": 3, "die": "d20", "value": 17, "face": 17, "pixel": "Bob", "time": 1794417719.178 }
  ]
}
```

| Field | Meaning |
|---|---|
| `session` | Random id per bridge run. A change means `seq` restarted at 1. |
| `updated` | Unix time of the last write. The bridge heartbeats every 15 s; FGU treats a file older than 60 s as a dead bridge. |
| `running` | `false` once the bridge exits (including closing its window). |
| `dice[].die` | FGU die type, or `null` for dice FGU can't use (fudge). |
| `dice[].state` | `connected` or `asleep`. Sleeping dice still count as owned while the bridge runs. |
| `lastseq` | Highest `seq` written. On first read the extension skips up to here so old rolls are not replayed. |
| `rolls` | The last 50 rolls, oldest first. |
| `rolls[].die` | FGU die type: `d4 d6 d8 d10 d12 d20`, or `d00` (percentile tens die). |
| `rolls[].value` | FGU value. d10 is 1..10 (face 0 counts as 10). d00 is 0..90. |
| `rolls[].face` | Raw face as printed: d10 is 0..9, d00 is 0..90. Used to build d100 = tens + units (00 + 0 = 100). |

## Outbox (FGU → bridge)

The extension writes `PixelsFGU_outbox.json` with `File.saveTextFile` whenever the set of
physical dice it is waiting on changes:

```json
{"version":1,"waiting":["d20","d20"]}
```

The list has one entry per empty slot of a die type the user has connected. A d100 slot
appears as `d00` and/or `d10`. The bridge blinks connected dice of those types until the
list no longer contains them.

## Waking FGU

FGU's Lua has no timer, per-frame event or file watcher. After writing a roll, the bridge taps
Shift while FGU is the foreground window (`bridge/nudge.py` has one backend per OS). Without a
working nudge, the user tapping Shift in FGU does the same thing. The extension polls the inbox on the global
`Input` `onShift`/`onControl`/`onAlt` events, and whenever a manual roll window opens.

Any producer that writes this format can drive the extension, for example a Pixels-app
web-request receiver.
