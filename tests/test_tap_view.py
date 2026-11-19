import csv
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tap_view import HEIGHT, PEAK_SAMPLES, WIDTH, TapLog, TapMonitor
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

    def test_render_shows_finger_keys(self):
        with_key = TapMonitor(demo=True).render({"index": 3})
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
        self.assertTrue(t.stop())
        self.assertTrue(t.connected)
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
        tap.on_sample(sample(-1.0), 0.305)
        self.assertEqual(len(tap.pop_events()), 2)

    def test_profile_sets_per_finger_threshold(self):
        tap = TapMonitor(demo=True)
        tap.on_sample(sample(-1.3), 10.0)
        self.assertEqual(tap.pop_events(), [])  # 0.3 g is under the default 0.5 g
        tap.set_profile({"thresholds": {"thumb": 0.5, "index": 0.2, "middle": 0.5, "ring": 0.5, "pinky": 0.5}})
        tap.on_sample(sample(-1.0), 11.0)
        tap.on_sample(sample(-1.3), 12.0)
        tap.on_sample(sample(-1.0), 12.005)
        self.assertEqual(len(tap.pop_events()), 1)

    def test_event_reports_true_peak_at_crossing_time(self):
        tap = TapMonitor(demo=True)
        for z, t in [(-1.0, 0.0), (-1.6, 0.005), (-3.0, 0.010), (-2.0, 0.015)]:
            tap.on_sample(sample(z), t)
        self.assertEqual(tap.pop_events(), [])  # Still rising or ringing: wait for the peak.
        tap.on_sample(sample(-1.0), 0.020)
        (t, finger, peak), = tap.pop_events()
        self.assertEqual((t, finger), (0.005, "index"))
        self.assertAlmostEqual(peak, 2.0)

    def test_peak_wait_is_bounded(self):
        tap = TapMonitor(demo=True)
        for i in range(PEAK_SAMPLES):  # The crossing sample plus all but one of the wait.
            tap.on_sample(sample(-2.5), i * 0.005)
        self.assertEqual(tap.pop_events(), [])
        tap.on_sample(sample(-2.5), PEAK_SAMPLES * 0.005)
        self.assertEqual(len(tap.pop_events()), 1)

    def test_listener_errors_are_isolated_and_removal_sticks(self):
        tap = TapMonitor(demo=True)
        calls = []

        def bad(s, t):
            raise RuntimeError("boom")

        tap.listeners.append(bad)
        tap.listeners.append(lambda s, t: calls.append(t))
        with self.assertLogs("tap_view", "ERROR"):
            tap.on_sample(sample(-1.0), 1.0)
        self.assertEqual(calls, [1.0])
        tap.listeners.remove(bad)
        self.assertNotIn(bad, tap.listeners)

    def test_remove_waits_for_running_listener(self):
        tap = TapMonitor(demo=True)
        inside, release, log = threading.Event(), threading.Event(), []

        def slow(s, t):
            inside.set()
            release.wait(2)
            log.append("call done")

        tap.listeners.append(slow)
        worker = threading.Thread(target=tap.on_sample, args=(sample(-1.0), 1.0))
        worker.start()
        inside.wait(2)
        remover = threading.Thread(target=lambda: (tap.listeners.remove(slow), log.append("removed")))
        remover.start()
        time.sleep(0.05)
        release.set()
        worker.join(2)
        remover.join(2)
        self.assertEqual(log, ["call done", "removed"])

    def test_failed_connect_is_not_clean(self):
        class FailingStream:
            def __init__(self, *a, **k):
                self.closed_ok = True

            def on_sample(self, cb):
                pass

            async def start(self):
                self.closed_ok = False  # Its own cleanup couldn't confirm Text mode.
                raise OSError("no strap")

            async def stop(self):
                return self.closed_ok

        tap = TapMonitor()
        with mock.patch("tap_view.TapRawStream", FailingStream):
            tap.start()
            self.assertFalse(tap.stop())
        self.assertFalse(tap.connected)
        self.assertIn("no strap", tap.status)

    def test_rest_noise_no_event(self):
        tap = TapMonitor(demo=True)
        for i in range(100):
            tap.on_sample(sample(-1.2), i * 0.005)
        self.assertEqual(tap.pop_events(), [])

    def test_tap_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "taps.csv"
            log = TapLog(path)
            log.add(1.0, "index", 3, 1.2, "right")
            log.add(2.0, "ring", None, 0.8)
            log.close()
            with open(path, newline="") as f:
                rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["host_time_s", "finger", "key", "peak_g", "hands_seen"])
        self.assertEqual([r[4] for r in rows[1:]], ["right", ""])
        self.assertEqual(len(rows), 3)
        self.assertEqual([r[2] for r in rows[1:]], ["3", "0"])
        self.assertEqual(log.summary(), "Taps: 2, on a key: 1 (50%)")


if __name__ == "__main__":
    unittest.main()
