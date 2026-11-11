import csv
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session import CHORDS, GuidedSession, HandLog, build_cues
from session_analyze import analyze
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


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows([header] + rows)


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = str(Path(self.tmp.name) / "s")
        write_csv(f"{self.prefix}_cues.csv", ["host_time_s", "kind", "fingers", "keys"], [
            ["10.0", "tap", "index", "3"], ["13.0", "tap", "ring", "5"],
            ["16.0", "chord", "index+middle", ""],
            ["20.0", "idle_start", "", ""], ["30.0", "idle_end", "", ""]])
        write_csv(f"{self.prefix}_events.csv", ["host_time_s", "finger", "key", "peak_g"], [
            ["10.1", "index", "3", "1.0"], ["10.11", "middle", "3", "1.0"],
            ["16.05", "index", "2", "1.0"], ["16.06", "middle", "3", "1.0"],
            ["25.0", "pinky", "0", "1.0"], ["40.0", "thumb", "1", "1.0"]])

    def tearDown(self):
        self.tmp.cleanup()

    def test_scores(self):
        report = "\n".join(analyze(self.prefix))
        for s in ["tap detected: 1/2", "right key: 1/1", "tap cues with extra fingers: 1/2",
                  "chord complete: 1/1", "chord exact: 1/1",
                  "false taps while idle: 1 in 10 s (6.0/min)", "unmatched events: 1",
                  "lag sweep: skipped"]:
            self.assertIn(s, report)

    def test_lag_sweep(self):
        log = HandLog(f"{self.prefix}_hand.csv")
        for t in (9.9, 9.95, 10.05, 10.08):
            log.add(t, fake_hand(), {"Index": 2 if t < 10.05 else 3})
        log.close()
        report = analyze(self.prefix)
        self.assertIn("lag 0 ms key acc: 1/1 (100%)", report)
        self.assertIn("lag 100 ms key acc: 0/1 (0%)", report)
        self.assertIn("lag best: 0 ms, 1/1 (100%)", report)


if __name__ == "__main__":
    unittest.main()
