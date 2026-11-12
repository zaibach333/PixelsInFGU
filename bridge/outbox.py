"""Reads PixelsFGU_outbox.json, written by the FGU extension.

It lists the physical dice FGU is currently waiting on, e.g.
    {"version":1,"waiting":["d20","d20"]}
so the bridge can blink those dice.
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

    def reset(self) -> None:
        """Forget stale requests from a previous FGU session."""
        self.waiting = []
        try:
            self._mtime = self.path.stat().st_mtime_ns
        except OSError:
            self._mtime = None

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
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False  # mid-write; try again next poll
        waiting = doc.get("waiting") or []
        if not isinstance(waiting, list):
            waiting = []
        waiting = [str(d) for d in waiting]
        changed = waiting != self.waiting
        self.waiting = waiting
        return changed
