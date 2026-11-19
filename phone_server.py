import argparse
import hmac
import os
import secrets
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from flask import Flask, request, send_from_directory
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from calibration import (
    FINGERTIPS,
    INK_RATIO,
    LINE_KERNEL,
    build_calibration,
    draw_calibration,
    load_calibration,
    rebuild_calibration,
    fingertip,
    region_at,
    save_calibration,
)
from paper_detector import detect_paper
from recording import Recorder, click
from session import GuidedSession, HandLog, build_cues
from tap_profile import TapCalibration, load_profile, save_profile
from tap_view import TapLog, TapMonitor

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "hand_landmarker.task"

app = Flask(__name__)
# Frames are small JPEGs; reject anything larger.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
# Always revalidate the page and script so phones pick up changes.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

CALIBRATION_FRAMES = 15
SETTINGS_WINDOW = "Calibration settings"
CAMERA_WINDOW = "Phone Camera Feed"
TAP_WINDOW = "Tap Strap"
CAMERA_MAX_WIDTH = 640     # Webcam frames are shrunk to this for speed.
# Shared secret for POST /frame: through ngrok the server is reachable from the internet.
FRAME_TOKEN = os.environ.get("PHONE_TOKEN") or secrets.token_urlsafe(16)

camera_app = None  # The CameraApp that POST /frame feeds; set by main().


def make_landmarker(running_mode=vision.RunningMode.VIDEO):
    """MediaPipe Hand Landmarker for up to two hands. Built on demand, not at import."""
    return vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=running_mode,
        num_hands=2,
    ))


def draw_hand_landmarks(frame, result):
    height, width, _ = frame.shape

    connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    for hand_landmarks in result.hand_landmarks:
        # Draw connections between landmarks.
        for connection in connections:
            start = hand_landmarks[connection.start]
            end = hand_landmarks[connection.end]

            start_point = (
                int(start.x * width),
                int(start.y * height),
            )
            end_point = (
                int(end.x * width),
                int(end.y * height),
            )

            cv2.line(
                frame,
                start_point,
                end_point,
                (0, 255, 0),
                2,
            )

        # Draw each landmark.
        for landmark in hand_landmarks:
            point = (
                int(landmark.x * width),
                int(landmark.y * height),
            )

            cv2.circle(frame, point, 4, (0, 0, 255), -1)

    return frame


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "phone_camera.html")


@app.get("/phone_camera.css")
def camera_css():
    return send_from_directory(BASE_DIR, "phone_camera.css")


@app.get("/phone_camera.js")
def camera_js():
    return send_from_directory(BASE_DIR, "phone_camera.js")


@app.post("/frame")
def receive_frame():
    token = request.headers.get("X-Frame-Token", "").encode()
    if not hmac.compare_digest(token, FRAME_TOKEN.encode()):
        return "Missing or wrong token: open the link the server printed.", 403
    seq = None
    if "X-Frame-Seq" in request.headers:
        try:
            session_id, number = request.headers["X-Frame-Seq"].split()
            seq = (session_id, int(number))
        except ValueError:
            return "Bad X-Frame-Seq", 400

    image_bytes = np.frombuffer(request.get_data(), dtype=np.uint8)
    frame = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)

    if frame is None:
        return "Invalid image", 400

    camera_app.submit_frame(frame, seq)
    return "OK", 200


def open_camera(index):
    # DirectShow is the Windows backend that lists virtual webcams like Camo;
    # AVFoundation is the macOS one (built-in camera, Continuity Camera, Camo).
    # Use the camera's own resolution: asking Camo for 640x480 makes it send
    # all-black frames.
    if sys.platform == "win32":
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if sys.platform == "darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def list_cameras(max_index=6):
    for index in range(max_index):
        cap = open_camera(index)
        opened = cap.isOpened()
        ok, frame = False, None
        if opened:
            # Continuity Camera (iPhone) can take a second to send its first frame.
            for _ in range(30):
                ok, frame = cap.read()
                if ok:
                    break
                time.sleep(0.1)
        cap.release()
        if ok:
            print(f"  camera {index}: {frame.shape[1]}x{frame.shape[0]}")
        elif opened:
            print(f"  camera {index}: opened but sent no frames")


def camera_loop(index, submit_frame):
    # Feed a local webcam (e.g. the iPhone via Camo over USB) into the same pipeline.
    cap = open_camera(index)
    if not cap.isOpened():
        print(f"Can't open camera {index}. Try --list-cameras.")
        return
    while True:
        ok, frame = cap.read()
        if ok:
            if frame.shape[1] > CAMERA_MAX_WIDTH:
                # Camo sends 1280x720; a quarter of the pixels is far cheaper
                # to process and still plenty for the paper keyboard.
                scale = CAMERA_MAX_WIDTH / frame.shape[1]
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            submit_frame(frame)
        else:
            time.sleep(0.05)


def pick_hand(result, strap_label=None):
    """Index of the strap hand in result.hand_landmarks, or None (same rule as hand_fingers)."""
    for i in range(len(result.hand_landmarks)):
        label = result.handedness[i][0].category_name if i < len(result.handedness) else None
        if (strap_label is None and i == 0) or (strap_label is not None and label == strap_label):
            return i
    return None


def hand_fingers(result, cal, strap_label=None):
    """Return (fingers of the chosen hand, regions under any fingertip).

    The chosen hand is the one MediaPipe labels strap_label, or the first hand if
    strap_label is None. fingers is {} when that hand isn't visible.
    """
    chosen, touched = {}, set()
    strap_i = pick_hand(result, strap_label)
    for i, hand in enumerate(result.hand_landmarks):
        fingers = {name: region_at(cal, *fingertip(hand, k)) for name, k in FINGERTIPS.items()}
        touched |= {r for r in fingers.values() if r}
        if i == strap_i:
            chosen = fingers
    return chosen, touched


SETTINGS_HELP = [
    "Sens = sensitivity (default 50)",
    "  Raise if lines or keys are missed.",
    "  Lower if shadows or paper texture become regions.",
    "Key = min black key size (default 15)",
    "  Lower for small drawings where black keys",
    "  vanish or merge into white keys.",
    "Changes re-detect ~0.3 s after you stop dragging.",
]


def settings_help_image():
    image = np.full((22 * len(SETTINGS_HELP) + 12, 470, 3), 30, np.uint8)
    for i, line in enumerate(SETTINGS_HELP):
        cv2.putText(
            image, line, (8, 22 + 22 * i),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1,
        )
    return image


class CameraApp:
    """All app state. Three threads use it:

    - the frame source (Flask or camera_loop) calls submit_frame,
    - the processing thread runs process_loop,
    - the display loop in main() calls slider_positions/set_sliders, tick and handle_key.
    frame_lock guards what processing and display share; pending_lock the pending frame.
    """

    def __init__(self, landmarker=None, data_dir=BASE_DIR, tap=None, player=None, base_note=60,
                 session_enabled=False, strap_label=None):
        self.landmarker = landmarker
        self.cal_dir = Path(data_dir) / "calibration"
        self.tap_profile_path = self.cal_dir / "tap_profile.json"
        self.samples_dir = Path(data_dir) / "samples"
        self.recordings_dir = Path(data_dir) / "recordings"
        self.tap, self.player, self.base_note = tap, player, base_note
        self.session_enabled = session_enabled
        self.strap_label = strap_label  # MediaPipe label of the strap hand; None = first hand.

        self.frame_lock = threading.Lock()
        self.landmarker_lock = threading.Lock()
        self.last_timestamp_ms = 0
        self.calibration = None
        self.checked_size = None   # Frame size the saved calibration was last tried for.
        self.calibrating = False
        self.calibration_frames = []
        self.latest_frame = None
        self.latest_raw = None
        self.latest_fingers = {}
        self.latest_hand = None    # Strap-hand landmarks of the newest frame (for session logs).
        self.status_text = "Press C to calibrate."
        self.ink_ratio_setting = INK_RATIO
        self.line_kernel_setting = LINE_KERNEL

        self.pending_lock = threading.Lock()
        self.pending_event = threading.Event()
        self.pending_frame = None
        self.pending_time = 0.0
        self.newest_seq = (None, -1)  # (page session, frame number) of the newest phone frame.
        self.frames_received = 0
        self.process_ms = 0.0
        self.age_ms = 0.0             # Arrival on the laptop -> processed and ready to show.

        # Set by the display loop; the processing thread reads frames_dir and session_hands.
        self.frames_dir = None        # Folder every processed frame is saved to while V recording is on.
        self.session = None
        self.session_prefix = None
        self.session_recorder = None
        self.session_hands = None     # session.HandLog while a guided session runs.
        self.session_events = None
        self.tap_cal = None
        self.applied = (None, None)   # Settings the trackbars were last set to.
        self.slider_pending = None    # (settings, time first seen) while debouncing.
        self.last_rx_count = 0
        self.last_rx_time = time.monotonic()
        self.rx_fps = 0.0

        self.tap_log = None
        if tap is not None:
            profile = load_profile(self.tap_profile_path)
            if profile is not None:
                tap.set_profile(profile)
                print(f"Tap profile loaded ({profile['created']}).")
            self.tap_log = TapLog(self.recordings_dir / f"taps_{time.strftime('%Y%m%d_%H%M%S')}.csv")

    def submit_frame(self, frame, seq=None):
        # A newer frame replaces an unprocessed older one, so the server never falls behind.
        with self.pending_lock:
            if seq is not None:
                # Parallel POSTs can arrive out of order: drop one older than the newest seen.
                # A reloaded page has a new session id, so its numbers start over.
                if seq[0] == self.newest_seq[0] and seq[1] <= self.newest_seq[1]:
                    return
                self.newest_seq = seq
            self.pending_frame = frame
            self.pending_time = time.perf_counter()
            self.frames_received += 1
        self.pending_event.set()

    def process_frame(self, frame):
        # Detect the paper.
        annotated, _ = detect_paper(frame)

        # Convert BGR (OpenCV) to RGB (MediaPipe).
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame,
        )

        # VIDEO mode needs strictly increasing timestamps and is not thread-safe.
        with self.landmarker_lock:
            timestamp_ms = max(int(time.monotonic() * 1000), self.last_timestamp_ms + 1)
            self.last_timestamp_ms = timestamp_ms
            result = self.landmarker.detect_for_video(mp_image, timestamp_ms)

        frame_size = (frame.shape[1], frame.shape[0])
        build = None
        with self.frame_lock:
            self.latest_raw = frame
            # Try the saved calibration once per frame size, so rotating back reloads it.
            if self.calibration is None and self.checked_size != frame_size:
                self.checked_size = frame_size
                self.calibration = load_calibration(self.cal_dir, frame.shape)
                if self.calibration is not None:
                    self.ink_ratio_setting = self.calibration["settings"]["ink_ratio"]
                    self.line_kernel_setting = self.calibration["settings"]["line_kernel"]
                    self.status_text = (
                        f"Loaded calibration: {len(self.calibration['regions'])} regions."
                    )
            if self.calibrating:
                if result.hand_landmarks:
                    self.calibration_frames.clear()
                    self.status_text = "Calibrating: keep your hands out of view."
                else:
                    self.calibration_frames.append(frame)
                if len(self.calibration_frames) >= CALIBRATION_FRAMES:
                    build = (self.calibration_frames, self.ink_ratio_setting, self.line_kernel_setting)
        if build is not None:
            # Build outside frame_lock so the display thread doesn't stall meanwhile.
            new_cal, message = None, "Calibration failed (see terminal). Press C to retry."
            try:
                new_cal = build_calibration(*build)
                message = f"Calibrated: {len(new_cal['regions'])} regions."
            except ValueError as error:
                message = f"Calibration failed: {error} Press C to retry."
            finally:
                with self.frame_lock:
                    if self.calibration_frames is build[0]:  # C wasn't pressed again meanwhile.
                        if new_cal is not None:
                            self.calibration = new_cal
                        self.status_text = message
                        self.calibrating = False
                        self.calibration_frames = []
                    else:
                        new_cal = None
            if new_cal is not None:
                save_calibration(new_cal, self.cal_dir)
        with self.frame_lock:
            if self.calibration is not None and self.calibration["frame_size"] != frame_size:
                self.calibration = None
                self.checked_size = frame_size
                self.status_text = "Frame size changed (phone rotated?): press C to recalibrate."
            cal = self.calibration if not self.calibrating else None

        fingers = {}
        if cal is not None:
            fingers, touched = hand_fingers(result, cal, self.strap_label)
            annotated = draw_calibration(annotated, cal, touched)

        # Draw detected hand landmarks on top of the overlay.
        annotated = draw_hand_landmarks(annotated, result)

        i = pick_hand(result, self.strap_label) if cal is not None else None
        hand = result.hand_landmarks[i] if i is not None else None
        with self.frame_lock:
            self.latest_frame = annotated
            self.latest_fingers = fingers
            self.latest_hand = hand

    def process_pending(self):
        with self.pending_lock:
            frame = self.pending_frame
            arrived = self.pending_time
            self.pending_frame = None
            self.pending_event.clear()
        if frame is None:
            return False

        start = time.perf_counter()
        self.process_frame(frame)
        # Arrival time on the wall clock, the same clock the strap, tap and cue files use.
        arrived_wall = time.time() - (time.perf_counter() - arrived)
        hands = self.session_hands  # One read: the display thread may end the session meanwhile.
        if hands is not None:
            with self.frame_lock:
                hand, fingers = self.latest_hand, dict(self.latest_fingers)
            hands.add(arrived_wall, hand, fingers)
        record_dir = self.frames_dir
        if record_dir is not None:
            # The exact image MediaPipe saw; the name matches tap logs' host_time_s.
            cv2.imwrite(str(record_dir / f"{arrived_wall:.3f}.jpg"), frame)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.process_ms = 0.9 * self.process_ms + 0.1 * elapsed_ms
        self.age_ms = 0.9 * self.age_ms + 0.1 * (time.perf_counter() - arrived) * 1000
        return True

    def process_loop(self):
        # One bad frame must not kill this thread: the window would freeze for good.
        while True:
            self.pending_event.wait()
            try:
                self.process_pending()
            except Exception:
                traceback.print_exc()

    def slider_positions(self):
        """(Sens, Key) to move the trackbars to when the calibration's settings changed, else None."""
        with self.frame_lock:
            if self.calibration is None:
                return None
            cs = self.calibration["settings"]
            settings = (cs["ink_ratio"], cs["line_kernel"])
        if settings == self.applied:
            return None
        self.applied = settings
        return round((settings[0] - 0.5) / 0.4 * 100), settings[1]

    def set_sliders(self, sens, kern, now):
        """Trackbar values; re-detects 0.3 s after they stop changing. now is time.monotonic()."""
        kern = max(3, kern)
        want = (0.5 + 0.4 * sens / 100, kern)
        if want == (self.ink_ratio_setting, self.line_kernel_setting):
            self.slider_pending = None
        elif self.slider_pending is None or self.slider_pending[0] != want:
            self.slider_pending = (want, now)
        elif now - self.slider_pending[1] >= 0.3:
            self.slider_pending = None
            with self.frame_lock:
                self.ink_ratio_setting, self.line_kernel_setting = want
                old_cal = self.calibration if not self.calibrating else None
            if old_cal is not None:
                # Re-detect outside frame_lock so frame processing doesn't stall.
                try:
                    new_cal = rebuild_calibration(old_cal, *want)
                    message = (
                        f"Re-detected: {len(new_cal['regions'])} regions "
                        f"(sens {sens}, key {kern})"
                    )
                except ValueError as error:
                    new_cal, message = None, str(error)
                with self.frame_lock:
                    # Drop the result if the calibration was reset or redone meanwhile.
                    if self.calibration is not old_cal or self.calibrating:
                        new_cal = None
                    else:
                        if new_cal is not None:
                            self.calibration = new_cal
                        self.status_text = message
                if new_cal is not None:
                    save_calibration(new_cal, self.cal_dir)
                    self.applied = want

    def set_status(self, message):
        with self.frame_lock:
            self.status_text = message

    def tick(self, now):
        """Per-frame display work; now is time.time(). Returns {window name: image} to show."""
        mono = time.monotonic()
        if mono - self.last_rx_time >= 1.0:
            with self.pending_lock:
                count = self.frames_received
            self.rx_fps = (count - self.last_rx_count) / (mono - self.last_rx_time)
            self.last_rx_count, self.last_rx_time = count, mono

        with self.frame_lock:
            frame = (
                self.latest_frame.copy()
                if self.latest_frame is not None
                else None
            )
            status = self.status_text
            fingers = dict(self.latest_fingers)

        if frame is None:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(
            frame, status, (5, 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
        )
        cv2.putText(
            frame, f"rx {self.rx_fps:.1f} fps  proc {self.process_ms:.0f} ms  age {self.age_ms:.0f} ms",
            (5, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
        )
        if fingers:
            cv2.putText(
                frame,
                "  ".join(f"{name[0].upper()}:{rid or '-'}" for name, rid in fingers.items()),
                (5, frame.shape[0] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
            )
        if self.session is not None:
            text = self.session.update(now)
            if text is None:
                print(f"Session done. Score it: python session_analyze.py {self.session_prefix}")
                self.end_session()
            else:
                cv2.putText(frame, text, (5, frame.shape[0] // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        if self.tap_cal is not None:
            text = self.tap_cal.update(now)
            if text is None:
                self.finish_tap_calibration()
            else:
                cv2.putText(frame, text, (5, frame.shape[0] // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        images = {CAMERA_WINDOW: frame}
        if self.tap is not None:
            images[TAP_WINDOW] = self.tap.render(fingers)
            for host_time, finger, peak in self.tap.pop_events():
                key = fingers.get(finger)
                self.tap_log.add(host_time, finger, key, peak)
                if self.session_events is not None:
                    self.session_events.add(host_time, finger, key, peak)
                if self.player is not None and key:
                    from sound import key_note, tap_velocity  # Only loaded when sound works.
                    self.player.play(key_note(key, self.base_note), tap_velocity(peak, self.tap.thresholds[finger]))
            if self.player is not None:
                self.player.update()
        return images

    def finish_tap_calibration(self):
        self.tap.listeners.remove(self.tap_cal)
        try:
            profile = self.tap_cal.fit()
            self.cal_dir.mkdir(exist_ok=True)
            save_profile(profile, self.tap_profile_path)
            self.tap.set_profile(profile)
            msg = "Tap calibrated: " + "  ".join(
                f"{f[0]}:{profile['thresholds'][f]:.2f}" for f in profile["thresholds"])
            for w in profile["warnings"]:
                print("Tap calibration warning:", w)
        except ValueError as error:
            msg = f"Tap calibration failed: {error} Press T to retry."
        print(msg)
        self.set_status(msg)
        self.tap_cal = None

    def handle_key(self, key, now):
        """React to a cv2.waitKey code; now is time.time(). Returns False when the app should quit."""
        if key == ord("q"):
            return False
        if key == ord("c"):
            with self.frame_lock:
                self.calibrating = True
                self.calibration_frames = []
                self.status_text = "Calibrating: keep your hands out of view."
        elif key == ord("s"):
            with self.frame_lock:
                raw = self.latest_raw.copy() if self.latest_raw is not None else None
            if raw is not None:
                self.samples_dir.mkdir(exist_ok=True)
                path = self.samples_dir / f"frame_{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}.jpg"
                cv2.imwrite(str(path), raw)
                print(path)
                self.set_status(f"Saved {path.name}")
        elif key == ord("v"):
            if self.frames_dir is None:
                # Milliseconds too: start/stop/start within one second must not reuse a name.
                stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
                new_dir = self.recordings_dir / f"frames_{stamp}_{int(now * 1000) % 1000:03d}"
                new_dir.mkdir(parents=True)
                self.frames_dir = new_dir
                message = f"Recording frames to {new_dir.name} (V to stop)"
            else:
                message = (f"Stopped recording: {len(list(self.frames_dir.glob('*.jpg')))} frames "
                           f"in {self.frames_dir.name}")
                self.frames_dir = None
            print(message)
            self.set_status(message)
        elif key == ord("t") and self.tap is not None and self.tap_cal is None and self.session is None:
            self.tap_cal = TapCalibration(now + 3, beep=click)
            self.tap.listeners.append(self.tap_cal)
        elif (key == ord("g") and self.session_enabled and self.tap is not None
              and self.session is None and self.tap_cal is None):
            self.start_session(now)
        return True

    def start_session(self, now):
        with self.frame_lock:
            n_keys = len(self.calibration["regions"]) if self.calibration is not None else 0
        if n_keys == 0:
            self.set_status("Calibrate (C) before a guided session.")
            return
        prefix = self.recordings_dir / f"session_{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}"
        prefix.parent.mkdir(exist_ok=True)
        self.session_prefix = prefix
        self.session_recorder = Recorder(str(prefix))
        self.tap.listeners.append(self.session_recorder)
        self.session_hands = HandLog(f"{prefix}_hand.csv")
        self.session_events = TapLog(f"{prefix}_events.csv")
        self.session = GuidedSession(build_cues(n_keys), f"{prefix}_cues.csv", now + 3, beep=click)
        print(f"Guided session: {prefix}")

    def end_session(self):
        """Stop and close a guided session's recorders, keeping its files."""
        # Unhook first: the strap thread calls listeners, so no late write hits a closed file.
        if self.session_recorder in self.tap.listeners:
            self.tap.listeners.remove(self.session_recorder)
        for item in (self.session_recorder, self.session_hands, self.session_events, self.session):
            if item is not None:
                item.close()
        self.session = self.session_recorder = self.session_hands = self.session_events = None

    def close(self):
        """Shutdown work that must finish before main() kills the process."""
        if self.session is not None:
            self.end_session()  # A quit mid-session keeps its files.
        if self.player is not None:
            self.player.close()
        if self.tap_log is not None:
            print(self.tap_log.summary())
            self.tap_log.close()
        if self.tap is not None:
            # Close the strap BEFORE the hard kill in main(): Text mode, then disconnect.
            print("Closing Tap Strap... (Ctrl+C is ignored until this finishes)")
            if self.tap.stop():
                print("Tap Strap back in typing mode and disconnected.")
            elif not self.tap.connected:
                print("Tap Strap never connected; nothing to close.")
            elif not self.tap.demo:
                print("WARNING: Tap Strap did not close cleanly. Before reconnecting, "
                      "switch it off and on (or toggle Bluetooth) to clear the stale link.")


def run_server(use_https=False):
    # Phones only allow camera access over HTTPS. --https serves it directly
    # with a local self-signed certificate; otherwise put ngrok in front.
    ssl_context = None
    if use_https:
        cert, key = BASE_DIR / "cert.pem", BASE_DIR / "key.pem"
        if not (cert.exists() and key.exists()):
            print("cert.pem/key.pem not found; see 'Local HTTPS' in the README.")
            os._exit(1)
        ssl_context = (str(cert), str(key))
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context,
    )


def main():
    global camera_app
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--camera", type=int, metavar="N",
        help="read webcam N (e.g. iPhone via Camo over USB) instead of the phone page",
    )
    parser.add_argument(
        "--list-cameras", action="store_true", help="print working camera indices and exit",
    )
    parser.add_argument(
        "--https", action="store_true",
        help="serve the phone page over HTTPS with cert.pem/key.pem (no ngrok needed)",
    )
    parser.add_argument("--tap", action="store_true", help="also stream a Tap Strap into a 'Tap Strap' window")
    parser.add_argument("--tap-demo", action="store_true", help="like --tap, but with synthetic data (no strap)")
    parser.add_argument("--tap-address", metavar="ADDR", help="Tap Strap BLE address (default: first found)")
    parser.add_argument(
        "--tap-hand", choices=["left", "right"], default="right",
        help="hand wearing the strap; its fingers fill the Tap window's key column",
    )
    parser.add_argument("--program", type=int, default=0, metavar="N",
                        help="General MIDI instrument 0-127 for tapped keys (0 = piano, 40 = violin)")
    parser.add_argument("--base-note", type=int, default=60, metavar="N",
                        help="MIDI note for paper key 1 (60 = middle C)")
    parser.add_argument("--no-sound", action="store_true", help="log taps without playing notes")
    parser.add_argument("--session", action="store_true",
                        help="enable G: a guided accuracy session (needs --tap or --tap-demo and a calibration)")
    args = parser.parse_args()
    if args.list_cameras:
        list_cameras()
        return

    landmarker = make_landmarker()  # Before the strap starts, so a model error can't strand it.
    tap = player = strap_label = None
    if args.tap or args.tap_demo:
        # MediaPipe labels hands as if the image were mirrored; ours aren't, so swap.
        strap_label = {"left": "Right", "right": "Left"}[args.tap_hand]
        tap = TapMonitor(demo=args.tap_demo, address=args.tap_address)
        tap.start()
        if not args.no_sound:
            try:
                from sound import NotePlayer
                player = NotePlayer(program=args.program)
            except Exception as error:  # No MIDI output or missing package: keep running silently.
                print(f"Sound off: {error}")
    camera_app = CameraApp(landmarker, tap=tap, player=player, base_note=args.base_note,
                           session_enabled=args.session, strap_label=strap_label)

    if args.camera is None:
        threading.Thread(target=run_server, args=(args.https,), daemon=True).start()
        source = "phone camera frames"
        print(f"On the phone open: https://<ngrok or local address>/?token={FRAME_TOKEN}")
    else:
        threading.Thread(target=camera_loop, args=(args.camera, camera_app.submit_frame), daemon=True).start()
        source = f"camera {args.camera}"
    threading.Thread(target=camera_app.process_loop, daemon=True).start()

    guided = ", G = guided session" if args.session else ""
    tap_keys = ", T = tap calibration" if tap is not None else ""
    print(f"Waiting for {source}. C = calibrate, S = save frame, V = record frames{tap_keys}{guided}, Q = quit.")

    cv2.namedWindow(SETTINGS_WINDOW)
    # Trackbars have no tooltips, so the window shows a short guide instead.
    cv2.imshow(SETTINGS_WINDOW, settings_help_image())
    cv2.createTrackbar("Sens", SETTINGS_WINDOW, 50, 100, lambda v: None)
    cv2.createTrackbar("Key", SETTINGS_WINDOW, 15, 31, lambda v: None)

    exit_code = 0
    try:
        while True:
            positions = camera_app.slider_positions()
            if positions is not None:
                cv2.setTrackbarPos("Sens", SETTINGS_WINDOW, positions[0])
                cv2.setTrackbarPos("Key", SETTINGS_WINDOW, positions[1])
            camera_app.set_sliders(cv2.getTrackbarPos("Sens", SETTINGS_WINDOW),
                                   cv2.getTrackbarPos("Key", SETTINGS_WINDOW), time.monotonic())
            for name, image in camera_app.tick(time.time()).items():
                cv2.imshow(name, image)
            if not camera_app.handle_key(cv2.waitKey(1) & 0xFF, time.time()):
                break
    except KeyboardInterrupt:
        pass
    except Exception:
        # Print now: the hard kill below would swallow Python's own traceback.
        traceback.print_exc()
        exit_code = 1
    finally:
        # From here on, Ctrl+C must not interrupt the strap close (a second press
        # would kill it mid-close). Q needs nothing: the key loop has already ended.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # Don't call landmarker.close(): it can block forever while the
        # worker thread is mid-detection, which froze the terminal on Ctrl+C.
        # Exiting the process frees the model, camera and windows anyway.
        try:
            camera_app.close()
            cv2.destroyAllWindows()
        except Exception:
            # Still reach the hard kill: a normal exit can hang on Camo's driver.
            traceback.print_exc()
            exit_code = 1
        sys.stdout.flush()
        sys.stderr.flush()
        if os.name == "nt":
            # os._exit still runs DLL cleanup, which can deadlock with Camo's
            # DirectShow driver and leave the terminal stuck. Kill outright.
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
            k32.TerminateProcess(k32.GetCurrentProcess(), exit_code)
        os._exit(exit_code)


if __name__ == "__main__":
    main()
