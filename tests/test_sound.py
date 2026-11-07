import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import NotePlayer, key_note, tap_velocity


class FakePort:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg)

    def close(self):
        self.closed = True


class SoundTest(unittest.TestCase):
    def test_key_note(self):
        self.assertEqual(key_note(1), 60)
        self.assertEqual(key_note(13), 72)
        self.assertEqual(key_note(1, base_note=48), 48)

    def test_tap_velocity(self):
        self.assertEqual(tap_velocity(0.5), 40)
        self.assertEqual(tap_velocity(3.0), 127)
        self.assertEqual(tap_velocity(10), 127)
        self.assertEqual(tap_velocity(0), 40)

    def test_program_change_first(self):
        port = FakePort()
        NotePlayer(program=40, port=port)
        self.assertEqual(port.sent[0].type, "program_change")
        self.assertEqual(port.sent[0].program, 40)

    def test_note_off_after_note_length(self):
        port = FakePort()
        player = NotePlayer(port=port)
        player.play(60, 100)
        self.assertEqual((port.sent[-1].type, port.sent[-1].note), ("note_on", 60))
        player.update(now=time.monotonic())
        self.assertEqual(len(port.sent), 2)
        player.update(now=time.monotonic() + 1)
        self.assertEqual((port.sent[-1].type, port.sent[-1].note), ("note_off", 60))

    def test_out_of_range_note_is_silent(self):
        port = FakePort()
        player = NotePlayer(port=port)
        player.play(200, 100)
        self.assertEqual(len(port.sent), 1)

    def test_close_stops_notes_and_port(self):
        port = FakePort()
        player = NotePlayer(port=port)
        player.play(60, 100)
        player.close()
        self.assertEqual((port.sent[-1].type, port.sent[-1].note), ("note_off", 60))
        self.assertTrue(port.closed)


if __name__ == "__main__":
    unittest.main()
