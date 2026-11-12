import json
import struct
import tempfile
import unittest
from pathlib import Path

import pixels_protocol as proto
from inbox import Inbox, to_fgu


class ProtocolTests(unittest.TestCase):
    def test_roll_state(self):
        msg = proto.parse_message(bytes([proto.MSG_ROLL_STATE, 1, 16]))
        self.assertEqual(msg, proto.RollState("rolled", 16))

    def test_face_from_index(self):
        self.assertEqual(proto.face_from_index(19, "d20"), 20)
        self.assertEqual(proto.face_from_index(0, "d10"), 0)
        self.assertEqual(proto.face_from_index(7, "d00"), 70)
        # old firmware with swapped d6 normals
        self.assertEqual(proto.face_from_index(4, "d6", 1700000000000), 2)
        self.assertEqual(proto.face_from_index(4, "d6", 1750000000000), 5)

    def test_parse_advertisement(self):
        manuf = {0x0D39: bytes([20, (7 << 4) | 3, 1, 16, 0x80 | 55])}
        service = {"a6b90001-7a5a-43f2-a962-350c8edc9b5b": struct.pack("<II", 999, 1720000000)}
        adv = proto.parse_advertisement(manuf, service)
        self.assertEqual(adv.die_type, "d20")
        self.assertEqual(adv.roll_state, "rolled")
        self.assertEqual(adv.face_index, 16)
        self.assertEqual(adv.battery_percent, 55)
        self.assertEqual(adv.pixel_id, 999)
        self.assertIsNone(proto.parse_advertisement({}, {}))

    def test_encode_blink(self):
        msg = proto.encode_blink(0x0050FF, count=3, duration_ms=1200)
        self.assertEqual(len(msg), 14)  # 1+1+2+4+4+1+1
        self.assertEqual(msg[0], 29)
        self.assertEqual(struct.unpack_from("<H", msg, 2)[0], 1200)
        self.assertEqual(struct.unpack_from("<I", msg, 4)[0], 0x0050FF)

    def test_legacy_i_am_a_die(self):
        data = struct.pack("<BBBBIIHIBBBB", 2, 20, 1, 7, 0xAA, 1234, 0, 1700000000, 5, 3, 88, 0)
        info = proto.parse_message(data)
        self.assertEqual(info.die_type, "d20")
        self.assertEqual(info.pixel_id, 1234)
        self.assertEqual(info.battery_percent, 88)
        self.assertEqual(info.firmware_timestamp_ms, 1700000000000)

    def test_new_i_am_a_die(self):
        version = struct.pack("<BHIHHHH", 15, 0x200, 1720000000, 1, 1, 1, 1)
        die = struct.pack("<BIBBBB", 9, 4321, 1, 2, 6, 3)
        design = bytes([2, 0])
        name = bytes([8]) + b"Bobby\x00\x00"
        settings = struct.pack("<BIII", 13, 0, 0, 0)
        status = bytes([5, 77, 0, 5, 2])
        info = proto.parse_message(bytes([2]) + version + die + design + name + settings + status)
        self.assertEqual(info.die_type, "d6")
        self.assertEqual(info.pixel_id, 4321)
        self.assertEqual(info.name, "Bobby")
        self.assertEqual(info.battery_percent, 77)
        self.assertEqual(info.face_index, 2)
        self.assertEqual(info.firmware_timestamp_ms, 1720000000000)


class EveryPixelsDieType(unittest.TestCase):
    """Face index (as reported by the die) -> what FGU receives, for every Pixels die."""

    CASES = [
        # pixels type, face index, expected (fgu die, value)
        ("d4", 0, ("d4", 1)), ("d4", 3, ("d4", 4)),
        ("d6", 0, ("d6", 1)), ("d6", 5, ("d6", 6)),
        ("d6pipped", 2, ("d6", 3)),
        ("d8", 7, ("d8", 8)),
        ("d10", 0, ("d10", 10)), ("d10", 9, ("d10", 9)),
        ("d00", 0, ("d00", 0)), ("d00", 9, ("d00", 90)),
        ("d12", 11, ("d12", 12)),
        ("d20", 0, ("d20", 1)), ("d20", 19, ("d20", 20)),
    ]

    def test_face_to_fgu(self):
        for die, index, expected in self.CASES:
            with self.subTest(die=die, index=index):
                face = proto.face_from_index(index, die, 1750000000000)
                self.assertEqual(to_fgu(die, face), expected)

    def test_fudge_not_supported(self):
        self.assertIsNone(to_fgu("d6fudge", proto.face_from_index(2, "d6fudge")))

    def test_advert_die_type_nibble(self):
        service = {"x": struct.pack("<II", 1, 1750000000)}
        for value, name in proto.DIE_TYPES.items():
            adv = proto.parse_advertisement({0x0D39: bytes([6, value << 4, 5, 0, 50])}, service)
            self.assertEqual(adv.die_type, name)


class InboxTests(unittest.TestCase):
    def test_to_fgu(self):
        self.assertEqual(to_fgu("d10", 0), ("d10", 10))
        self.assertEqual(to_fgu("d6pipped", 4), ("d6", 4))
        self.assertIsNone(to_fgu("d6fudge", 3))

    def test_write_and_trim(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(Path(tmp))
            for i in range(60):
                inbox.add_roll("Bob", "d20", (i % 20) + 1)
            doc = json.loads(inbox.path.read_text(encoding="utf-8"))
            self.assertEqual(doc["lastseq"], 60)
            self.assertEqual(len(doc["rolls"]), 50)
            self.assertEqual(doc["rolls"][-1]["seq"], 60)


if __name__ == "__main__":
    unittest.main()
