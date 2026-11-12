"""Pixels dice Bluetooth LE protocol: UUIDs, enums and message parsing.

Derived from the official open-source @systemic-games/pixels-core-connect
and pixels-core-animation packages (v1.3.0). All multi-byte fields are
little-endian. Each BLE notification carries one message whose first byte
is the message type.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# --- Bluetooth UUIDs -------------------------------------------------------

SERVICE_UUID = "a6b90001-7a5a-43f2-a962-350c8edc9b5b"
NOTIFY_UUID = "a6b90002-7a5a-43f2-a962-350c8edc9b5b"
WRITE_UUID = "a6b90003-7a5a-43f2-a962-350c8edc9b5b"

LEGACY_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
LEGACY_NOTIFY_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
LEGACY_WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

# --- Message types (subset we use) ------------------------------------------

MSG_WHO_ARE_YOU = 1
MSG_I_AM_A_DIE = 2
MSG_ROLL_STATE = 3
MSG_REQUEST_ROLL_STATE = 23
MSG_BLINK = 29
MSG_REQUEST_BATTERY_LEVEL = 33
MSG_BATTERY_LEVEL = 34

# --- Enums -------------------------------------------------------------------

DIE_TYPES = {
    0: "unknown",
    1: "d4",
    2: "d6",
    3: "d8",
    4: "d10",
    5: "d00",
    6: "d12",
    7: "d20",
    8: "d6pipped",
    9: "d6fudge",
}

ROLL_STATES = {
    0: "unknown",
    1: "rolled",
    2: "handling",
    3: "rolling",
    4: "crooked",
    5: "onFace",
}

LEGACY_I_AM_A_DIE_SIZE = 22

# Firmware built on/before this (ms since epoch) has swapped normals on d4/d6.
_FW_BAD_NORMALS_MS = 1704150000000


@dataclass
class DieInfo:
    die_type: str = "unknown"
    pixel_id: int = 0
    led_count: int = 0
    name: str = ""
    firmware_timestamp_ms: int = 0
    battery_percent: int | None = None
    roll_state: str = "unknown"
    face_index: int = 0


@dataclass
class RollState:
    state: str
    face_index: int


@dataclass
class BatteryLevel:
    percent: int
    state: int


SYSTEMIC_COMPANY_ID = 0x0D39


@dataclass
class AdvInfo:
    """Die state broadcast in BLE advertisements (works while not connected)."""
    pixel_id: int
    die_type: str
    led_count: int
    roll_state: str
    face_index: int
    battery_percent: int
    firmware_timestamp_ms: int


def parse_advertisement(manufacturer_data: dict[int, bytes], service_data: dict[str, bytes]) -> AdvInfo | None:
    """Port of getScannedPixel (react-native-pixels-connect), current format only.

    manufacturer data (after the company id): ledCount, designAndColor
    (die type in the high nibble), rollState, faceIndex, battery (MSB = charging).
    service data: pixelId u32, firmware build timestamp u32 (seconds).
    """
    manuf = manufacturer_data.get(SYSTEMIC_COMPANY_ID)
    if manuf is None and len(manufacturer_data) == 1:
        manuf = next(iter(manufacturer_data.values()))
    service = next((v for v in service_data.values() if len(v) >= 8), None)
    if not manuf or len(manuf) < 5 or service is None:
        return None
    pixel_id, fw_seconds = struct.unpack_from("<II", service, 0)
    if not pixel_id:
        return None
    return AdvInfo(
        pixel_id=pixel_id,
        die_type=DIE_TYPES.get((manuf[1] >> 4) & 0xF, "unknown"),
        led_count=manuf[0],
        roll_state=ROLL_STATES.get(manuf[2], "unknown"),
        face_index=manuf[3],
        battery_percent=manuf[4] & 0x7F,
        firmware_timestamp_ms=fw_seconds * 1000,
    )


def face_from_index(face_index: int, die_type: str, firmware_timestamp_ms: int = 0) -> int:
    """Port of DiceUtils.faceFromIndex.

    d10 returns 0..9 and d00 returns 0..90 (as printed on the die); callers
    that need 1..10 / percentile semantics convert afterwards.
    """
    if firmware_timestamp_ms and firmware_timestamp_ms <= _FW_BAD_NORMALS_MS:
        if die_type == "d4":
            return {3: 2, 2: 3, 5: 4}.get(face_index, 1)
        if die_type == "d6":
            return {4: 2, 3: 3, 2: 4, 1: 5}.get(face_index, face_index + 1)
    if die_type == "d10":
        return face_index
    if die_type == "d00":
        return face_index * 10
    if die_type == "unknown":
        return face_index
    return face_index + 1


def encode_who_are_you() -> bytes:
    return bytes([MSG_WHO_ARE_YOU])


def encode_request_battery() -> bytes:
    return bytes([MSG_REQUEST_BATTERY_LEVEL])


def encode_blink(rgb: int, count: int = 2, duration_ms: int = 1000, fade: int = 128,
                 face_mask: int = 0xFFFFFFFF, loop_count: int = 1) -> bytes:
    """Blink message: type, count, duration(u16), color(u32 0xRRGGBB), faceMask(u32), fade, loopCount."""
    return struct.pack("<BBHIIBB", MSG_BLINK, count, duration_ms, rgb & 0xFFFFFF,
                       face_mask, fade, loop_count)


def parse_message(data: bytes):
    """Parse a notification payload. Returns DieInfo, RollState, BatteryLevel or None."""
    if not data:
        return None
    msg_type = data[0]
    if msg_type == MSG_ROLL_STATE and len(data) >= 3:
        return RollState(ROLL_STATES.get(data[1], "unknown"), data[2])
    if msg_type == MSG_BATTERY_LEVEL and len(data) >= 3:
        return BatteryLevel(data[1], data[2])
    if msg_type == MSG_I_AM_A_DIE:
        if len(data) == LEGACY_I_AM_A_DIE_SIZE:
            return _parse_legacy_i_am_a_die(data)
        return _parse_i_am_a_die(data)
    return None


def _parse_legacy_i_am_a_die(data: bytes) -> DieInfo:
    # type, ledCount, colorway, dieType, dataSetHash(4), pixelId(4),
    # availableFlash(2), buildTimestamp(4, seconds), rollState, faceIndex,
    # batteryPercent, batteryState
    (_, led_count, _colorway, die_type, _hash, pixel_id, _flash, build_ts,
     roll_state, face_index, battery, _bstate) = struct.unpack("<BBBBIIHIBBBB", data)
    return DieInfo(
        die_type=DIE_TYPES.get(die_type, "unknown"),
        pixel_id=pixel_id,
        led_count=led_count,
        firmware_timestamp_ms=build_ts * 1000,
        battery_percent=battery,
        roll_state=ROLL_STATES.get(roll_state, "unknown"),
        face_index=face_index,
    )


def _parse_i_am_a_die(data: bytes) -> DieInfo:
    """New format: type byte followed by size-prefixed chunks, in order:
    VersionInfo, DieInfo, CustomDesignAndColorName, DieName, SettingsInfo, StatusInfo.
    """
    info = DieInfo()
    chunks = []
    pos = 1
    while pos < len(data) and len(chunks) < 6:
        size = data[pos]
        if size == 0:
            break
        chunks.append(data[pos:pos + size])
        pos += size

    def get(i: int) -> bytes:
        return chunks[i] if i < len(chunks) else b""

    version = get(0)
    if len(version) >= 7:
        # chunkSize(1) firmwareVersion(2) buildTimestamp(4, seconds) ...
        build_ts = struct.unpack_from("<I", version, 3)[0]
        info.firmware_timestamp_ms = build_ts * 1000

    die = get(1)
    if len(die) >= 9:
        # chunkSize(1) pixelId(4) chipModel(1) dieType(1) ledCount(1) colorway(1)
        info.pixel_id = struct.unpack_from("<I", die, 1)[0]
        info.die_type = DIE_TYPES.get(die[6], "unknown")
        info.led_count = die[7]

    name = get(3)
    if len(name) > 1:
        info.name = name[1:].split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    status = get(5)
    if len(status) >= 5:
        # chunkSize(1) batteryPercent(1) batteryState(1) rollState(1) faceIndex(1)
        info.battery_percent = status[1]
        info.roll_state = ROLL_STATES.get(status[3], "unknown")
        info.face_index = status[4]

    return info
