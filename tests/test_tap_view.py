import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tap_view import HEIGHT, WIDTH, TapMonitor
from tapstrap import FingerAccelSample

REST = (0.0, 0.0, -1.0)


def sample(index_z):
    return FingerAccelSample(0, REST, (0.0, 0.0, index_z), REST, REST, REST)


class TapViewTests(unittest.TestCase):
    def test_spike_raises_only_that_finger(self):
        tap = TapMonitor(demo=True)
        tap.on_sample(FingerAccelSample(0, REST, (0.0, 0.0, -2.5), REST, REST, REST))
        self.assertAlmostEqual(tap.activity["index"], 1.5)
        self.assertEqual(tap.activity["thumb"], 0.0)

    def test_render_size_and_decay(self):
        tap = TapMonitor(demo=True)
        tap.on_sample(FingerAccelSample(0, REST, (0.0, 0.0, -2.5), REST, REST, REST))
        tap.last_render -= 0.1  # One half-life since the last render.
        img = tap.render({"index": 3, "thumb": None})
        self.assertEqual(img.shape, (HEIGHT, WIDTH, 3))
        self.assertLess(tap.activity["index"], 1.5)

    def test_render_accepts_camera_finger_names(self):
        with_key = TapMonitor(demo=True).render({"Index": 3})
        without = TapMonitor(demo=True).render({})
        self.assertFalse(np.array_equal(with_key, without))

    def test_status_goes_stale(self):
        tap = TapMonitor(demo=True)
        sample = FingerAccelSample(0, REST, REST, REST, REST, REST)
        tap.on_sample(sample)
        tap.last_sample -= 2
        self.assertTrue(tap.display_status(time.monotonic()).startswith("Tap: no data"))
        self.assertEqual(tap.render().shape, (HEIGHT, WIDTH, 3))
        tap.on_sample(sample)
        self.assertEqual(tap.display_status(time.monotonic()), tap.status)

    def test_demo_thread_starts_and_stops(self):
        t = TapMonitor(demo=True)
        t.start()
        deadline = time.monotonic() + 2
        while t.last_sample is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(t.last_sample)
        t.stop()
        self.assertFalse(t.thread.is_alive())

    def test_one_event_per_tap(self):
        tap = TapMonitor(demo=True)
        for z, t in [(-1.0, 0.0), (-2.5, 0.005), (-2.5, 0.010), (-1.0, 0.015)]:
            tap.on_sample(sample(z), t)
        events = tap.pop_events()
        self.assertEqual(len(events), 1)
        t, finger, peak = events[0]
        self.assertAlmostEqual(t, 0.005)
        self.assertEqual(finger, "index")
        self.assertAlmostEqual(peak, 1.5)
        self.assertEqual(tap.pop_events(), [])

    def test_refractory(self):
        tap = TapMonitor(demo=True)
        for z, t in [(-2.5, 0.0), (-1.0, 0.01), (-2.5, 0.05)]:
            tap.on_sample(sample(z), t)
        self.assertEqual(len(tap.events), 1)
        tap.on_sample(sample(-1.0), 0.06)
        tap.on_sample(sample(-2.5), 0.30)
        self.assertEqual(len(tap.pop_events()), 2)

    def test_rest_noise_no_event(self):
        tap = TapMonitor(demo=True)
        for i in range(100):
            tap.on_sample(sample(-1.2), i * 0.005)
        self.assertEqual(tap.pop_events(), [])


if __name__ == "__main__":
    unittest.main()
