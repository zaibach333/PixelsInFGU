"""Pixels -> Fantasy Grounds Unity bridge.

Connects to Pixels dice over Bluetooth LE and writes each finished roll to an
inbox file in the FGU data folder, where the PixelsFGU extension picks it up.
It also watches the extension's outbox and blinks the dice FGU is waiting on.

Pixels fall asleep and drop the connection when left still. The bridge keeps
scanning, so a die that wakes up is seen at once. Its roll is read from the
advertisement (Pixels broadcast roll state + face), and then it reconnects.
Sleeping dice still count as owned, so FGU keeps routing rolls to them.

Usage:
    pixels_bridge.py                     # connect to all Pixels in range
    pixels_bridge.py --names Bob Amy     # only dice whose name contains these
    pixels_bridge.py --list              # scan once, show dice in range, exit
    pixels_bridge.py --simulate d20 d6   # no dice: type rolls like "d20 17"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import time
from pathlib import Path

import pixels_protocol as proto
from inbox import Inbox, fgu_die_type
from nudge import Nudger, test_nudge
from outbox import OutboxWatcher
from percentile import PercentilePairer
from version import __version__

log = logging.getLogger("pixels-bridge")

BLINK_COLOR = 0x0040FF          # blue: "FGU wants this die"
BLINK_EVERY_SECONDS = 3.0
HEARTBEAT_SECONDS = 15.0
RECONNECT_MIN_SECONDS = 3.0
DUPLICATE_ROLL_WINDOW = 2.0     # same face from advert + notify within this = one roll
LOW_BATTERY_PERCENT = 15
LOG_FILENAME = "PixelsFGU_bridge.log"


# --- FGU data folder ---------------------------------------------------------

def data_dir_candidates(platform: str = sys.platform, home: Path | None = None) -> list[Path]:
    """FGU's default data folders, most likely first.

    Defaults per FGU's docs (Settings > Advanced > Data Directory). A custom
    folder on macOS/Linux isn't discoverable; pass --data-dir for that.
    """
    home = home or Path.home()
    if platform == "win32":
        return [home / "AppData" / "Roaming" / "SmiteWorks" / "Fantasy Grounds"]
    if platform == "darwin":
        return [home / "SmiteWorks" / "Fantasy Grounds",
                home / "Library" / "Application Support" / "SmiteWorks" / "Fantasy Grounds"]
    return [home / ".smiteworks" / "fgdata"]


def default_data_dir() -> Path | None:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SmiteWorks\Fantasy Grounds") as key:
                value, _ = winreg.QueryValueEx(key, "DataDir")
                return Path(value)
        except OSError:
            pass
    return next((p for p in data_dir_candidates() if p.is_dir()), None)


# --- One physical die ----------------------------------------------------------

class Die:
    def __init__(self, address: str, inbox: Inbox, add_roll=None):
        self.address = address
        self.inbox = inbox
        self.add_roll = add_roll or inbox.add_roll   # usually PercentilePairer.add
        self.device = None
        self.name = address
        self.die_type = "unknown"
        self.firmware_ms = 0
        self.battery: int | None = None
        self.client = None
        self.write_uuid = None
        self.connecting = False
        self.last_attempt = 0.0
        self.last_state: str | None = None     # last roll state seen (advert or notify)
        self.last_roll: tuple[int, float] | None = None
        self.last_blink = 0.0
        self.low_battery_warned = False

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    @property
    def fgu_die(self) -> str | None:
        return fgu_die_type(self.die_type)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.die_type})"

    # ---- state shared with FGU

    def publish(self) -> None:
        if self.die_type == "unknown":
            return
        self.inbox.set_die(
            self.address,
            name=self.name,
            die=self.fgu_die,           # null if FGU can't use this die type
            pixels_type=self.die_type,
            battery=self.battery,
            connected=self.connected,
            state="connected" if self.connected else "asleep",
        )
        if self.battery is not None and self.battery <= LOW_BATTERY_PERCENT and not self.low_battery_warned:
            log.warning("%s battery is low (%s%%) - charge it soon.", self.name, self.battery)
            self.low_battery_warned = True

    def record_roll(self, face_index: int, source: str) -> None:
        face = proto.face_from_index(face_index, self.die_type, self.firmware_ms)
        now = time.monotonic()
        if self.last_roll and self.last_roll[0] == face and now - self.last_roll[1] < DUPLICATE_ROLL_WINDOW:
            return  # same roll reported by both the advert and the connection
        self.last_roll = (face, now)
        roll = self.add_roll(self.name, self.die_type, face)
        if roll:
            log.info("ROLL  %-20s %s = %s  (#%d, via %s)", self.name, roll["die"], roll["value"], roll["seq"], source)
        elif self.fgu_die is None:
            log.info("Ignored roll from %s (FGU can't use %s)", self.name, self.die_type)

    def on_roll_state(self, state: str, face_index: int, source: str) -> None:
        if state == "rolled" and self.last_state not in (None, "rolled"):
            self.record_roll(face_index, source)
        elif state == "crooked" and self.last_state != "crooked":
            log.info("%s landed crooked - roll again", self.name)
        self.last_state = state

    # ---- advertisements (work while asleep/disconnected)

    def on_advertisement(self, device, adv: proto.AdvInfo, local_name: str | None) -> None:
        self.device = device
        if local_name:
            self.name = local_name
        changed = (self.die_type != adv.die_type or self.battery != adv.battery_percent)
        if adv.die_type != "unknown":
            self.die_type = adv.die_type
        self.firmware_ms = adv.firmware_timestamp_ms or self.firmware_ms
        self.battery = adv.battery_percent
        if not self.connected:
            self.on_roll_state(adv.roll_state, adv.face_index, "advert")
        if changed:
            self.publish()

    # ---- connection

    def want_connection(self) -> bool:
        return (not self.connected and not self.connecting and self.device is not None
                and time.monotonic() - self.last_attempt >= RECONNECT_MIN_SECONDS)

    async def connect(self) -> None:
        from bleak import BleakClient

        self.connecting = True
        self.last_attempt = time.monotonic()
        try:
            async with BleakClient(self.device, timeout=15.0) as client:
                self.client = client
                self.connecting = False
                if client.services.get_service(proto.SERVICE_UUID) is not None:
                    notify_uuid, self.write_uuid = proto.NOTIFY_UUID, proto.WRITE_UUID
                else:
                    notify_uuid, self.write_uuid = proto.LEGACY_NOTIFY_UUID, proto.LEGACY_WRITE_UUID
                await client.start_notify(notify_uuid, self._on_notify)
                await self.send(proto.encode_who_are_you())
                log.info("Connected to %s", self.label)
                self.publish()
                while client.is_connected:
                    await asyncio.sleep(30)
                    if not await self.send(proto.encode_request_battery()):
                        break
        except Exception as exc:  # noqa: BLE001
            log.debug("Connection to %s ended: %s", self.name, exc)
        finally:
            was_connected = self.client is not None
            self.client = None
            self.connecting = False
            if was_connected:
                log.info("%s disconnected (asleep or out of range); still counted as yours.", self.name)
                self.publish()

    async def send(self, data: bytes) -> bool:
        client = self.client
        if not client or not client.is_connected:
            return False
        try:
            await client.write_gatt_char(self.write_uuid, data, response=True)
            return True
        except Exception as exc:  # noqa: BLE001 - die went away mid-write
            log.debug("Write to %s failed: %s", self.name, exc)
            return False

    async def blink(self) -> None:
        self.last_blink = time.monotonic()
        await self.send(proto.encode_blink(BLINK_COLOR, count=2, duration_ms=1000, fade=160))

    def _on_notify(self, _sender, data: bytearray) -> None:
        msg = proto.parse_message(bytes(data))
        if isinstance(msg, proto.DieInfo):
            if msg.name:
                self.name = msg.name
            if msg.die_type != "unknown":
                self.die_type = msg.die_type
            self.firmware_ms = msg.firmware_timestamp_ms or self.firmware_ms
            self.battery = msg.battery_percent
            log.info("Identified %s, battery %s%%", self.label, self.battery)
            if self.fgu_die is None:
                log.warning("%s is a %s, which FGU can't use; its rolls will be ignored.", self.name, self.die_type)
            self.publish()
        elif isinstance(msg, proto.BatteryLevel):
            self.battery = msg.percent
            self.publish()
        elif isinstance(msg, proto.RollState):
            self.on_roll_state(msg.state, msg.face_index, "connection")


# --- Scanning ------------------------------------------------------------------

def _is_pixel(adv_data) -> bool:
    uuids = [u.lower() for u in (adv_data.service_uuids or [])]
    return (proto.SERVICE_UUID in uuids or proto.LEGACY_SERVICE_UUID in uuids
            or proto.SYSTEMIC_COMPANY_ID in (adv_data.manufacturer_data or {}))


async def run_ble(inbox: Inbox, dice: dict[str, Die], name_filters: list[str], add_roll=None) -> None:
    from bleak import BleakScanner

    loop = asyncio.get_running_loop()

    def on_detect(device, adv_data) -> None:
        if not _is_pixel(adv_data):
            return
        adv = proto.parse_advertisement(adv_data.manufacturer_data or {}, adv_data.service_data or {})
        if adv is None:
            return
        name = adv_data.local_name or device.name or ""
        die = dice.get(device.address)
        if die is None:
            if name_filters and not any(f.lower() in name.lower() for f in name_filters):
                return
            die = Die(device.address, inbox, add_roll)
            dice[device.address] = die
            log.info("Found %s (%s), battery %s%%", name or device.address, adv.die_type, adv.battery_percent)
        die.on_advertisement(device, adv, name or None)
        if die.want_connection():
            die.connecting = True  # claim before the task starts so repeats don't double-connect
            loop.create_task(die.connect())

    log.info("Scanning for Pixels dice... pick them up to wake them. (Ctrl+C to quit)")
    async with BleakScanner(detection_callback=on_detect):
        while True:
            await asyncio.sleep(3600)


async def list_dice(scan_seconds: float) -> None:
    from bleak import BleakScanner

    print(f"Scanning {scan_seconds:.0f}s for Pixels dice (pick them up to wake them)...")
    found = await BleakScanner.discover(timeout=scan_seconds, return_adv=True)
    pixels = [(d, a) for d, a in found.values() if _is_pixel(a)]
    if not pixels:
        print("No Pixels found. Make sure they're awake and not connected to the Pixels app.")
    for d, a in pixels:
        adv = proto.parse_advertisement(a.manufacturer_data or {}, a.service_data or {})
        extra = f"{adv.die_type:8} battery {adv.battery_percent}%" if adv else ""
        print(f"  {a.local_name or d.name or '(unnamed)':24} {d.address}  {extra}")


# --- Background tasks ------------------------------------------------------------

async def blink_waiting_dice(outbox: OutboxWatcher, dice: dict[str, Die]) -> None:
    """While FGU waits on a die type, blink connected dice of that type every few seconds."""
    while True:
        await asyncio.sleep(0.25)
        if outbox.poll():
            if outbox.waiting:
                log.info("FGU is waiting for: %s", " ".join(outbox.waiting))
            for die in dice.values():
                die.last_blink = 0.0  # blink right away on a new request
        wanted = set(outbox.waiting)
        if not wanted:
            continue
        now = time.monotonic()
        for die in list(dice.values()):
            if die.connected and die.fgu_die in wanted and now - die.last_blink >= BLINK_EVERY_SECONDS:
                asyncio.create_task(die.blink())


async def heartbeat(inbox: Inbox) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        inbox.heartbeat()


# --- Simulator ---------------------------------------------------------------

_SIM_FACES = {"d4": 4, "d6": 6, "d8": 8, "d10": 10, "d00": 10, "d12": 12, "d20": 20}


def sim_face(die: str, value: int | None) -> int:
    """Turn an FGU-style value typed by the user into a Pixels face value."""
    if value is None:
        n = random.randint(1, _SIM_FACES[die])
        if die == "d10":
            return n - 1
        if die == "d00":
            return (n - 1) * 10
        return n
    if die == "d10":
        return 0 if value == 10 else value
    return value


async def run_simulator(inbox: Inbox, sim_dice: list[str], add_roll=None) -> None:
    add_roll = add_roll or inbox.add_roll
    for i, die in enumerate(sim_dice, 1):
        inbox.set_die(f"sim{i}", name=f"Sim {die} #{i}", die=die, pixels_type=die, battery=100,
                      connected=True, state="connected")
    print(f"Simulating dice: {', '.join(sim_dice)}")
    print("Type a die and optional value, e.g. 'd20 17', 'd6', 'd00 70'. 'q' quits.")
    loop = asyncio.get_running_loop()
    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        line = raw.lstrip("﻿").strip().lower()  # PowerShell pipes may prepend a BOM
        if raw == "" or line in ("q", "quit", "exit"):  # "" means EOF
            return
        if not line:
            continue
        parts = line.split()
        die = parts[0]
        if die not in _SIM_FACES:
            print(f"  unknown die '{die}', use one of {', '.join(_SIM_FACES)}")
            continue
        try:
            value = int(parts[1]) if len(parts) > 1 else None
        except ValueError:
            print("  value must be a number")
            continue
        roll = add_roll(f"Simulated {die}", die, sim_face(die, value))
        if roll:
            log.info("ROLL  %-20s %s = %s  (#%d)", roll["pixel"], roll["die"], roll["value"], roll["seq"])


# --- Main --------------------------------------------------------------------

def install_close_handler(inbox: Inbox) -> None:
    """Mark the bridge stopped even when the console window is closed with X."""
    if sys.platform != "win32":
        # Closing a terminal sends SIGHUP; logout/kill send SIGTERM.
        import signal

        def on_signal(_signum, _frame):
            try:
                inbox.stop()
            except Exception:  # noqa: BLE001
                pass
            raise KeyboardInterrupt

        for name in ("SIGHUP", "SIGTERM"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), on_signal)
        return
    import ctypes
    from ctypes import wintypes

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def handler(_event):
        try:
            inbox.stop()
        except Exception:  # noqa: BLE001
            pass
        return False  # let default handling continue

    install_close_handler._ref = handler  # keep the callback alive
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge Pixels dice rolls into Fantasy Grounds Unity.")
    parser.add_argument("--data-dir", type=Path, help="FGU data folder (default: auto-detect)")
    parser.add_argument(
        "--simulate", nargs="*", metavar="DIE",
        help="no real dice: pretend these are connected (default: d20 d20) and type rolls",
    )
    parser.add_argument("--list", action="store_true", help="scan once, list Pixels in range, and exit")
    parser.add_argument("--names", nargs="*", default=[], help="only use dice whose name contains one of these")
    parser.add_argument("--no-nudge", action="store_true", help="don't tap Shift to wake FGU after a roll")
    parser.add_argument("--test-nudge", action="store_true",
                        help="check that the Shift nudge reaches FGU (click into FGU when asked), then exit")
    parser.add_argument("--nudge-method", metavar="NAME",
                        help="force one way of sending Shift (see --test-nudge); default: find one that works")
    parser.add_argument("--no-blink", action="store_true", help="don't blink dice FGU is waiting on")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"PixelsFGU bridge {__version__}")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("bleak").setLevel(logging.WARNING)

    if args.list:
        asyncio.run(list_dice(8.0))
        return

    data_dir = args.data_dir or default_data_dir()
    if not data_dir or not Path(data_dir).exists():
        sys.exit("Could not find the Fantasy Grounds data folder; pass --data-dir "
                 "(FGU shows it under Settings > Data Folder).")

    file_log = logging.FileHandler(Path(data_dir) / LOG_FILENAME, mode="w", encoding="utf-8")
    file_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    file_log.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(file_log)

    outbox = OutboxWatcher(data_dir)
    outbox.reset()
    if args.test_nudge:
        sys.exit(asyncio.run(test_nudge(outbox, args.nudge_method)))

    nudger = Nudger(wakeups=outbox.current_wakeups, method=args.nudge_method)
    inbox = Inbox(data_dir, on_roll=None if args.no_nudge else nudger.request)
    inbox._write()
    install_close_handler(inbox)
    dice: dict[str, Die] = {}

    def waiting() -> list[str]:
        outbox.poll()
        return outbox.waiting
    log.info("PixelsFGU bridge %s - writing rolls to %s", __version__, inbox.path)

    if args.simulate is not None:
        sim_dice = args.simulate or ["d20", "d20"]
        bad = [d for d in sim_dice if d not in _SIM_FACES]
        if bad:
            sys.exit(f"Unknown die type(s) {bad}; use {', '.join(_SIM_FACES)}")
        pairer = PercentilePairer(inbox, waiting, lambda: set(sim_dice))
        main_coro = run_simulator(inbox, sim_dice, pairer.add)
    else:
        pairer = PercentilePairer(inbox, waiting, lambda: {d.die_type for d in dice.values()})
        main_coro = run_ble(inbox, dice, args.names, pairer.add)

    async def run_all():
        helpers = [asyncio.create_task(heartbeat(inbox))]
        if not args.no_nudge:
            helpers.append(asyncio.create_task(nudger.run()))
        if not args.no_blink:
            helpers.append(asyncio.create_task(blink_waiting_dice(outbox, dice)))
        try:
            await main_coro
        finally:
            for task in helpers:
                task.cancel()

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        pass
    finally:
        inbox.stop()
        log.info("Bridge stopped; FGU will use normal dice.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        logging.exception("Bridge crashed")
        if getattr(sys, "frozen", False):
            input("Press Enter to close...")
        raise
