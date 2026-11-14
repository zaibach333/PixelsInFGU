import sys
import unittest
from pathlib import Path
from unittest import mock

import nudge
from pixels_bridge import data_dir_candidates


class FguNameTests(unittest.TestCase):
    def test_matches_fgu_on_every_platform(self):
        for name in (
            r"C:\Program Files\Fantasy Grounds\FantasyGrounds.exe",   # Windows image path
            '"FantasyGrounds"',                                       # macOS lsappinfo value
            "Fantasy Grounds",                                        # macOS display name variant
            "/home/me/.smiteworks/fantasygrounds/FantasyGrounds.x86_64",
            "FantasyGrounds.\n",                                      # Linux comm (15 chars)
        ):
            self.assertTrue(nudge.is_fgu_name(name), name)

    def test_rejects_other_apps(self):
        for name in ("explorer.exe", '"Finder"', "/usr/bin/firefox", "", "Grounds"):
            self.assertFalse(nudge.is_fgu_name(name), name)


class DataDirTests(unittest.TestCase):
    def test_documented_defaults(self):
        home = Path("/h")
        self.assertEqual(data_dir_candidates("darwin", home)[0], home / "SmiteWorks" / "Fantasy Grounds")
        self.assertEqual(data_dir_candidates("linux", home), [home / ".smiteworks" / "fgdata"])
        self.assertEqual(data_dir_candidates("win32", home),
                         [home / "AppData" / "Roaming" / "SmiteWorks" / "Fantasy Grounds"])


class BackendSelectionTests(unittest.TestCase):
    def test_unknown_platform_has_no_backend(self):
        self.assertIsNone(nudge.make_backend("sunos5"))

    def test_linux_reports_missing_requirements(self):
        with mock.patch("shutil.which", return_value=None), mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            self.assertIn("xdotool", nudge.LinuxBackend().problem())
        with mock.patch("shutil.which", return_value="/usr/bin/xdotool"), \
                mock.patch.dict("os.environ", {}, clear=True):
            self.assertIn("Wayland", nudge.LinuxBackend().problem())
        with mock.patch("shutil.which", return_value="/usr/bin/xdotool"), \
                mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            self.assertIsNone(nudge.LinuxBackend().problem())

    def test_nudger_without_backend_returns_quietly(self):
        with mock.patch("nudge.make_backend", return_value=None):
            n = nudge.Nudger()
        self.assertFalse(n.enabled)
        import asyncio
        asyncio.run(n.run())  # must not loop forever

    def test_waits_for_permission_then_nudges(self):
        import asyncio

        class FakeBackend:
            name = "fake"
            methods = ["only"]
            def __init__(self):
                self.checks = 0
                self.keys = []
            def problem(self):
                self.checks += 1
                return "not allowed yet" if self.checks < 3 else None
            def front_app(self): return "FantasyGrounds"
            def fgu_is_foreground(self): return True
            def user_holding_shift(self): return False
            def post_background_nudge(self): return False
            def shift(self, down, method): self.keys.append(down)

        fake = FakeBackend()
        with mock.patch("nudge.make_backend", return_value=fake), \
                mock.patch("nudge.PROBLEM_RECHECK_SECONDS", 0.01):
            n = nudge.Nudger()
            n.interval = 0.01
            n.request()

            async def go():
                task = asyncio.create_task(n.run())
                for _ in range(200):
                    await asyncio.sleep(0.01)
                    if fake.keys == [True, False]:
                        break
                task.cancel()

            asyncio.run(go())
        self.assertGreaterEqual(fake.checks, 3)
        self.assertEqual(fake.keys, [True, False])   # one Shift down + up
        self.assertFalse(n.pending)

    def test_mac_shift_flags_look_like_left_shift(self):
        b = nudge.MacBackend
        down = b.FLAG_NONCOALESCED | b.FLAG_SHIFT | b.FLAG_DEVICE_LSHIFT
        self.assertEqual(down, 0x00020102)   # what a real left-Shift press reports
        self.assertEqual(b.KEYCODE_SHIFT, 56)

    @unittest.skipUnless(sys.platform == "win32", "Windows API")
    def test_windows_backend_loads(self):
        b = nudge.make_backend("win32")
        self.assertIsNone(b.problem())
        self.assertIsInstance(b.fgu_is_foreground(), bool)

    @unittest.skipUnless(sys.platform == "darwin", "macOS frameworks")
    def test_mac_backend_loads(self):
        b = nudge.make_backend("darwin")
        self.assertIsInstance(b.user_holding_shift(), bool)
        self.assertIsInstance(b.fgu_is_foreground(), bool)


if __name__ == "__main__":
    unittest.main()
