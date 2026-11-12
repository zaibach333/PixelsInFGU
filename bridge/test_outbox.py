import os
import tempfile
import time
import unittest
from pathlib import Path

from outbox import OUTBOX_FILENAME, OutboxWatcher


class OutboxTests(unittest.TestCase):
    def test_reset_ignores_stale_then_sees_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / OUTBOX_FILENAME
            path.write_text('{"version":1,"waiting":["d20"]}', encoding="utf-8")
            w = OutboxWatcher(Path(tmp))
            w.reset()
            self.assertFalse(w.poll())
            self.assertEqual(w.waiting, [])

            path.write_text('{"version":1,"waiting":["d20","d6"]}', encoding="utf-8")
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
            self.assertTrue(w.poll())
            self.assertEqual(w.waiting, ["d20", "d6"])

    def test_empty_object_waiting(self):
        # FGU's JSON encoder may write an empty list as {}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / OUTBOX_FILENAME
            w = OutboxWatcher(Path(tmp))
            path.write_text('{"version":1,"waiting":{}}', encoding="utf-8")
            w.poll()
            self.assertEqual(w.waiting, [])


if __name__ == "__main__":
    unittest.main()
