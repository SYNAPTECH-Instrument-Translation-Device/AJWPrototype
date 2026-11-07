import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
