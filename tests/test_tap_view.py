import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tap_view import HEIGHT, WIDTH, TapMonitor
from tapstrap import FingerAccelSample

REST = (0.0, 0.0, -1.0)


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


if __name__ == "__main__":
    unittest.main()
