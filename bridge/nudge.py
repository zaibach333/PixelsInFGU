"""Wake the FGU extension after a roll.

FGU's Lua has no timer, file watcher or per-frame event, so it cannot notice
the inbox changing on its own. It does get a global Input "onShift" event, so
after writing a roll we briefly tap Shift while FGU is the foreground window.
The extension polls the inbox on that event. A lone Shift tap types nothing.

If FGU isn't in the foreground the nudge waits until it is (the user isn't
looking at FGU anyway), and it never fires while the user is holding Shift.
Windows only for now; on other platforms nudging is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

log = logging.getLogger("pixels-bridge")

FGU_EXE = "fantasygrounds.exe"
VK_SHIFT = 0x10
KEYEVENTF_KEYUP = 0x0002
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
HOLD_SECONDS = 0.06   # several frames, so FGU sees the key state change


class Nudger:
    def __init__(self) -> None:
        self.pending = False
        self.enabled = sys.platform == "win32"
        if self.enabled:
            import ctypes
            from ctypes import wintypes

            self._ct = ctypes
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._user32.GetForegroundWindow.restype = wintypes.HWND
            self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self._kernel32.OpenProcess.restype = wintypes.HANDLE
            self._kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            self._wintypes = wintypes

    def request(self) -> None:
        self.pending = True

    def fgu_is_foreground(self) -> bool:
        ct, wt = self._ct, self._wintypes
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wt.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ct.byref(pid))
        handle = self._kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            buf = ct.create_unicode_buffer(1024)
            size = wt.DWORD(len(buf))
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ct.byref(size)):
                return False
            return os.path.basename(buf.value).lower() == FGU_EXE
        finally:
            self._kernel32.CloseHandle(handle)

    def _process_name(self, pid: int) -> str:
        ct, wt = self._ct, self._wintypes
        handle = self._kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ct.create_unicode_buffer(1024)
            size = wt.DWORD(len(buf))
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ct.byref(size)):
                return ""
            return os.path.basename(buf.value).lower()
        finally:
            self._kernel32.CloseHandle(handle)

    def find_fgu_window(self):
        """Top-level visible window belonging to FantasyGrounds.exe, or None."""
        ct, wt = self._ct, self._wintypes
        found = []

        @ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def enum_proc(hwnd, _lparam):
            if self._user32.IsWindowVisible(hwnd):
                pid = wt.DWORD()
                self._user32.GetWindowThreadProcessId(hwnd, ct.byref(pid))
                if self._process_name(pid.value) == FGU_EXE:
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
        self._user32.PostMessageW(hwnd, WM_KEYDOWN, VK_SHIFT, 1 | scan)
        self._user32.PostMessageW(hwnd, WM_KEYUP, VK_SHIFT, 1 | scan | (1 << 30) | (1 << 31))
        return True

    def user_holding_shift(self) -> bool:
        return bool(self._user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)

    async def run(self) -> None:
        if not self.enabled:
            log.warning("Auto-nudge only works on Windows; FGU will pick rolls up on its next poll.")
            return
        waiting_logged = False
        while True:
            await asyncio.sleep(0.05)
            if not self.pending:
                waiting_logged = False
                continue
            if not self.fgu_is_foreground() or self.user_holding_shift():
                if not waiting_logged:
                    # Try to wake FGU in the background; keep the foreground
                    # nudge pending as a fallback (a second poll is harmless).
                    sent = self.post_background_nudge()
                    log.info("FGU not active: %s; will also nudge when FGU is focused.",
                             "sent background nudge" if sent else "FGU window not found")
                    waiting_logged = True
                continue
            self.pending = False
            self._user32.keybd_event(VK_SHIFT, 0, 0, 0)
            await asyncio.sleep(HOLD_SECONDS)
            self._user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
            log.debug("Nudged FGU")
