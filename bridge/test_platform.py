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
