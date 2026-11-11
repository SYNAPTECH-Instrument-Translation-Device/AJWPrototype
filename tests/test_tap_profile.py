import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tap_profile import (REST_S, TAPS_PER_FINGER, TapCalibration, fit_profile, load_profile,
                         save_profile, schedule)
from tapstrap import FINGERS

START, HZ = 100.0, 200


def synth(skip=None):
    sched = schedule(START)
    rng = np.random.default_rng(0)
    times = np.arange(START - 1, sched[-1][0] + 2, 1 / HZ)
    devs = np.abs(rng.normal(0, 0.02, (len(times), 5)))
    for t, kind, f in sched:
        if kind != "tap" or f == skip:
            continue
        i = FINGERS.index(f)
        peak = 0.6 if f == "pinky" else 1.0
        k = int(np.argmin(np.abs(times - (t + 0.15))))
        devs[k, i] = peak
        devs[k, (i + 1) % 5] = 0.3 * peak
    return times, devs, sched


class TapProfileTests(unittest.TestCase):
    def test_schedule(self):
        s = schedule(0)
        self.assertEqual(len(s), 2 + 5 * TAPS_PER_FINGER)
        self.assertEqual(s[2][0], REST_S + 2.0)
        self.assertEqual([f for _, k, f in s if k == "tap"],
                         [f for f in FINGERS for _ in range(TAPS_PER_FINGER)])

    def test_fit(self):
        p = fit_profile(*synth())
        for f in FINGERS:
            self.assertGreaterEqual(p["thresholds"][f], p["noise"][f] + 0.05)
            self.assertLess(p["thresholds"][f], p["weakest_tap"][f])
        self.assertLess(p["thresholds"]["pinky"], p["thresholds"]["index"])
        self.assertAlmostEqual(p["crosstalk"]["index"]["middle"], 0.3, delta=0.05)
        self.assertLess(p["crosstalk"]["index"]["ring"], 0.1)
        self.assertEqual(p["warnings"], [])

    def test_missing_finger_warns(self):
        p = fit_profile(*synth(skip="ring"))
        self.assertTrue(any("ring" in w for w in p["warnings"]))

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            self.assertIsNone(load_profile(path))
            p = fit_profile(*synth())
            save_profile(p, path)
            self.assertEqual(load_profile(path), p)
            path.write_text('{"thresholds": {"thumb": 0.5}}')
            self.assertIsNone(load_profile(path))

    def test_calibration(self):
        beeps = []
        cal = TapCalibration(0, beep=lambda: beeps.append(1))
        cal(types.SimpleNamespace(magnitudes=lambda: (1.0, 1.5, 1.0, 1.0, 1.0)), 1.0)
        self.assertEqual(cal.devs[-1][1], 0.5)
        cal(types.SimpleNamespace(gyro_dps=(0, 0, 0)), 1.0)
        self.assertEqual(len(cal.times), 1)
        self.assertIsNotNone(cal.update(1.0))
        self.assertIsNone(cal.update(cal.sched[-1][0] + 0.7))
        self.assertEqual(len(beeps), 25)


if __name__ == "__main__":
    unittest.main()
