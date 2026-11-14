"""The inbox file shared between the bridge and the FGU extension.

The bridge rewrites the whole file atomically on every change. The FGU
extension polls it and processes every roll whose `seq` is greater than the
last one it handled. A new `session` id tells the extension that the bridge
restarted and sequence numbers began again. See docs/protocol.md.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

INBOX_FILENAME = "PixelsFGU_inbox.json"
FORMAT_VERSION = 1
MAX_ROLLS_KEPT = 50

# Pixels die type -> FGU die type.
_FGU_DIE = {
    "d4": "d4",
    "d6": "d6",
    "d6pipped": "d6",
    "d8": "d8",
    "d10": "d10",
    "d00": "d00",
    "d12": "d12",
    "d20": "d20",
}


def fgu_die_type(die_type: str) -> str | None:
    """Pixels die type -> FGU die type, or None if FGU can't use it."""
    return _FGU_DIE.get(die_type)


def to_fgu(die_type: str, face: int) -> tuple[str, int] | None:
    """Convert a Pixels face value to an FGU (die, value) pair.

    d10 faces are 0..9 and become 1..10 (0 counts as 10).
    d00 stays 0..90 and is only useful as the tens die of a d100.
    Returns None for dice FGU can't use directly (e.g. fudge, unknown).
    """
    die = _FGU_DIE.get(die_type)
    if die is None:
        return None
    if die == "d10":
        return die, (10 if face == 0 else face)
    return die, face


class Inbox:
    def __init__(self, data_dir: Path, on_roll=None):
        self.on_roll = on_roll  # called after each roll is written (e.g. to nudge FGU)
        self.path = Path(data_dir) / INBOX_FILENAME
        self.session = uuid.uuid4().hex
        self.seq = 0
        self.rolls: list[dict] = []
        self.dice: dict[str, dict] = {}
        self.running = True
        self._lock = threading.Lock()

    def set_die(self, key: str, **fields) -> None:
        with self._lock:
            self.dice.setdefault(key, {}).update(fields)
            self._write()

    def heartbeat(self) -> None:
        """Rewrite the file so `updated` stays fresh; FGU treats a stale file as a dead bridge."""
        with self._lock:
            self._write()

    def stop(self) -> None:
        """Called on exit so FGU stops routing rolls to the bridge's dice."""
        with self._lock:
            if not self.running:
                return
            self.running = False
            for die in self.dice.values():
                die["connected"] = False
            self._write()

    def add_roll(self, pixel_name: str, die_type: str, face: int) -> dict | None:
        converted = to_fgu(die_type, face)
        if converted is None:
            return None
        die, value = converted
        with self._lock:
            self.seq += 1
            roll = {
                "seq": self.seq,
                "die": die,
                "value": value,
                "face": face,
                "pixel": pixel_name,
                "time": round(time.time(), 3),
            }
            self.rolls.append(roll)
            del self.rolls[:-MAX_ROLLS_KEPT]
            self._write()
        if self.on_roll:
            self.on_roll()
        return roll

    def add_percentile(self, pixel_name: str, tens: int, units: int) -> dict:
        """A d00 (0..90) and a d10 face (0..9) rolled together: one d100 roll, 00+0 = 100."""
        value = tens + units or 100
        with self._lock:
            self.seq += 1
            roll = {
                "seq": self.seq,
                "die": "d100",
                "value": value,
                "face": value,
                "pixel": pixel_name,
                "time": round(time.time(), 3),
            }
            self.rolls.append(roll)
            del self.rolls[:-MAX_ROLLS_KEPT]
            self._write()
        if self.on_roll:
            self.on_roll()
        return roll

    def _write(self) -> None:
        doc = {
            "version": FORMAT_VERSION,
            "session": self.session,
            "updated": round(time.time(), 3),
            "running": self.running,
            "lastseq": self.seq,
            "dice": list(self.dice.values()),
            "rolls": self.rolls,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        # os.replace is atomic on the same volume, so FGU never sees a partial file.
        # FGU may hold the file open briefly while reading; retry a few times.
        for attempt in range(20):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.025 * (attempt + 1))
        raise PermissionError(f"Could not replace {self.path}")
