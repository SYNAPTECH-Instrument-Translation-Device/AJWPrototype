"""Guided accuracy session: on-screen cues, a beep to tap on, and everything recorded.

Files, all on the host time.time() clock:
    PREFIX_fingers.csv / PREFIX_imu.csv   raw strap (recording.Recorder)
    PREFIX_hand.csv    host_time_s, then per finger (thumb..pinky): tip_x, tip_y, tip_z, dip_x, dip_y, key
    PREFIX_cues.csv    host_time_s, kind, fingers, keys   kind: tap | chord | idle_start | idle_end
    PREFIX_events.csv  the app's detected taps (tap_view.TapLog format)
"""
import csv
import random
import threading

from calibration import FINGERTIPS
from tapstrap import FINGERS

CHORDS = [("index", "middle"), ("index", "ring"), ("thumb", "index"),
          ("middle", "ring"), ("index", "middle", "ring")]
LEAD_S = 1.5    # The cue text shows this long before the beep.
PERIOD_S = 3.0  # Beep to beep.
IDLE_S = 20.0   # Final block: move the hand around without tapping (false-tap rate).


def build_cues(n_keys, singles=40, chords=10, seed=None):
    """Return [(kind, fingers, keys)]: singles spread evenly over fingers, then chords, then idle."""
    rng = random.Random(seed)
    cues = [("tap", (FINGERS[i % 5],), (rng.randint(1, n_keys),)) for i in range(singles)]
    rng.shuffle(cues)
    cues += [("chord", rng.choice(CHORDS), ()) for _ in range(chords)]
    cues.append(("idle", (), ()))
    return cues


def cue_text(kind, fingers, keys):
    if kind == "tap":
        return f"{fingers[0].upper()} on key {keys[0]}"
    if kind == "chord":
        return " + ".join(f.upper() for f in fingers) + " together"
    return "Move your hand over the paper, DON'T tap"


class HandLog:
    """Strap-hand landmarks per processed frame. Written from the processing thread."""

    def __init__(self, path):
        self.lock = threading.Lock()
        self.file = open(path, "w", newline="")
        self.writer = csv.writer(self.file)
        cols = ["host_time_s"]
        for f in FINGERS:
            cols += [f"{f}_{c}" for c in ("tip_x", "tip_y", "tip_z", "dip_x", "dip_y", "key")]
        self.writer.writerow(cols)

    def add(self, host_time, hand, fingers):
        """hand: 21 landmarks (x, y, z attributes) or None; fingers: {"index": key or None, ...}."""
        if hand is None:
            return
        row = [f"{host_time:.4f}"]
        for f in FINGERS:
            tip, dip = hand[FINGERTIPS[f]], hand[FINGERTIPS[f] - 1]
            row += [f"{tip.x:.4f}", f"{tip.y:.4f}", f"{tip.z:.4f}", f"{dip.x:.4f}", f"{dip.y:.4f}",
                    fingers.get(f) or 0]
        with self.lock:
            if not self.file.closed:
                self.writer.writerow(row)

    def close(self):
        with self.lock:
            self.file.close()


class GuidedSession:
    """Drive with update(now) from the display loop; it logs each cue at its beep."""

    def __init__(self, cues, cues_path, start, beep=None):
        self.cues, self.start, self.beep = cues, start, beep
        self.file = open(cues_path, "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["host_time_s", "kind", "fingers", "keys"])
        self.next = 0  # Index of the next cue to beep.
        self.idle_end = None

    def beep_time(self, i):
        return self.start + LEAD_S + i * PERIOD_S

    def update(self, now):
        """Return the text to show, or None once the session is over."""
        if self.idle_end is not None:
            if now >= self.idle_end:
                self._log(self.idle_end, "idle_end", (), ())
                self.idle_end = None
                self.next = len(self.cues)
                self.file.close()
                return None
            return f"{cue_text('idle', (), ())}  ({self.idle_end - now:.0f} s)"
        if self.next >= len(self.cues):
            return None
        kind, fingers, keys = self.cues[self.next]
        t = self.beep_time(self.next)
        if now >= t:
            if kind == "idle":
                self._log(t, "idle_start", (), ())
                self.idle_end = t + IDLE_S
            else:
                self._log(t, kind, fingers, keys)
                if self.beep:
                    self.beep()
            self.next += 1
            return self.update(now)
        return f"[{self.next + 1}/{len(self.cues)}] {cue_text(kind, fingers, keys)}  in {t - now:.1f} s"

    def _log(self, t, kind, fingers, keys):
        self.writer.writerow([f"{t:.4f}", kind, "+".join(fingers), "+".join(map(str, keys))])
        self.file.flush()

    @property
    def done(self):
        return self.next >= len(self.cues) and self.idle_end is None

    def close(self):
        if not self.file.closed:
            self.file.close()
