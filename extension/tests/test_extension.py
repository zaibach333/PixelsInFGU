"""Tests for the FGU extension's roll routing, run outside FGU with a Lua runtime (lupa).

Covers every die type Pixels makes, so behaviour can be checked without owning
each physical die. FGU APIs are stubbed in fgu_stubs.lua.
"""

import json
import time
import unittest
from pathlib import Path

from lupa import LuaRuntime

HERE = Path(__file__).parent
SCRIPT = HERE.parent / "PixelsFGU" / "scripts" / "manager_pixels.lua"
STUBS = HERE / "fgu_stubs.lua"


class Harness:
    def __init__(self, dice, running=True):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        make_env = self.lua.execute(STUBS.read_text(encoding="utf-8"))
        self.E = make_env(self._decode_json)
        self.T = self.E.T
        self.dice = dice
        self.running = running
        self.rolls = []
        self.seq = 0
        self._publish()

        chunk = self.lua.globals().load(SCRIPT.read_text(encoding="latin-1"), "@manager_pixels.lua", "t", self.E)
        chunk()
        self.E.onInit()
        self.E.onTabletopInit()

    # --- helpers

    def _to_lua(self, v):
        if isinstance(v, dict):
            return self.lua.table_from({k: self._to_lua(x) for k, x in v.items()})
        if isinstance(v, list):
            return self.lua.table_from([self._to_lua(x) for x in v])
        return v

    def _decode_json(self, s):
        return self._to_lua(json.loads(s))

    def _publish(self):
        self.T.inbox = json.dumps({
            "version": 1, "session": "s1", "updated": time.time(), "running": self.running,
            "lastseq": self.seq,
            "dice": [{"name": f"P{i}", "die": d, "connected": True, "state": "connected"}
                     for i, d in enumerate(self.dice)],
            "rolls": self.rolls,
        })

    def request(self, *dice, mod=0):
        """Simulate FGU starting a roll (what ActionsManager.roll receives)."""
        r = self._to_lua({"sType": "attack", "sDesc": "Test", "nMod": mod,
                          "aDice": [{"type": d} for d in dice]})
        self.E.ActionsManager.roll(None, None, r)
        return r

    def physical(self, die, value, face=None):
        """Simulate the bridge writing a Pixels roll, then waking FGU."""
        self.seq += 1
        self.rolls.append({"seq": self.seq, "die": die, "value": value,
                           "face": value if face is None else face, "pixel": "P"})
        self._publish()
        self.E.onWakeup()

    def submitted(self):
        # item access: `.values` would hit lupa's table method, not the field
        return [list(s["values"].values()) for s in self.T.submitted.values()]

    def pending_values(self, entry_index=1):
        entry = self.T.main.entries[entry_index]
        return [s.value.getValue() for s in entry.slots.values()]

    def waiting(self):
        return json.loads(self.T.outbox)["waiting"] if self.T.outbox else []


class EveryDieType(unittest.TestCase):
    def test_standard_dice_fill_and_submit(self):
        for die, value in [("d4", 3), ("d6", 6), ("d8", 1), ("d12", 11), ("d20", 20)]:
            with self.subTest(die=die):
                h = Harness([die])
                h.request(die)
                self.assertEqual(h.waiting(), [die])
                h.physical(die, value)
                self.assertEqual(h.submitted(), [[value]])
                self.assertEqual(h.waiting(), [])
                self.assertTrue(h.T.main.closed, "empty manual roll window should close")

    def test_d10_ten(self):
        h = Harness(["d10"])
        h.request("d10")
        h.physical("d10", 10, face=0)   # Pixels d10 shows 0, which is 10
        self.assertEqual(h.submitted(), [[10]])

    def test_d100_from_d00_and_d10(self):
        for first, second, expected in [
            (("d00", 70, 70), ("d10", 5, 5), 75),
            (("d10", 5, 5), ("d00", 70, 70), 75),
            (("d00", 0, 0), ("d10", 10, 0), 100),   # 00 + 0 = 100
            (("d00", 0, 0), ("d10", 7, 7), 7),
        ]:
            with self.subTest(first=first, second=second):
                h = Harness(["d00", "d10"])
                h.request("d100")
                self.assertEqual(sorted(h.waiting()), ["d00", "d10"])
                h.physical(*first)
                self.assertEqual(h.submitted(), [])
                h.physical(*second)
                self.assertEqual(h.submitted(), [[expected]])

    def test_d100_without_both_dice_is_digital(self):
        h = Harness(["d10"])   # no d00
        h.request("d100", "d10")
        values = h.pending_values()
        self.assertTrue(1 <= values[0] <= 100)
        self.assertEqual(values[1], 0)
        h.physical("d10", 4)
        self.assertEqual(h.submitted()[0][1], 4)

    def test_plain_d10_slot_wins_over_d100_units(self):
        h = Harness(["d00", "d10"])
        h.request("d100", "d10")
        h.physical("d10", 3)
        self.assertEqual(h.pending_values(), [0, 3])

    def test_pipped_d6_reported_as_d6(self):
        # The bridge maps Pixels "d6pipped" to "d6"; FGU only ever sees d6.
        h = Harness(["d6"])
        h.request("d6", "d6")
        h.physical("d6", 2)
        h.physical("d6", 5)
        self.assertEqual(h.submitted(), [[2, 5]])

    def test_negative_dice(self):
        h = Harness(["d6"])
        h.request("-d6")
        h.physical("d6", 4)
        self.assertEqual(h.submitted(), [[4]])  # CoreRPG's processOK applies the sign


class RulesetPatterns(unittest.TestCase):
    """Roll shapes used by the d20 rulesets the extension declares."""

    def test_string_dice_entries(self):
        # PFRPG2 builds some rolls as aDice = { "d20" } (strings, not tables)
        h = Harness(["d20"])
        r = h._to_lua({"sType": "misschance", "sDesc": "Flat", "nMod": 0, "aDice": ["d20"]})
        h.E.ActionsManager.roll(None, None, r)
        h.physical("d20", 12)
        self.assertEqual(h.submitted(), [[12]])

    def test_skinned_dice_entries(self):
        # DiceRollManager.getActorDice adds skin data but keeps type
        h = Harness(["d20"])
        r = h._to_lua({"sType": "attack", "sDesc": "Atk", "nMod": 3,
                       "aDice": [{"type": "d20", "iconcolor": "FF0000", "dicebodycolor": "00FF00"}]})
        h.E.ActionsManager.roll(None, None, r)
        h.physical("d20", 7)
        self.assertEqual(h.submitted(), [[7]])

    def test_ruleset_replaced_roll_still_used_as_fallback(self):
        # 2E swaps ActionsManager.roll for its own before tabletop init;
        # our wrapper must fall through to that replacement, not CoreRPG's.
        h = Harness.__new__(Harness)
        h.lua = LuaRuntime(unpack_returned_tuples=True)
        h.E = h.lua.execute(STUBS.read_text(encoding="utf-8"))(h._decode_json)
        h.T = h.E.T
        h.dice, h.running, h.rolls, h.seq = ["d20"], True, [], 0
        h._publish()
        h.lua.globals().load(SCRIPT.read_text(encoding="latin-1"), "@m", "t", h.E)()
        calls = []
        h.E.ActionsManager.roll = lambda *a: calls.append("adnd_roll")
        h.E.onInit()
        h.E.onTabletopInit()
        h.request("d8")
        self.assertEqual(calls, ["adnd_roll"])

    def test_disables_itself_without_corerpg_apis(self):
        h = Harness.__new__(Harness)
        h.lua = LuaRuntime(unpack_returned_tuples=True)
        h.E = h.lua.execute(STUBS.read_text(encoding="utf-8"))(h._decode_json)
        h.E.ManualRollManager = None
        h.lua.globals().load(SCRIPT.read_text(encoding="latin-1"), "@m", "t", h.E)()
        h.E.onInit()
        h.E.onTabletopInit()  # must not raise
        self.assertTrue(any("disabled" in s for s in h.E.T.console.values()))


class Routing(unittest.TestCase):
    def test_unowned_dice_go_to_normal_3d_dice(self):
        h = Harness(["d20"])
        h.request("d6", "d6")
        self.assertEqual(len(h.T.originalRolls), 1)
        self.assertIsNone(h.T.main)

    def test_mixed_roll_fills_unowned_digitally(self):
        h = Harness(["d20"])
        h.request("d20", "d6")
        values = h.pending_values()
        self.assertEqual(values[0], 0)
        self.assertTrue(1 <= values[1] <= 6)
        self.assertEqual(h.waiting(), ["d20"])
        h.physical("d20", 17)
        self.assertEqual(h.submitted()[0][0], 17)

    def test_advantage_needs_two_d20_rolls(self):
        h = Harness(["d20"])
        h.request("d20", "d20")
        h.physical("d20", 4)
        self.assertEqual(h.submitted(), [])
        h.physical("d20", 18)
        self.assertEqual(h.submitted(), [[4, 18]])

    def test_oldest_pending_roll_fills_first(self):
        h = Harness(["d20"])
        h.request("d20")
        h.request("d20")
        h.physical("d20", 1)
        h.physical("d20", 2)
        self.assertEqual(h.submitted(), [[1], [2]])

    def test_pixels_window_cannot_be_typed_into(self):
        h = Harness(["d20"])
        h.request("d20", "d6")
        entry = h.T.main.entries[1]
        self.assertTrue(all(s.value.readonly for s in entry.slots.values()))
        self.assertFalse(entry.button_ok.visible)
        self.assertFalse(entry.button_fauxroll.visible)

    def test_unrequested_roll_goes_to_chat(self):
        h = Harness(["d8"])
        h.physical("d8", 6)
        self.assertEqual(len(h.T.resolutions), 1)
        die = h.T.resolutions[1].aDice[1]
        self.assertEqual((die.type, die.result), ("d8", 6))

    def test_stopped_bridge_means_normal_dice(self):
        h = Harness(["d20"], running=False)
        h.request("d20")
        self.assertEqual(len(h.T.originalRolls), 1)

    def test_sleeping_die_still_counts(self):
        h = Harness([])
        h.T.inbox = json.dumps({"version": 1, "session": "s1", "updated": time.time(), "running": True,
                                "lastseq": 0, "rolls": [],
                                "dice": [{"name": "P", "die": "d20", "connected": False, "state": "asleep"}]})
        h.request("d20")
        self.assertEqual(len(h.T.originalRolls), 0)
        self.assertEqual(h.waiting(), ["d20"])

    def test_rolls_from_before_fgu_started_are_ignored(self):
        h = Harness(["d20"])
        h.rolls.append({"seq": 0, "die": "d20", "value": 9, "face": 9, "pixel": "P"})
        h.request("d20")
        h.E.onWakeup()
        self.assertEqual(h.submitted(), [])


if __name__ == "__main__":
    unittest.main()
