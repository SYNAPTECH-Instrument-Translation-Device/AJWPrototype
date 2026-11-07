"""Tap Strap live view as an OpenCV image, for showing next to the camera feed.

    tap = TapMonitor(demo=True)
    tap.start()
    cv2.imshow("Tap Strap", tap.render({"index": 3}))   # finger -> camera region
    tap.stop()
"""
import asyncio
import threading
import time

import cv2
import numpy as np

from tapstrap import FINGERS, DemoStream, FingerAccelSample, SensorConfig, TapRawStream

FULL_SCALE_G = 2.0   # |accel - 1 g| that fills a bar.
TAP_G = 0.5          # Bars turn red above this, so taps stand out.
HALF_LIFE_S = 0.1    # Peak-hold decay of the bars.
STALE_S = 1.0        # No finger data for this long means the strap went quiet.
WIDTH, HEIGHT = 480, 300


class TapMonitor:
    def __init__(self, demo=False, address=None):
        self.demo, self.address = demo, address
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.status = "Tap: connecting..."
        self.activity = {f: 0.0 for f in FINGERS}
        self.gyro = (0.0, 0.0, 0.0)
        self.count, self.rate = 0, 0.0
        self.last_sample = None  # Monotonic time of the newest finger sample.
        self.last_rate_time = self.last_render = time.monotonic()

    def start(self):
        self.thread = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True)
        self.thread.start()

    def stop(self, timeout=2.0):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout)

    async def _run(self):
        stream = (DemoStream if self.demo else TapRawStream)(SensorConfig(), address=self.address)
        stream.on_sample(self.on_sample)
        try:
            async with stream:
                with self.lock:
                    self.status = "Tap: demo data" if self.demo else "Tap: connected"
                while not self.stop_event.is_set():
                    await asyncio.sleep(0.1)
        except Exception as error:
            with self.lock:
                self.status = f"Tap: not connected - {error}"[:70]

    def on_sample(self, sample, _host_time=None):
        with self.lock:
            if isinstance(sample, FingerAccelSample):
                self.count += 1
                self.last_sample = time.monotonic()
                for f, m in zip(FINGERS, sample.magnitudes()):
                    self.activity[f] = max(self.activity[f], abs(m - 1.0))
            else:
                self.gyro = sample.gyro_dps

    def display_status(self, now):
        # Call with self.lock held (or single-threaded). Never overwrites self.status.
        if self.last_sample is not None and now - self.last_sample > STALE_S:
            return "Tap: no data - strap asleep or out of range?"
        return self.status

    def render(self,finger_regions=None):
        # Camera names are capitalised (calibration.FINGERTIPS); strap names are not.
        finger_regions = {k.lower(): v for k, v in (finger_regions or {}).items()}
        img = np.full((HEIGHT, WIDTH, 3), 30, np.uint8)
        font, white = cv2.FONT_HERSHEY_SIMPLEX, (230, 230, 230)
        now = time.monotonic()
        with self.lock:
            if now - self.last_rate_time >= 1.0:
                self.rate = self.count / (now - self.last_rate_time)
                self.count, self.last_rate_time = 0, now
            activity = dict(self.activity)
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
            color = (0, 0, 255) if a > TAP_G else (0, 200, 0)
            if fill:
                cv2.rectangle(img, (bar_x, y), (bar_x + fill, y + 20), color, -1)
            region = finger_regions.get(f)
            cv2.putText(img, f"key {region}" if region else "-", (WIDTH - 85, y + 15), font, 0.5, white, 1)
        gx, gy, gz = gyro
        cv2.putText(img, f"thumb gyro (deg/s)  x {gx:6.0f}  y {gy:6.0f}  z {gz:6.0f}",
                    (10, HEIGHT - 15), font, 0.45, white, 1)
        return img
