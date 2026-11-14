"""Wake the FGU extension after a roll.

FGU's Lua has no timer, file watcher or per-frame event, so it cannot notice
the inbox changing on its own. It does get a global Input "onShift" event, so
after writing a roll we briefly tap Shift while FGU is the foreground window.
The extension polls the inbox on that event. A lone Shift tap types nothing.

If FGU isn't in the foreground the nudge waits until it is (the user isn't
looking at FGU anyway), and it never fires while the user is holding Shift.

Platforms:
  Windows  user32 (keybd_event); also tries a background PostMessage.
  macOS    CoreGraphics events (EXPERIMENTAL). Needs Accessibility permission
           for the app that runs the bridge (Terminal, iTerm...).
  Linux    xdotool on X11 (EXPERIMENTAL). Not available on pure Wayland.
If no backend works, the user can tap Shift in FGU themselves.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from typing import Callable

log = logging.getLogger("pixels-bridge")

HOLD_SECONDS = 0.06   # several frames, so FGU sees the key state change
MANUAL_HINT = "Tap Shift in FGU after rolling to bring the roll in."
PROBLEM_RECHECK_SECONDS = 5.0
CONFIRM_SECONDS = 1.5      # how long FGU gets to react to a nudge


def is_fgu_name(name: str) -> bool:
    """True for FGU's process/app name on any platform.

    Windows: FantasyGrounds.exe   macOS: FantasyGrounds / "Fantasy Grounds"
    Linux:   FantasyGrounds.x86_64 (comm may be truncated to "FantasyGrounds.")
    """
    # Split on both separators: os.path.basename ignores "\" outside Windows.
    n = name.strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower().replace(" ", "")
    return n.startswith("fantasygrounds")


# --- Windows -------------------------------------------------------------------

class WindowsBackend:
    name = "Windows"
    methods = ["keybd_event"]
    VK_SHIFT = 0x10
    KEYEVENTF_KEYUP = 0x0002
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ct = ctypes
        self._wt = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

    def problem(self) -> str | None:
        return None

    def _process_name(self, pid: int) -> str:
        ct, wt = self._ct, self._wt
        handle = self._kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ct.create_unicode_buffer(1024)
            size = wt.DWORD(len(buf))
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ct.byref(size)):
                return ""
            return buf.value
        finally:
            self._kernel32.CloseHandle(handle)

    def front_app(self) -> str:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = self._wt.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, self._ct.byref(pid))
        return self._process_name(pid.value)

    def fgu_is_foreground(self) -> bool:
        return is_fgu_name(self.front_app())

    def find_fgu_window(self):
        """Top-level visible window belonging to FantasyGrounds.exe, or None."""
        ct, wt = self._ct, self._wt
        found = []

        @ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def enum_proc(hwnd, _lparam):
            if self._user32.IsWindowVisible(hwnd):
                pid = wt.DWORD()
                self._user32.GetWindowThreadProcessId(hwnd, ct.byref(pid))
                if is_fgu_name(self._process_name(pid.value)):
                    found.append(hwnd)
                    return False
            return True

        self._user32.EnumWindows(enum_proc, 0)
        return found[0] if found else None

    def post_background_nudge(self) -> bool:
        """Post Shift down/up straight to FGU's window without focusing it.

        Whether Unity acts on posted key messages while unfocused is engine
        dependent; if it doesn't, the foreground nudge still happens later.
        """
        hwnd = self.find_fgu_window()
        if not hwnd:
            return False
        scan = 0x2A << 16
        self._user32.PostMessageW(hwnd, self.WM_KEYDOWN, self.VK_SHIFT, 1 | scan)
        self._user32.PostMessageW(hwnd, self.WM_KEYUP, self.VK_SHIFT, 1 | scan | (1 << 30) | (1 << 31))
        return True

    def user_holding_shift(self) -> bool:
        return bool(self._user32.GetAsyncKeyState(self.VK_SHIFT) & 0x8000)

    def shift(self, down: bool, method: str = "keybd_event") -> None:
        self._user32.keybd_event(self.VK_SHIFT, 0, 0 if down else self.KEYEVENTF_KEYUP, 0)


# --- macOS (experimental) --------------------------------------------------------

class MacBackend:
    name = "macOS"
    # Ways to deliver Shift, tried in this order until FGU confirms one (see Nudger):
    #   hid-key      plain Shift key down/up into the HID stream (what automation tools use)
    #   pid-key      the same events sent straight to FGU's process
    #   session-key  plain key events into the login-session stream
    #   hid-flags    a hand-built flags-changed event with left-Shift flags
    methods = ["hid-key", "pid-key", "session-key", "hid-flags"]
    KEYCODE_SHIFT = 56          # kVK_Shift (left)
    FLAGS_CHANGED = 12          # kCGEventFlagsChanged
    FLAG_SHIFT = 0x00020000     # kCGEventFlagMaskShift
    # A real left-Shift press also sets the device-dependent left-shift bit and
    # the non-coalesced bit. Apps (Unity included) can look at these to tell
    # left from right Shift, so a bare FLAG_SHIFT may be ignored.
    FLAG_DEVICE_LSHIFT = 0x00000002   # NX_DEVICELSHIFTKEYMASK
    FLAG_NONCOALESCED = 0x00000100    # kCGEventFlagMaskNonCoalesced
    HID_EVENT_TAP = 0           # kCGHIDEventTap
    SESSION_EVENT_TAP = 1       # kCGSessionEventTap
    COMBINED_STATE = 0          # kCGEventSourceStateCombinedSessionState
    HID_STATE = 1               # kCGEventSourceStateHIDSystemState

    def __init__(self) -> None:
        import ctypes
        from ctypes import c_bool, c_int32, c_long, c_uint16, c_uint32, c_uint64, c_void_p

        self._ct = ctypes
        self._app = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        self._cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        a, cf = self._app, self._cf
        a.CGEventSourceCreate.restype = c_void_p
        a.CGEventSourceCreate.argtypes = [c_int32]
        a.CGEventCreateKeyboardEvent.restype = c_void_p
        a.CGEventCreateKeyboardEvent.argtypes = [c_void_p, c_uint16, c_bool]
        a.CGEventSetType.argtypes = [c_void_p, c_uint32]
        a.CGEventSetFlags.argtypes = [c_void_p, c_uint64]
        a.CGEventPost.argtypes = [c_uint32, c_void_p]
        a.CGEventPostToPid.argtypes = [c_int32, c_void_p]
        a.CGEventSourceFlagsState.restype = c_uint64
        a.CGEventSourceFlagsState.argtypes = [c_int32]
        a.AXIsProcessTrusted.restype = c_bool
        a.AXIsProcessTrustedWithOptions.restype = c_bool
        a.AXIsProcessTrustedWithOptions.argtypes = [c_void_p]
        cf.CFRelease.argtypes = [c_void_p]
        cf.CFDictionaryCreate.restype = c_void_p
        cf.CFDictionaryCreate.argtypes = [c_void_p, c_void_p, c_void_p, c_long, c_void_p, c_void_p]
        self._source = a.CGEventSourceCreate(self.HID_STATE)
        self._lsappinfo = shutil.which("lsappinfo") or "/usr/bin/lsappinfo"
        self._prompted = False
        self._front_asn = ""

    def _ask_for_accessibility(self) -> None:
        """Show macOS's own "allow Accessibility" prompt once, which also adds the
        terminal app to the list in System Settings so the user only flips a switch."""
        ct, a, cf = self._ct, self._app, self._cf
        try:
            key = ct.c_void_p.in_dll(a, "kAXTrustedCheckOptionPrompt")
            true = ct.c_void_p.in_dll(cf, "kCFBooleanTrue")
            keys = (ct.c_void_p * 1)(key.value)
            values = (ct.c_void_p * 1)(true.value)
            options = cf.CFDictionaryCreate(
                None, keys, values, 1,
                ct.addressof(ct.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
                ct.addressof(ct.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
            if options:
                a.AXIsProcessTrustedWithOptions(options)
                cf.CFRelease(options)
        except (ValueError, OSError) as exc:
            log.debug("Accessibility prompt unavailable: %s", exc)

    def problem(self) -> str | None:
        if self._app.AXIsProcessTrusted():
            return None
        if not self._prompted:
            self._prompted = True
            self._ask_for_accessibility()
        return ("macOS blocks the Shift nudge until you allow it: System Settings > "
                "Privacy & Security > Accessibility, turn on the app running the bridge "
                "(e.g. Terminal). The bridge starts nudging as soon as you do.")

    def front_app(self) -> str:
        try:
            front = subprocess.run([self._lsappinfo, "front"], capture_output=True, text=True, timeout=2).stdout.strip()
            self._front_asn = front
            if not front:
                return ""
            info = subprocess.run([self._lsappinfo, "info", "-only", "name", front],
                                  capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
        # Output looks like: "LSDisplayName"="FantasyGrounds"
        return info.partition("=")[2].strip().strip('"')

    def fgu_is_foreground(self) -> bool:
        return is_fgu_name(self.front_app())

    def post_background_nudge(self) -> bool:
        return False

    def user_holding_shift(self) -> bool:
        return bool(self._app.CGEventSourceFlagsState(self.COMBINED_STATE) & self.FLAG_SHIFT)

    def _front_pid(self) -> int | None:
        if not self._front_asn:
            self.front_app()
        try:
            out = subprocess.run([self._lsappinfo, "info", "-only", "pid", self._front_asn],
                                 capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        digits = "".join(c for c in out.partition("=")[2] if c.isdigit())   # "pid"=1234
        return int(digits) if digits else None

    def shift(self, down: bool, method: str = "hid-key") -> None:
        source = self._source if method == "hid-flags" else None
        ev = self._app.CGEventCreateKeyboardEvent(source, self.KEYCODE_SHIFT, down)
        if not ev:
            return
        try:
            if method == "hid-flags":
                flags = self.FLAG_NONCOALESCED
                if down:
                    flags |= self.FLAG_SHIFT | self.FLAG_DEVICE_LSHIFT
                self._app.CGEventSetType(ev, self.FLAGS_CHANGED)
                self._app.CGEventSetFlags(ev, flags)
                self._app.CGEventPost(self.HID_EVENT_TAP, ev)
            elif method == "pid-key":
                pid = self._front_pid()
                if pid:
                    self._app.CGEventPostToPid(pid, ev)
            elif method == "session-key":
                self._app.CGEventPost(self.SESSION_EVENT_TAP, ev)
            else:
                self._app.CGEventPost(self.HID_EVENT_TAP, ev)
        finally:
            self._cf.CFRelease(ev)


# --- Linux (experimental) ----------------------------------------------------------

class LinuxBackend:
    name = "Linux"
    methods = ["xdotool"]

    def __init__(self) -> None:
        self._xdotool = shutil.which("xdotool")

    def problem(self) -> str | None:
        self._xdotool = self._xdotool or shutil.which("xdotool")
        if not os.environ.get("DISPLAY"):
            return "No X11 display (pure Wayland?), so the Shift nudge is off."
        if not self._xdotool:
            return "Install xdotool (e.g. 'sudo apt install xdotool') to enable the Shift nudge."
        return None

    def _run(self, *args: str) -> str:
        try:
            return subprocess.run([self._xdotool, *args], capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def front_app(self) -> str:
        pid = self._run("getactivewindow", "getwindowpid")
        if not pid.isdigit():
            return ""
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                    return f.read().strip()
            except OSError:
                return ""

    def fgu_is_foreground(self) -> bool:
        return is_fgu_name(self.front_app())

    def post_background_nudge(self) -> bool:
        return False

    def user_holding_shift(self) -> bool:
        return False  # no cheap, permission-free way to read it; the tap is harmless anyway

    def shift(self, down: bool, method: str = "xdotool") -> None:
        self._run("keydown" if down else "keyup", "Shift_L")


def make_backend(platform: str = sys.platform):
    if platform == "win32":
        return WindowsBackend()
    if platform == "darwin":
        return MacBackend()
    if platform.startswith("linux"):
        return LinuxBackend()
    return None


class Nudger:
    """Taps Shift in FGU after each roll.

    With an extension that reports its wake-up count (in the outbox), the
    nudger checks that each tap actually woke FGU. If a way of sending Shift
    doesn't arrive, it moves on to the backend's next method and keeps the
    first one that works.
    """

    def __init__(self, wakeups: Callable[[], int | None] | None = None, method: str | None = None) -> None:
        self.pending = False
        try:
            self.backend = make_backend()
        except Exception as exc:  # noqa: BLE001 - missing system library etc.
            log.warning("Shift nudge unavailable: %s", exc)
            self.backend = None
        self.enabled = self.backend is not None
        # Windows checks are cheap API calls; elsewhere they spawn helper processes.
        self.interval = 0.05 if sys.platform == "win32" else 0.25
        self.wakeups = wakeups or (lambda: None)
        self.methods = list(self.backend.methods) if self.backend else []
        if method:
            if method in self.methods:
                self.methods = [method]
            else:
                log.warning("Unknown --nudge-method %r; choices here: %s", method, ", ".join(self.methods) or "none")
        self.method_index = 0
        self.checking = True        # still confirming that taps reach FGU

    @property
    def method(self) -> str:
        return self.methods[self.method_index] if self.methods else ""

    def request(self) -> None:
        self.pending = True

    async def wait_until_usable(self) -> None:
        """Return once the backend can nudge. Re-checks, so e.g. granting macOS
        Accessibility or installing xdotool takes effect without a restart."""
        warned = None
        while True:
            problem = self.backend.problem()
            if not problem:
                if warned:
                    log.info("Shift nudge is now available.")
                return
            if problem != warned:
                log.warning("%s %s", problem, MANUAL_HINT)
                warned = problem
            await asyncio.sleep(PROBLEM_RECHECK_SECONDS)

    async def tap(self, method: str | None = None) -> None:
        method = method or self.method
        self.backend.shift(True, method)
        await asyncio.sleep(HOLD_SECONDS)
        self.backend.shift(False, method)

    async def tap_and_confirm(self, method: str | None = None) -> bool | None:
        """Tap, then watch the extension's wake-up count.
        True: FGU woke. False: it didn't. None: can't tell (extension doesn't report)."""
        before = self.wakeups()
        await self.tap(method)
        if before is None:
            return None
        waited = 0.0
        while waited < CONFIRM_SECONDS:
            await asyncio.sleep(0.1)
            waited += 0.1
            after = self.wakeups()
            if after is not None and after > before:
                return True
        return False

    def _on_result(self, reached: bool | None) -> None:
        if reached is None:
            return  # extension too old to report wake-ups; just keep tapping
        if reached:
            log.info("Shift nudge confirmed: FGU picked up the roll (method: %s).", self.method)
            self.checking = False
            return
        log.warning("FGU didn't react to the Shift nudge (method: %s).", self.method)
        if self.method_index + 1 < len(self.methods):
            self.method_index += 1
            log.info("Trying the next way of sending Shift: %s", self.method)
            self.pending = True   # the roll still needs picking up
        else:
            log.warning("No way of sending Shift reached FGU. %s Please report this on GitHub "
                        "with your OS version.", MANUAL_HINT)
            self.method_index = 0
            self.checking = False

    async def run(self) -> None:
        if not self.enabled:
            log.warning("Auto-nudge isn't supported here. %s", MANUAL_HINT)
            return
        await self.wait_until_usable()
        waiting_logged = False
        while True:
            await asyncio.sleep(self.interval)
            if not self.pending:
                waiting_logged = False
                continue
            if not self.backend.fgu_is_foreground() or self.backend.user_holding_shift():
                if not waiting_logged:
                    # Try to wake FGU in the background; keep the foreground
                    # nudge pending as a fallback (a second poll is harmless).
                    sent = self.backend.post_background_nudge()
                    log.info("FGU not active (front app: %s)%s; will nudge when FGU is focused.",
                             self.backend.front_app() or "unknown",
                             ", sent background nudge" if sent else "")
                    waiting_logged = True
                continue
            self.pending = False
            if self.checking:
                self._on_result(await self.tap_and_confirm())
            else:
                await self.tap()
                log.debug("Nudged FGU (%s)", self.method)


async def test_nudge(outbox, method: str | None = None, seconds: int = 5) -> int:
    """--test-nudge: check each step of the nudge and try every way of sending Shift."""
    n = Nudger(wakeups=outbox.current_wakeups, method=method)
    print(f"Platform: {sys.platform}, nudge backend: {n.backend.name if n.backend else 'none'}")
    if not n.backend:
        print("No Shift nudge on this platform. " + MANUAL_HINT)
        return 1
    problem = n.backend.problem()
    print("Permissions/tools: " + ("OK" if not problem else problem))
    if problem:
        return 1
    print(f"Click into Fantasy Grounds now (campaign loaded, Pixels Dice enabled). Starting in {seconds} seconds...")
    for left in range(seconds, 0, -1):
        print(f"  {left}", flush=True)
        await asyncio.sleep(1)
    front = n.backend.front_app()
    is_fgu = is_fgu_name(front)
    print(f"Front app: {front or 'unknown'} -> {'FGU found' if is_fgu else 'NOT recognized as FGU'}")
    if not is_fgu:
        print("The bridge only taps Shift while FGU is the front app. If FGU WAS in front,")
        print("please report the front app name above on GitHub.")
        return 1
    working = []
    for m in n.methods:
        reached = await n.tap_and_confirm(m)
        label = {True: "reached FGU", False: "no response", None: "sent (can't confirm)"}[reached]
        print(f"  Shift via {m:12} {label}")
        if reached:
            working.append(m)
        await asyncio.sleep(0.5)
    if working:
        print(f"Working: {', '.join(working)}. The bridge finds this by itself; "
              f"to force it, use --nudge-method {working[0]}")
        return 0
    if n.wakeups() is None:
        print("The FGU extension didn't report wake-ups (needs extension 0.4.0+ and a loaded campaign).")
        print("Type /pixels in FGU: if 'wake-ups' went up, the nudge works.")
        return 1
    print("No way of sending Shift reached FGU. Please report this output on GitHub.")
    return 1
