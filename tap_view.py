"""Tap Strap live view as an OpenCV image, for showing next to the camera feed.

    tap = TapMonitor(demo=True)
    tap.start()
    cv2.imshow("Tap Strap", tap.render({"index": 3}))   # finger -> camera region
    tap.stop()
"""
import asyncio
import collections
import csv
import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from tapstrap import FINGERS, DemoStream, FingerAccelSample, SensorConfig, TapRawStream

FULL_SCALE_G = 2.0   # |accel - 1 g| that fills a bar.
TAP_G = 0.5          # Bars turn red above this, so taps stand out.
HALF_LIFE_S = 0.1    # Peak-hold decay of the bars.
STALE_S = 1.0        # No finger data for this long means the strap went quiet.
REFRACTORY_S = 0.15  # One tap per finger per this long (bounces and ringing).
# A tap event waits up to this many samples (30 ms at 200 Hz) after the threshold
# crossing, or until the finger drops back under threshold, to report the true peak
# for loudness. Bounded so a musical note isn't noticeably late.
PEAK_SAMPLES = 6
WIDTH, HEIGHT = 480, 300

log = logging.getLogger(__name__)


class Listeners(list):
    """Sample callbacks run on the strap thread. append/remove wait for a dispatch
    in progress, so once remove() returns that listener is never called again."""

    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()  # Reentrant: a listener may remove itself.

    def append(self, listener):
        with self.lock:
            super().append(listener)

    def remove(self, listener):
        with self.lock:
            super().remove(listener)

    def __call__(self, sample, host_time):
        with self.lock:
            for listener in list(self):
                try:
                    listener(sample, host_time)
                except Exception:
                    log.exception("tap listener failed")  # Don't starve the others.


class TapLog:
    """Appends tap-to-key events to a CSV and counts how many landed on a key."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["host_time_s", "finger", "key", "peak_g"])
        self.taps = self.on_key = 0

    def add(self, host_time, finger, key, peak):
        self.writer.writerow([f"{host_time:.4f}", finger, key or 0, f"{peak:.3f}"])
        self.file.flush()  # The app exits by killing the process; don't lose rows.
        self.taps += 1
        self.on_key += bool(key)

    def summary(self):
        pct = 100 * self.on_key / self.taps if self.taps else 0
        return f"Taps: {self.taps}, on a key: {self.on_key} ({pct:.0f}%)"

    def close(self):
        self.file.close()


class TapMonitor:
    def __init__(self, demo=False, address=None):
        self.demo, self.address = demo, address
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.closed_cleanly = False
        self.status = "Tap: connecting..."
        self.activity = {f: 0.0 for f in FINGERS}
        self.gyro = (0.0, 0.0, 0.0)
        self.count, self.rate = 0, 0.0
        self.last_sample = None  # Monotonic time of the newest finger sample.
        self.last_rate_time = self.last_render = time.monotonic()
        self.above = {f: False for f in FINGERS}   # Was the last sample over TAP_G?
        self.last_tap = {f: -1e9 for f in FINGERS}
        self.thresholds = {f: TAP_G for f in FINGERS}  # Replaced by a fitted tap profile.
        self.events = collections.deque(maxlen=64)  # (host_time_s, finger, peak_g)
        self.pending = {}  # finger -> [crossing host_time, peak so far, samples left]
        self.connected = False  # Did the strap (or demo) ever start streaming?
        self.listeners = Listeners()  # Extra (sample, host_time) callbacks, e.g. a session recorder.

    def start(self):
        self.thread = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True)
        self.thread.start()

    def stop(self, timeout=10.0):
        """Close the strap; True once it's back in Text mode and disconnected.

        False also after a failed connect whose cleanup couldn't confirm Text mode;
        check self.connected to tell "never connected" apart.

        Callers that kill the process afterwards must wait for this: killing
        mid-close leaves the strap in raw mode and Windows holding the link.
        """
        self.stop_event.set()
        if self.thread is None:
            return True
        self.thread.join(timeout)
        return not self.thread.is_alive() and self.closed_cleanly

    async def _run(self):
        stream = (DemoStream if self.demo else TapRawStream)(SensorConfig(), address=self.address)
        stream.on_sample(self.on_sample)
        try:
            await stream.start()
            self.connected = True
            with self.lock:
                self.status = "Tap: demo data" if self.demo else "Tap: connected"
            while not self.stop_event.is_set():
                await asyncio.sleep(0.1)
        except Exception as error:
            with self.lock:
                self.status = f"Tap: not connected - {error}"[:70]
        finally:
            try:
                # Also after a half-finished connect, so the link isn't left open;
                # stop() then reports how that earlier cleanup went.
                self.closed_cleanly = await stream.stop()
            except Exception:
                log.exception("Tap Strap close failed")

    def on_sample(self, sample, host_time=None):
        host_time = host_time if host_time is not None else time.time()
        with self.lock:
            if isinstance(sample, FingerAccelSample):
                self.count += 1
                self.last_sample = time.monotonic()
                for f, m in zip(FINGERS, sample.magnitudes()):
                    dev = abs(m - 1.0)
                    self.activity[f] = max(self.activity[f], dev)
                    thr = self.thresholds[f]
                    tap = self.pending.get(f)
                    if tap is not None:
                        tap[1], tap[2] = max(tap[1], dev), tap[2] - 1
                        if dev <= thr or tap[2] <= 0:  # Peak is past, or the wait is up.
                            self.events.append((tap[0], f, tap[1]))
                            del self.pending[f]
                    elif dev > thr and not self.above[f] and host_time - self.last_tap[f] >= REFRACTORY_S:
                        # shortcut: a tap still pending when the stream stops is never reported; add a flush if that matters.
                        self.pending[f] = [host_time, dev, PEAK_SAMPLES]
                        self.last_tap[f] = host_time
                    self.above[f] = dev > thr
            else:
                self.gyro = sample.gyro_dps
        self.listeners(sample, host_time)

    def set_profile(self, profile):
        with self.lock:
            self.thresholds = {f: float(profile["thresholds"][f]) for f in FINGERS}

    def pop_events(self):
        """Taps since the last call, oldest first: [(host_time_s, finger, peak_g)]."""
        with self.lock:
            events = list(self.events)
            self.events.clear()
        return events

    def display_status(self, now):
        # Call with self.lock held (or single-threaded). Never overwrites self.status.
        if self.last_sample is not None and now - self.last_sample > STALE_S:
            return "Tap: no data - strap asleep or out of range?"
        return self.status

    def render(self, finger_regions=None):
        finger_regions = finger_regions or {}
        img = np.full((HEIGHT, WIDTH, 3), 30, np.uint8)
        font, white = cv2.FONT_HERSHEY_SIMPLEX, (230, 230, 230)
        now = time.monotonic()
        with self.lock:
            if now - self.last_rate_time >= 1.0:
                self.rate = self.count / (now - self.last_rate_time)
                self.count, self.last_rate_time = 0, now
            activity = dict(self.activity)
            thresholds = dict(self.thresholds)
            decay = 0.5 ** ((now - self.last_render) / HALF_LIFE_S)
            self.last_render = now
            for f in FINGERS:
                self.activity[f] *= decay
            status, rate, gyro = self.display_status(now), self.rate, self.gyro

        cv2.putText(img, status, (10, 22), font, 0.5, (0, 255, 255), 1)
        cv2.putText(img, f"fingers {rate:.0f} Hz", (10, 44), font, 0.45, white, 1)
        cv2.putText(img, "camera", (WIDTH - 85, 44), font, 0.45, white, 1)
        bar_x, bar_w = 80, WIDTH - 190
        for i, f in enumerate(FINGERS):
            y = 70 + 38 * i
            a = activity[f]
            cv2.putText(img, f, (10, y + 15), font, 0.5, white, 1)
            cv2.rectangle(img, (bar_x, y), (bar_x + bar_w, y + 20), (70, 70, 70), 1)
            fill = int(bar_w * min(1.0, a / FULL_SCALE_G))
            color = (0, 0, 255) if a > thresholds[f] else (0, 200, 0)
            if fill:
                cv2.rectangle(img, (bar_x, y), (bar_x + fill, y + 20), color, -1)
            region = finger_regions.get(f)
            cv2.putText(img, f"key {region}" if region else "-", (WIDTH - 85, y + 15), font, 0.5, white, 1)
        gx, gy, gz = gyro
        cv2.putText(img, f"thumb gyro (deg/s)  x {gx:6.0f}  y {gy:6.0f}  z {gz:6.0f}",
                    (10, HEIGHT - 15), font, 0.45, white, 1)
        return img
