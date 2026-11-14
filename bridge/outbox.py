"""Reads PixelsFGU_outbox.json, written by the FGU extension.

It lists the physical dice FGU is currently waiting on, and how many times the
extension has been woken by a Shift/Ctrl/Alt event, e.g.
    {"version":1,"waiting":["d20","d20"],"wakeups":12}
so the bridge can blink those dice and check that its Shift nudge arrives.
"""

from __future__ import annotations

import json
from pathlib import Path

OUTBOX_FILENAME = "PixelsFGU_outbox.json"


class OutboxWatcher:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / OUTBOX_FILENAME
        self._mtime = None
        self.waiting: list[str] = []
        self.wakeups: int | None = None   # None: extension too old to report it

    def reset(self) -> None:
        """Forget stale requests from a previous FGU session."""
        self.waiting = []
        try:
            self._mtime = self.path.stat().st_mtime_ns
        except OSError:
            self._mtime = None
            return
        # The wake-up count is only compared before/after a nudge, so an old value is fine.
        try:
            wakeups = json.loads(self.path.read_text(encoding="utf-8-sig")).get("wakeups")
            self.wakeups = wakeups if isinstance(wakeups, int) else None
        except (OSError, ValueError, AttributeError):
            pass

    def poll(self) -> bool:
        """Re-read the file if it changed. Returns True when `waiting` changed."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            # utf-8-sig: FGU's File.saveTextFile starts the file with a byte-order mark.
            doc = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return False  # mid-write; try again next poll
        waiting = doc.get("waiting") or []
        if not isinstance(waiting, list):
            waiting = []
        waiting = [str(d) for d in waiting]
        wakeups = doc.get("wakeups")
        self.wakeups = wakeups if isinstance(wakeups, int) else None
        changed = waiting != self.waiting
        self.waiting = waiting
        return changed

    def current_wakeups(self) -> int | None:
        """Latest wake-up count from the extension (re-reads the file if it changed)."""
        self.poll()
        return self.wakeups
