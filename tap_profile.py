"""Per-user tap profile: per-finger thresholds and crosstalk, fitted from a short calibration.

Calibration = REST_S of a still hand, then TAPS_PER_FINGER cued taps per finger.
"""
import json
import time

import numpy as np

from tapstrap import FINGERS

REST_S = 3.0
TAPS_PER_FINGER = 5
TAP_PERIOD_S = 1.2
WINDOW = (-0.2, 0.6)     # Seconds around a cue in which the tap's peak is searched.
MIN_MARGIN_G = 0.05      # A threshold is at least this far above the noise floor.
NOISE_PCT = 99.5


def schedule(start):
    """[(time, kind, finger)]: rest_start, rest_end, then a 'tap' cue per tap, finger by finger."""
    s = [(start, "rest_start", ""), (start + REST_S, "rest_end", "")]
    t = start + REST_S + 2.0  # Time to read the first finger's instruction.
    for f in FINGERS:
        for _ in range(TAPS_PER_FINGER):
            s.append((t, "tap", f))
            t += TAP_PERIOD_S
        t += 1.0
    return s


def window_peaks(times, devs, t0, t1):
    """Max deviation per finger over samples with t0 <= time <= t1; devs is (N, 5)."""
    m = (times >= t0) & (times <= t1)
    return devs[m].max(axis=0) if m.any() else np.zeros(len(FINGERS))


def fit_profile(times, devs, sched):
    """times (N,), devs (N, 5) = |accel| - 1 g per finger; sched from schedule().

    Returns {"thresholds", "noise", "crosstalk", "weakest_tap", "warnings", "created"}.
    """
    times, devs = np.asarray(times, float), np.asarray(devs, float)
    rest0 = next(t for t, k, _ in sched if k == "rest_start")
    rest1 = next(t for t, k, _ in sched if k == "rest_end")
    rest = devs[(times >= rest0) & (times <= rest1)]
    if len(rest) == 0:
        raise ValueError("No strap data during the rest phase.")
    noise = np.percentile(rest, NOISE_PCT, axis=0)

    peaks = {f: [] for f in FINGERS}  # finger -> list of 5-vectors (peak on every finger)
    for t, kind, f in sched:
        if kind == "tap":
            peaks[f].append(window_peaks(times, devs, t + WINDOW[0], t + WINDOW[1]))

    thresholds, weakest, crosstalk, warnings = {}, {}, {}, []
    for i, f in enumerate(FINGERS):
        own = np.array([p[i] for p in peaks[f]]) if peaks[f] else np.zeros(1)
        weakest[f] = float(own.min())
        thr = max((noise[i] + weakest[f]) / 2, noise[i] + MIN_MARGIN_G)
        if weakest[f] <= noise[i] + MIN_MARGIN_G:
            warnings.append(f"{f}: weakest tap ({weakest[f]:.2f} g) is not above rest noise ({noise[i]:.2f} g)")
        thresholds[f] = float(thr)
        crosstalk[f] = {
            g: float(np.median([p[j] / max(p[i], 1e-6) for p in peaks[f]])) if peaks[f] else 0.0
            for j, g in enumerate(FINGERS) if g != f
        }
    return {"thresholds": thresholds, "noise": {f: float(noise[i]) for i, f in enumerate(FINGERS)},
            "weakest_tap": weakest, "crosstalk": crosstalk, "warnings": warnings,
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}


def save_profile(profile, path):
    with open(path, "w") as f:
        json.dump(profile, f, indent=2)


def load_profile(path):
    try:
        with open(path) as f:
            profile = json.load(f)
        return profile if set(profile.get("thresholds", {})) == set(FINGERS) else None
    except (OSError, ValueError):
        return None


class TapCalibration:
    """Collects samples (as a TapMonitor listener) and walks through schedule()."""

    def __init__(self, start, beep=None):
        self.sched, self.beep = schedule(start), beep
        self.times, self.devs = [], []
        self.next = 0

    def __call__(self, sample, host_time):
        if hasattr(sample, "magnitudes"):  # FingerAccelSample only
            self.times.append(host_time)
            self.devs.append([abs(m - 1.0) for m in sample.magnitudes()])

    def update(self, now):
        """Return the text to show, or None when every cue is past and the last window has closed."""
        while self.next < len(self.sched) and now >= self.sched[self.next][0]:
            if self.sched[self.next][1] == "tap" and self.beep:
                self.beep()
            self.next += 1
        if self.next >= len(self.sched):
            return None if now >= self.sched[-1][0] + WINDOW[1] else "Tap calibration: finishing..."
        t, kind, f = self.sched[self.next]
        if kind == "rest_start":
            return f"Tap calibration: rest your hand on the paper, still (starts in {t - now:.1f} s)"
        if kind == "rest_end":
            return f"Keep still... {t - now:.1f} s"
        return f"Tap with {f.upper()} on each beep (next in {t - now:.1f} s)"

    def fit(self):
        return fit_profile(self.times, self.devs, self.sched)
