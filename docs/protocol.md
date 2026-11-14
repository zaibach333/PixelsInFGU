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
| `rolls[].die` | FGU die type: `d4 d6 d8 d10 d12 d20`, `d00` (percentile tens die), or `d100` (a d00 and d10 the bridge paired; see below). |
| `rolls[].value` | FGU value. d10 is 1..10 (face 0 counts as 10). d00 is 0..90. d100 is 1..100. |
| `rolls[].face` | Raw face as printed: d10 is 0..9, d00 is 0..90. Used to build d100 = tens + units (00 + 0 = 100). |

## Outbox (FGU → bridge)

The extension writes `PixelsFGU_outbox.json` with `File.saveTextFile` whenever the dice it
is waiting on change, and on every wake-up:

```json
{"version":1,"waiting":["d20","d20"],"wakeups":12}
```

`waiting` has one entry per empty slot of a die type the user has connected. A d100 slot
appears as `d00` (tens) and `d10` (units), or as two `d10`s when the user has no d00 (the d10
is rolled twice, tens first). The bridge blinks connected dice of those types until the list
no longer contains them.

`wakeups` counts the extension's Shift/Ctrl/Alt wake-ups. The bridge compares it before and
after a nudge to confirm the nudge arrived (older extensions omit it).

## Percentile dice

- **FGU waiting on a roll:** rolls pass straight through and the extension fills boxes by type.
  Plain `d10` boxes fill before a `d100` box takes a d10, so `2d10` is never read as a d100.
- **Nothing waiting (free rolls):** if the user owns a d00 and a d10, the bridge holds a d00 or
  d10 roll for up to 2 s; if the other one lands in that time it writes a single `d100` roll.
  Two d10s are never paired. A d00 on its own just shows a hint in chat.

## Waking FGU

FGU's Lua has no timer, per-frame event or file watcher. After writing a roll, the bridge taps
Shift while FGU is the foreground window (`bridge/nudge.py` has one backend per OS). On macOS
there are several ways to send that Shift; the bridge tries them in turn until the outbox's
`wakeups` count confirms one reached FGU, then keeps it. Without a working nudge, the user
tapping Shift in FGU does the same thing. The extension polls the inbox on the global
`Input` `onShift`/`onControl`/`onAlt` events, and whenever a manual roll window opens.

Any producer that writes this format can drive the extension, for example a Pixels-app
web-request receiver.
