"""Shared recording helpers: raw strap CSVs and the cue click."""
import csv
import threading

from tapstrap import FINGERS, FingerAccelSample


def click():
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(1000, 30), daemon=True).start()
    except ImportError:
        print("\a", end="", flush=True)


class Recorder:
    def __init__(self, prefix):
        # Line-buffered: the camera app exits by killing the process; don't lose rows.
        self.ff = open(f"{prefix}_fingers.csv", "w", newline="", buffering=1)
        self.fi = open(f"{prefix}_imu.csv", "w", newline="", buffering=1)
        self.wf, self.wi = csv.writer(self.ff), csv.writer(self.fi)
        self.wf.writerow(["host_time_s", "device_ms"] + [f"{f}_{ax}_g" for f in FINGERS for ax in "xyz"])
        self.wi.writerow(["host_time_s", "device_ms", "gyro_x_dps", "gyro_y_dps", "gyro_z_dps",
                          "accel_x_g", "accel_y_g", "accel_z_g"])

    def __call__(self, s, host_time):
        if self.ff.closed:
            return  # A late sample after close() is dropped, not an error.
        if isinstance(s, FingerAccelSample):
            self.wf.writerow([f"{host_time:.4f}", s.device_ms] +
                             [f"{v:.4f}" for f in FINGERS for v in getattr(s, f)])
        else:
            self.wi.writerow([f"{host_time:.4f}", s.device_ms] +
                             [f"{v:.3f}" for v in (*s.gyro_dps, *s.accel_g)])

    def close(self):
        self.ff.close()
        self.fi.close()
