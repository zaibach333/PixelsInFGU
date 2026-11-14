"""Pair a d00 and a d10 rolled together into one d100 roll.

Only for rolls made while FGU isn't waiting on anything (free rolls): a d00
(00-90) is only ever half of a percentile roll, so a d00 and a d10 landing
within PAIR_WINDOW seconds of each other become a single d100. Two d10s are
never paired. When FGU *is* waiting (it shows a d100 box, or d10 boxes), rolls
pass straight through and the extension decides from the boxes on screen.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

log = logging.getLogger("pixels-bridge")

PAIR_WINDOW = 2.0
PERCENTILE_TYPES = ("d00", "d10")


class PercentilePairer:
    def __init__(self, inbox, waiting: Callable[[], list[str]], owned_types: Callable[[], set[str]],
                 window: float = PAIR_WINDOW):
        self.inbox = inbox
        self.waiting = waiting            # dice FGU is waiting on (from the outbox)
        self.owned_types = owned_types    # Pixels die types the user has
        self.window = window
        self._held = None                 # (pixel, die_type, face)
        self._timer = None

    def _should_pair(self, die_type: str) -> bool:
        if die_type not in PERCENTILE_TYPES:
            return False
        owned = self.owned_types()
        return "d00" in owned and "d10" in owned and not self.waiting()

    def add(self, pixel: str, die_type: str, face: int) -> dict | None:
        """Record a roll. Returns the inbox roll written now, or None if held."""
        if not self._should_pair(die_type):
            self.flush()
            return self.inbox.add_roll(pixel, die_type, face)

        if self._held and self._held[1] != die_type:
            other_pixel, other_type, other_face = self._held
            self._cancel_timer()
            self._held = None
            tens, units = (face, other_face) if die_type == "d00" else (other_face, face)
            log.debug("Paired d00 %s with d10 %s", tens, units)
            return self.inbox.add_percentile(f"{other_pixel} + {pixel}", tens, units)

        self.flush()  # a second die of the same type: the first one stands alone
        self._held = (pixel, die_type, face)
        try:
            self._timer = asyncio.get_running_loop().call_later(self.window, self.flush)
        except RuntimeError:  # no event loop (tests, odd callers): don't hold
            self.flush()
            return None
        log.debug("Holding %s %s for up to %.1fs in case it's half of a d100", die_type, face, self.window)
        return None

    def flush(self) -> None:
        """Write a held roll on its own (its partner never came)."""
        self._cancel_timer()
        if self._held:
            pixel, die_type, face = self._held
            self._held = None
            roll = self.inbox.add_roll(pixel, die_type, face)
            if roll:
                log.info("ROLL  %-20s %s = %s  (#%d)", pixel, roll["die"], roll["value"], roll["seq"])

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
