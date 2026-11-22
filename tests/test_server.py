import csv
import sys
import time
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
from tap_profile import load_profile
from tapstrap import FINGERS
from tests.test_tap_profile import START, synth


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
        # A fresh landmarker per app: VIDEO mode needs increasing timestamps per model.
        landmarker = phone_server.make_landmarker()
        self.addCleanup(landmarker.close)
        self.cam = phone_server.CameraApp(landmarker, data_dir=tmp.name)
        self.cal_dir = self.cam.cal_dir
        patcher = mock.patch.object(phone_server, "camera_app", self.cam)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        self.assertTrue(self.cam.process_pending())
        self.assertIsNotNone(self.cam.latest_frame)

    def test_recording_saves_frame_named_by_wall_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.cam.frames_dir = Path(tmp)
            self.client.post("/frame", data=jpeg_bytes())
            self.cam.process_pending()
            saved = list(Path(tmp).glob("*.jpg"))
            self.assertEqual(len(saved), 1)
            self.assertAlmostEqual(float(saved[0].stem), time.time(), delta=5)
            self.assertEqual(cv2.imread(str(saved[0])).shape, make_image().shape)

    def test_timestamps_strictly_increase(self):
        self.client.post("/frame", data=jpeg_bytes())
        self.cam.process_pending()
        first = self.cam.last_timestamp_ms
        self.client.post("/frame", data=jpeg_bytes())
        self.cam.process_pending()
        self.assertGreater(self.cam.last_timestamp_ms, first)

    def test_newer_frame_replaces_pending(self):
        self.client.post("/frame", data=jpeg_bytes())
        self.client.post("/frame", data=jpeg_bytes())
        self.assertTrue(self.cam.process_pending())
        self.assertFalse(self.cam.process_pending())

    def test_submit_frame_feeds_pipeline(self):
        # The --camera path uses submit_frame directly, without HTTP.
        self.cam.submit_frame(make_image())
        self.assertTrue(self.cam.process_pending())

    def save_sheet_calibration(self):
        img = make_sheet(solid, STRAIGHT)[0]
        save_calibration(build_calibration([img]), self.cal_dir)
        return img

    def feed(self, frame):
        self.cam.submit_frame(frame)
        self.assertTrue(self.cam.process_pending())

    def test_no_saved_calibration_in_temp_dir(self):
        self.feed(make_image())
        self.assertIsNone(self.cam.calibration)

    def test_saved_calibration_loads(self):
        img = self.save_sheet_calibration()
        self.feed(img)
        self.assertIsNotNone(self.cam.calibration)
        self.assertEqual(len(self.cam.calibration["regions"]), 4)

    def test_rotating_back_reloads_calibration(self):
        img = self.save_sheet_calibration()
        self.feed(img)
        self.assertIsNotNone(self.cam.calibration)
        self.feed(np.ascontiguousarray(np.rot90(img)))
        self.assertIsNone(self.cam.calibration)
        self.feed(img)
        self.assertIsNotNone(self.cam.calibration)
        self.assertEqual(len(self.cam.calibration["regions"]), 4)

    def test_out_of_order_frame_dropped(self):
        before = self.cam.frames_received
        for seq in ("s1 5", "s1 3", "s1 5", "s1 6", "s2 0"):
            resp = self.client.post("/frame", data=jpeg_bytes(), headers={"X-Frame-Seq": seq})
            self.assertEqual(resp.status_code, 200)
        # s1 3 and the repeated s1 5 are stale; a new page session starts over at 0.
        self.assertEqual(self.cam.frames_received, before + 3)

    def test_frame_counter(self):
        before = self.cam.frames_received
        self.client.post("/frame", data=jpeg_bytes())
        self.client.post("/frame", data=jpeg_bytes())
        self.assertEqual(self.cam.frames_received, before + 2)


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

    def test_unknown_strap_hand_with_two_hands_picks_none(self):
        fingers, touched = phone_server.hand_fingers(self.both, self.cal, None)
        self.assertEqual(fingers, {})
        self.assertEqual(touched, {1, 2})

    def test_unknown_strap_hand_with_one_hand_picks_it(self):
        fingers, _ = phone_server.hand_fingers(make_result([("Left", 0.8)]), self.cal, None)
        self.assertEqual(set(fingers.values()), {2})
        self.assertEqual(len(fingers), 5)

    def test_strap_label_picks_that_hand(self):
        fingers, touched = phone_server.hand_fingers(self.both, self.cal, "Right")
        self.assertEqual(set(fingers.values()), {2})
        self.assertEqual(len(fingers), 5)
        self.assertEqual(touched, {1, 2})

    def test_same_label_twice_matches_pick_hand(self):
        result = make_result([("Right", 0.2), ("Right", 0.8)])
        fingers, _ = phone_server.hand_fingers(result, self.cal, "Right")
        self.assertEqual(phone_server.pick_hand(result, "Right"), 0)
        self.assertEqual(set(fingers.values()), {1})  # Hand 0's keys, not hand 1's.

    def test_strap_hand_missing(self):
        result = make_result([("Left", 0.2)])
        fingers, touched = phone_server.hand_fingers(result, self.cal, "Right")
        self.assertEqual(fingers, {})
        self.assertEqual(touched, {1})

    def test_no_hands(self):
        result = make_result([])
        self.assertEqual(phone_server.hand_fingers(result, self.cal, "Right"), ({}, set()))


class FakeTap:
    """Stands in for TapMonitor: no Bluetooth, no thread."""
    demo, connected = True, True

    def __init__(self):
        self.listeners = []
        self.thresholds = {f: 0.5 for f in FINGERS}
        self.profile = None
        self.events = []
        self.stopped = False

    def set_profile(self, profile):
        self.profile = profile

    def render(self, fingers):
        return np.zeros((10, 10, 3), np.uint8)

    def pop_events(self):
        events, self.events = self.events, []
        return events

    def stop(self):
        self.stopped = True
        return True


class AppTests(unittest.TestCase):
    """Display-loop logic (keys and tick) without windows or hardware."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (mock.patch.object(phone_server, "click"), mock.patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tap = FakeTap()
        self.cam = phone_server.CameraApp(data_dir=tmp.name, tap=self.tap, session_enabled=True)
        self.addCleanup(self.cam.close)  # Runs before tmp.cleanup: Windows can't delete open files.
        self.rec_dir = self.cam.recordings_dir

    def key(self, char, now):
        return self.cam.handle_key(ord(char), now)

    def test_v_starts_and_stops_recording_twice_within_a_second(self):
        t = 1_000_000.0
        self.key("v", t)
        first = self.cam.frames_dir
        self.assertTrue(first.is_dir())
        (first / "1.000.jpg").write_bytes(b"")
        self.key("v", t + 0.2)
        self.assertIsNone(self.cam.frames_dir)
        self.assertIn("Stopped recording: 1 frames", self.cam.status_text)
        self.key("v", t + 0.4)
        self.assertNotEqual(self.cam.frames_dir, first)
        self.assertTrue(self.cam.frames_dir.is_dir())
        self.assertTrue(first.is_dir())

    def start_tap_calibration(self):
        self.key("t", START - 3)  # The calibration starts 3 s after the key.
        cal = self.cam.tap_cal
        self.assertIn(cal, self.tap.listeners)
        return cal

    def test_tap_calibration_saves_and_applies_profile(self):
        cal = self.start_tap_calibration()
        times, devs, _ = synth()
        for t, dev in zip(times, devs):
            cal(types.SimpleNamespace(magnitudes=lambda dev=dev: tuple(1 + dev)), t)
        self.cam.tick(times[-1] + 10)
        self.assertIsNone(self.cam.tap_cal)
        self.assertEqual(self.tap.listeners, [])
        self.assertIsNotNone(self.tap.profile)
        self.assertEqual(load_profile(self.cam.tap_profile_path), self.tap.profile)
        self.assertTrue(self.cam.status_text.startswith("Tap calibrated"))

    def test_tap_calibration_failure(self):
        cal = self.start_tap_calibration()
        self.cam.tick(cal.sched[-1][0] + 10)  # No strap data at all.
        self.assertIsNone(self.cam.tap_cal)
        self.assertEqual(self.tap.listeners, [])
        self.assertIsNone(self.tap.profile)
        self.assertFalse(self.cam.tap_profile_path.exists())
        self.assertIn("Press T to retry", self.cam.status_text)
        self.start_tap_calibration()  # T works again.

    def test_guided_session_needs_calibration(self):
        self.key("g", time.time())
        self.assertIsNone(self.cam.session)
        self.assertEqual(self.cam.status_text, "Calibrate (C) before a guided session.")
        self.assertEqual(list(self.rec_dir.glob("session_*")), [])

    def start_session(self, now):
        self.cam.calibration = {"regions": [1, 2, 3]}
        self.key("g", now)
        self.assertIsNotNone(self.cam.session)
        self.assertIn(self.cam.session_recorder, self.tap.listeners)
        return (self.cam.session_recorder, self.cam.session_hands, self.cam.session_events,
                self.cam.session)

    def assert_session_closed(self, parts):
        rec, hands, events, session = parts
        self.assertEqual(self.tap.listeners, [])
        self.assertTrue(rec.ff.closed and rec.fi.closed and hands.file.closed
                        and events.file.closed and session.file.closed)
        self.assertIsNone(self.cam.session)
        self.assertIsNone(self.cam.session_hands)
        names = {p.name.split("_", 3)[-1] for p in self.rec_dir.glob("session_*")}
        self.assertEqual(names, {"fingers.csv", "imu.csv", "hand.csv", "events.csv", "cues.csv"})

    def test_guided_session_runs_and_cleans_up(self):
        now = time.time()
        parts = self.start_session(now)
        self.key("t", now)
        self.assertIsNone(self.cam.tap_cal)  # No tap calibration during a session.
        self.cam.latest_fingers = {"index": 2}
        self.tap.events = [(now, "index", 1.0)]
        self.cam.tick(now)
        self.cam.tick(now + 10_000)  # Past the last cue: the session ends itself.
        self.assert_session_closed(parts)
        with open(f"{self.cam.session_prefix}_events.csv", newline="") as f:
            self.assertEqual(list(csv.reader(f))[1][1:3], ["index", "2"])
        with open(f"{self.cam.session_prefix}_cues.csv", newline="") as f:
            self.assertEqual(list(csv.reader(f))[-1][1], "idle_end")

    def test_tap_logs_hands_seen_when_strap_hand_missing(self):
        # Camera sees only a left hand while the strap is on the right: no key, and the log says why.
        self.cam.strap_label = "Right"
        self.cam.latest_fingers, self.cam.latest_hands_seen = {}, "left"
        self.tap.events = [(1.0, "index", 1.0)]
        self.cam.tick(1.0)
        self.cam.tap_log.file.flush()
        with open(self.cam.tap_log.file.name, newline="") as f:
            self.assertEqual(list(csv.reader(f))[1][1:], ["index", "0", "1.000", "left"])

    def test_auto_mode_learns_strap_hand_from_taps(self):
        cam = self.cam  # strap_label None = auto.
        both = [("Left", {"index": 0, "middle": 3}), ("Right", {"index": 5, "middle": 4})]
        # Unknown hand, two in view: the lone hand with the finger on a key gives the key.
        self.assertEqual(cam.tap_key("index", {}, both), 5)
        self.assertEqual(cam.strap_hand_label(), "Right")
        # Both hands on a key: ambiguous, no vote; the learned hand's key is used.
        self.assertEqual(cam.tap_key("middle", {"index": 5, "middle": 4}, both), 4)
        self.assertEqual(cam.label_votes, {"Right": 1})
        # A flipped label now and then doesn't take over.
        cam.tap_key("index", {}, [("Left", {"index": 2})])
        cam.tap_key("index", {}, [("Right", {"index": 2})])
        self.assertEqual(cam.strap_hand_label(), "Right")

    def test_fixed_hand_never_votes(self):
        self.cam.strap_label = "Left"
        self.assertEqual(self.cam.tap_key("index", {}, [("Right", {"index": 5})]), None)
        self.assertEqual(self.cam.strap_hand_label(), "Left")
        self.assertFalse(self.cam.label_votes)

    def test_quit_mid_session_keeps_files(self):
        parts = self.start_session(time.time())
        self.assertFalse(self.key("q", time.time()))
        self.cam.close()
        self.assert_session_closed(parts)
        self.assertTrue(self.tap.stopped)
        self.assertTrue(self.cam.tap_log.file.closed)

if __name__ == "__main__":
    unittest.main()
