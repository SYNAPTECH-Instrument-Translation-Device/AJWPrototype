import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

import phone_server
from calibration import build_calibration, save_calibration
from tests.test_calibration import STRAIGHT, make_sheet, solid
from paper_detector import detect_paper


def make_image():
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(img, (60, 40), (260, 190), (255, 255, 255), -1)
    return img


def jpeg_bytes():
    return cv2.imencode(".jpg", make_image())[1].tobytes()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = phone_server.app.test_client()
        # Never read or write the developer's real calibration/ folder.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cal_dir = Path(tmp.name)
        patcher = mock.patch.object(phone_server, "CALIBRATION_DIR", self.cal_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        phone_server.calibration = None
        phone_server.checked_size = None

    def test_detect_paper_does_not_mutate_input(self):
        img = make_image()
        original = img.copy()
        out, _ = detect_paper(img)
        self.assertTrue(np.array_equal(img, original))
        self.assertFalse(np.array_equal(out, original))

    def test_index_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_invalid_frame_rejected(self):
        self.assertEqual(self.client.post("/frame", data=b"not a jpeg").status_code, 400)

    def test_oversized_frame_rejected(self):
        resp = self.client.post("/frame", data=b"\0" * (3 * 1024 * 1024))
        self.assertEqual(resp.status_code, 413)

    def test_valid_frame_accepted(self):
        resp = self.client.post("/frame", data=jpeg_bytes())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(phone_server.process_pending())
        self.assertIsNotNone(phone_server.latest_frame)

    def test_timestamps_strictly_increase(self):
        self.client.post("/frame", data=jpeg_bytes())
        phone_server.process_pending()
        first = phone_server.last_timestamp_ms
        self.client.post("/frame", data=jpeg_bytes())
        phone_server.process_pending()
        self.assertGreater(phone_server.last_timestamp_ms, first)

    def test_newer_frame_replaces_pending(self):
        self.client.post("/frame", data=jpeg_bytes())
        self.client.post("/frame", data=jpeg_bytes())
        self.assertTrue(phone_server.process_pending())
        self.assertFalse(phone_server.process_pending())

    def test_submit_frame_feeds_pipeline(self):
        # The --camera path uses submit_frame directly, without HTTP.
        phone_server.submit_frame(make_image())
        self.assertTrue(phone_server.process_pending())

    def save_sheet_calibration(self):
        img = make_sheet(solid, STRAIGHT)[0]
        save_calibration(build_calibration([img]), self.cal_dir)
        return img

    def feed(self, frame):
        phone_server.submit_frame(frame)
        self.assertTrue(phone_server.process_pending())

    def test_no_saved_calibration_in_temp_dir(self):
        self.feed(make_image())
        self.assertIsNone(phone_server.calibration)

    def test_saved_calibration_loads(self):
        img = self.save_sheet_calibration()
        self.feed(img)
        self.assertIsNotNone(phone_server.calibration)
        self.assertEqual(len(phone_server.calibration["regions"]), 4)

    def test_rotating_back_reloads_calibration(self):
        img = self.save_sheet_calibration()
        self.feed(img)
        self.assertIsNotNone(phone_server.calibration)
        self.feed(np.ascontiguousarray(np.rot90(img)))
        self.assertIsNone(phone_server.calibration)
        self.feed(img)
        self.assertIsNotNone(phone_server.calibration)
        self.assertEqual(len(phone_server.calibration["regions"]), 4)

    def test_frame_counter(self):
        before = phone_server.frames_received
        self.client.post("/frame", data=jpeg_bytes())
        self.client.post("/frame", data=jpeg_bytes())
        self.assertEqual(phone_server.frames_received, before + 2)


def make_hand(x):
    return [types.SimpleNamespace(x=x, y=0.5) for _ in range(21)]


def make_result(hands):
    return types.SimpleNamespace(
        hand_landmarks=[make_hand(x) for _, x in hands],
        handedness=[[types.SimpleNamespace(category_name=label)] for label, _ in hands],
    )


class HandFingersTests(unittest.TestCase):
    def setUp(self):
        km = np.zeros((100, 100), int)
        km[:, :50] = 1
        km[:, 50:] = 2
        self.cal = {"frame_size": (100, 100), "key_map": km}
        self.both = make_result([("Left", 0.2), ("Right", 0.8)])

    def test_first_hand_without_strap_label(self):
        fingers, touched = phone_server.hand_fingers(self.both, self.cal, None)
        self.assertEqual(set(fingers.values()), {1})
        self.assertEqual(len(fingers), 5)
        self.assertEqual(touched, {1, 2})

    def test_strap_label_picks_that_hand(self):
        fingers, touched = phone_server.hand_fingers(self.both, self.cal, "Right")
        self.assertEqual(set(fingers.values()), {2})
        self.assertEqual(len(fingers), 5)
        self.assertEqual(touched, {1, 2})

    def test_strap_hand_missing(self):
        result = make_result([("Left", 0.2)])
        fingers, touched = phone_server.hand_fingers(result, self.cal, "Right")
        self.assertEqual(fingers, {})
        self.assertEqual(touched, {1})

    def test_no_hands(self):
        result = make_result([])
        self.assertEqual(phone_server.hand_fingers(result, self.cal, "Right"), ({}, set()))


if __name__ == "__main__":
    unittest.main()
