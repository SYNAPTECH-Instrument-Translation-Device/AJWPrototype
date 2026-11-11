import csv
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session import CHORDS, GuidedSession, HandLog, build_cues
from tapstrap import FINGERS


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def fake_hand():
    return [types.SimpleNamespace(x=i / 100, y=i / 100, z=0.0) for i in range(21)]


class TestBuildCues(unittest.TestCase):
    def test_shape(self):
        cues = build_cues(12, singles=40, chords=10, seed=1)
        self.assertEqual(len(cues), 51)
        self.assertEqual(cues[-1], ("idle", (), ()))
        singles = [c for c in cues if c[0] == "tap"]
        for f in FINGERS:
            self.assertEqual(sum(c[1] == (f,) for c in singles), 8)
        self.assertTrue(all(1 <= c[2][0] <= 12 for c in singles))
        self.assertTrue(all(c[1] in CHORDS for c in cues if c[0] == "chord"))

    def test_seed(self):
        self.assertEqual(build_cues(12, seed=1), build_cues(12, seed=1))
        self.assertNotEqual(build_cues(12, seed=1), build_cues(12, seed=2))


class TestGuidedSession(unittest.TestCase):
    def test_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cues.csv"
            beeps = []
            cues = [("tap", ("index",), (3,)), ("chord", ("index", "middle"), ()), ("idle", (), ())]
            s = GuidedSession(cues, path, 100.0, beep=lambda: beeps.append(1))
            self.assertIn("INDEX on key 3", s.update(100.0))
            self.assertEqual(len(beeps), 0)
            s.update(101.6)
            self.assertEqual(len(beeps), 1)
            s.update(104.6)
            self.assertEqual(len(beeps), 2)
            self.assertIn("DON'T tap", s.update(107.6))
            self.assertIsNone(s.update(107.6 + 20.1))
            self.assertTrue(s.done)
            s.close()
            rows = read_rows(path)[1:]
            self.assertEqual([r[1] for r in rows], ["tap", "chord", "idle_start", "idle_end"])
            self.assertEqual(rows[0][0], "101.5000")
            self.assertEqual([rows[0][2], rows[1][2]], ["index", "index+middle"])
            self.assertEqual([rows[0][3], rows[1][3]], ["3", ""])


class TestHandLog(unittest.TestCase):
    def test_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hand.csv"
            log = HandLog(path)
            log.add(1.0, fake_hand(), {"Index": 4})
            log.add(2.0, None, {})
            log.close()
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["index_tip_x"], "0.0800")
            self.assertEqual(rows[0]["index_key"], "4")
            self.assertEqual(rows[0]["thumb_key"], "0")


if __name__ == "__main__":
    unittest.main()
