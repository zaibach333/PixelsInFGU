import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nudge
from inbox import Inbox
from outbox import OUTBOX_FILENAME, OutboxWatcher
from percentile import PercentilePairer


class FakeInbox:
    def __init__(self):
        self.rolls = []

    def add_roll(self, pixel, die_type, face):
        value = 10 if die_type == "d10" and face == 0 else face
        roll = {"die": die_type, "value": value, "seq": len(self.rolls) + 1, "pixel": pixel}
        self.rolls.append(roll)
        return roll

    def add_percentile(self, pixel, tens, units):
        roll = {"die": "d100", "value": tens + units or 100, "seq": len(self.rolls) + 1, "pixel": pixel}
        self.rolls.append(roll)
        return roll


def run_pairer(steps, waiting=(), owned=("d00", "d10", "d20"), window=0.2, settle=None):
    """steps: list of (die_type, face, delay_after). Returns the inbox rolls."""
    inbox = FakeInbox()

    async def go():
        p = PercentilePairer(inbox, lambda: list(waiting), lambda: set(owned), window=window)
        for die, face, delay in steps:
            p.add("pixel", die, face)
            await asyncio.sleep(delay)
        await asyncio.sleep(window * 2 if settle is None else settle)

    asyncio.run(go())
    return [(r["die"], r["value"]) for r in inbox.rolls]


class PercentilePairingTests(unittest.TestCase):
    def test_d00_and_d10_together_make_one_d100(self):
        self.assertEqual(run_pairer([("d00", 70, 0.01), ("d10", 3, 0)]), [("d100", 73)])
        self.assertEqual(run_pairer([("d10", 3, 0.01), ("d00", 70, 0)]), [("d100", 73)])

    def test_00_and_0_is_100(self):
        self.assertEqual(run_pairer([("d00", 0, 0.01), ("d10", 0, 0)]), [("d100", 100)])

    def test_two_d10s_are_never_a_d100(self):
        self.assertEqual(run_pairer([("d10", 3, 0.01), ("d10", 7, 0)]), [("d10", 3), ("d10", 7)])

    def test_lone_die_is_released_after_the_window(self):
        self.assertEqual(run_pairer([("d10", 4, 0)]), [("d10", 4)])
        self.assertEqual(run_pairer([("d00", 40, 0)]), [("d00", 40)])

    def test_far_apart_rolls_stay_separate(self):
        self.assertEqual(run_pairer([("d00", 40, 0.5), ("d10", 2, 0)]), [("d00", 40), ("d10", 2)])

    def test_no_pairing_while_fgu_waits(self):
        # FGU asked for 2d10 (or anything): rolls go straight through, the extension decides.
        rolls = run_pairer([("d00", 70, 0.01), ("d10", 3, 0)], waiting=["d10", "d10"])
        self.assertEqual(rolls, [("d00", 70), ("d10", 3)])

    def test_no_pairing_without_a_d00(self):
        self.assertEqual(run_pairer([("d10", 3, 0)], owned=("d10",), window=5, settle=0.05), [("d10", 3)])

    def test_other_dice_pass_straight_through(self):
        self.assertEqual(run_pairer([("d20", 17, 0)], window=5, settle=0.05), [("d20", 17)])


class InboxPercentileTests(unittest.TestCase):
    def test_add_percentile_writes_a_d100(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(Path(tmp))
            roll = inbox.add_percentile("A + B", 90, 9)
            self.assertEqual((roll["die"], roll["value"]), ("d100", 99))
            self.assertEqual(inbox.add_percentile("A + B", 0, 0)["value"], 100)
            doc = json.loads(inbox.path.read_text(encoding="utf-8"))
            self.assertEqual([r["die"] for r in doc["rolls"]], ["d100", "d100"])


class OutboxWakeupTests(unittest.TestCase):
    def test_reads_wakeups_including_at_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / OUTBOX_FILENAME
            path.write_text('{"version":1,"waiting":[],"wakeups":5}', encoding="utf-8")
            w = OutboxWatcher(Path(tmp))
            w.reset()
            self.assertEqual(w.current_wakeups(), 5)
            path.write_text('{"version":1,"waiting":["d20"],"wakeups":6}', encoding="utf-8")
            import os, time
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
            self.assertEqual(w.current_wakeups(), 6)

    def test_old_extension_reports_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / OUTBOX_FILENAME).write_text('{"version":1,"waiting":[]}', encoding="utf-8")
            w = OutboxWatcher(Path(tmp))
            w.reset()
            self.assertIsNone(w.current_wakeups())


class FakeFgu:
    """Backend whose FGU only reacts to some methods; bumps a wake-up counter."""
    name = "fake"

    def __init__(self, methods, works):
        self.methods = methods
        self.works = works
        self.wakeups = 0
        self.used = []

    def problem(self): return None
    def front_app(self): return "FantasyGrounds"
    def fgu_is_foreground(self): return True
    def user_holding_shift(self): return False
    def post_background_nudge(self): return False

    def shift(self, down, method):
        if down:
            self.used.append(method)
            if method in self.works:
                self.wakeups += 1


def run_nudger(fake, rolls=1, method=None):
    with mock.patch("nudge.make_backend", return_value=fake),             mock.patch("nudge.CONFIRM_SECONDS", 0.15):
        n = nudge.Nudger(wakeups=lambda: fake.wakeups, method=method)
        n.interval = 0.01

        async def settle():
            for _ in range(300):              # up to 3 s
                await asyncio.sleep(0.01)
                if not n.pending and not n.checking:
                    return

        async def go():
            task = asyncio.create_task(n.run())
            for _ in range(rolls):
                used = len(fake.used)
                n.request()
                await settle()
                while len(fake.used) == used:  # make sure this roll's tap happened
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
            task.cancel()

        asyncio.run(go())
    return n


class NudgeMethodSelectionTests(unittest.TestCase):
    def test_moves_on_until_a_method_reaches_fgu(self):
        fake = FakeFgu(["a", "b", "c"], works={"b"})
        n = run_nudger(fake, rolls=2)
        self.assertEqual(n.method, "b")
        self.assertFalse(n.checking)
        self.assertEqual(fake.used, ["a", "b", "b"])  # 1st roll: a fails, b works; 2nd roll: b
        self.assertEqual(fake.wakeups, 2)

    def test_first_method_working_is_kept(self):
        fake = FakeFgu(["a", "b"], works={"a"})
        n = run_nudger(fake)
        self.assertEqual((n.method, fake.used), ("a", ["a"]))

    def test_none_working_stops_checking(self):
        fake = FakeFgu(["a", "b"], works=set())
        n = run_nudger(fake)
        self.assertEqual(fake.used, ["a", "b"])
        self.assertFalse(n.checking)

    def test_forced_method(self):
        fake = FakeFgu(["a", "b"], works={"a", "b"})
        n = run_nudger(fake, method="b")
        self.assertEqual(fake.used, ["b"])

    def test_old_extension_just_keeps_tapping(self):
        fake = FakeFgu(["a", "b"], works=set())
        with mock.patch("nudge.make_backend", return_value=fake):
            n = nudge.Nudger(wakeups=lambda: None)
        n.interval = 0.01

        async def go():
            task = asyncio.create_task(n.run())
            n.request()
            await asyncio.sleep(0.2)
            task.cancel()

        asyncio.run(go())
        self.assertEqual(fake.used, ["a"])
        self.assertTrue(n.checking)  # still unknown, nothing switched


if __name__ == "__main__":
    unittest.main()
