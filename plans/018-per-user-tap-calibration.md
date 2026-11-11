# Plan 018: Per-user tap calibration (finger thresholds and crosstalk, key T)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: plan 017 must have landed: `grep -n "self.listeners" tap_view.py`
> prints 2 lines, and `grep -n "def pick_hand" phone_server.py` prints 1. If not, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (changes the tap threshold the app uses, but only after the user runs the calibration)
- **Depends on**: 017 (the `TapMonitor.listeners` hook, and 017's `__main__` edits, to avoid conflicts)
- **Category**: direction (accuracy); Phase 1 of `plans/design-press-accuracy.md`
- **Planned at**: commit `c5161ca` + plan 017, 2026-11-10

## Why this matters

Tap detection uses one guessed threshold for every finger: `TAP_G = 0.5` g of deviation from
resting gravity (`tap_view.py:21`). Fingers differ: the thumb and pinky move less, and the
strap fit changes the readings. The tool has one user, so we can measure *their* fingers.
A 30-second step (rest, then 5 cued taps per finger) gives:
- a per-finger noise floor and a per-finger threshold placed between noise and the weakest real tap;
- a **crosstalk matrix**: when finger A taps, what fraction of A's peak shows up on finger B.

Chords are a stated goal. A later plan will use the crosstalk matrix to tell "B really tapped
too" (chord) apart from "B just shook because A tapped" (crosstalk). This plan only
measures and stores the matrix; it does not change how events are attributed.

## Current state

`tap_view.py` (after plan 017):
```python
TAP_G = 0.5          # Bars turn red above this, so taps stand out.
...
class TapMonitor:
    def __init__(self, demo=False, address=None):
        ...
        self.above = {f: False for f in FINGERS}   # Was the last sample over TAP_G?
        self.last_tap = {f: -1e9 for f in FINGERS}
        self.events = collections.deque(maxlen=64)  # (host_time_s, finger, peak_g)
        self.listeners = []  # Extra (sample, host_time) callbacks, e.g. a session recorder.

    def on_sample(self, sample, host_time=None):
        host_time = host_time if host_time is not None else time.time()
        with self.lock:
            if isinstance(sample, FingerAccelSample):
                self.count += 1
                self.last_sample = time.monotonic()
                for f, m in zip(FINGERS, sample.magnitudes()):
                    dev = abs(m - 1.0)
                    self.activity[f] = max(self.activity[f], dev)
                    if dev > TAP_G and not self.above[f] and host_time - self.last_tap[f] >= REFRACTORY_S:
                        self.events.append((host_time, f, dev))
                        self.last_tap[f] = host_time
                    self.above[f] = dev > TAP_G
            ...
        for listener in self.listeners:
            listener(sample, host_time)
```
In `render()`: `color = (0, 0, 255) if a > TAP_G else (0, 200, 0)`.

`FINGERS = ("thumb", "index", "middle", "ring", "pinky")` (tapstrap/decode.py).
`FingerAccelSample.magnitudes()` returns |a| per finger in g, in `FINGERS` order.
`m0_record.click()` beeps. `CALIBRATION_DIR = BASE_DIR / "calibration"` in phone_server.py.
`phone_server.py` `__main__`:
- `tap = TapMonitor(...)` and `tap.start()` inside `if args.tap or args.tap_demo:`;
- keys are handled with `elif key == ord(...)`;
- the camera frame text overlay is drawn just before `cv2.imshow("Phone Camera Feed", frame)` (plan 017 added the session overlay there).

**Conventions**: as in plan 017 (small root modules, stdlib unittest with the `sys.path` header, short why-comments, plain imperative commits).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| New tests | `<python> -m unittest tests.test_tap_profile -v` | all ok |
| All tests | `<python> -m unittest discover -s tests -t .` | `OK (skipped=1, expected failures=1)` |

`<python>` is `.venv/Scripts/python.exe`, or `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe` if the worktree has none. Install nothing.

## Scope
**In scope:**
- create `tap_profile.py` and `tests/test_tap_profile.py`;
- `tap_view.py`: per-finger thresholds, `set_profile`;
- `phone_server.py`: load the profile at start, the T key, the overlay;
- `README.md`: one paragraph.

**Out of scope:**
- event attribution or crosstalk suppression (a later plan);
- `REFRACTORY_S`;
- `session.py` and `session_analyze.py`;
- `calibration.py`.

## Git workflow
Commits:
1. `Fit per-finger tap thresholds from a calibration`
2. `Use per-finger tap thresholds`
3. `Add tap calibration to the camera app`

Do not push.

## Steps

### Step 1: `tap_profile.py` (pure logic, no I/O except save/load)

```python
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
```

Notes for the executor:
- `update` beeps on `tap` cues only.
- Cue times are scheduled times (the same idea as plan 017).
- The `__call__` runs in the strap thread and only appends to lists, so no lock is needed. `fit()` runs after `update()` returned None; by then any late append is harmless.

### Step 2: Tests (`tests/test_tap_profile.py`)
Build synthetic data at 200 Hz from `schedule(100.0)`. `devs` holds noise `rng.normal(0, 0.02)` (absolute value) on every finger. Inside each tap window, add a spike at `cue + 0.15` s:
- the cued finger peaks at 1.0 g, except the pinky at 0.6 g;
- the next finger in `FINGERS` peaks at 0.3 × that (crosstalk).

Tests:
1. `schedule(0)` has 2 + 25 entries; the first tap is at `REST_S + 2.0`; the taps go thumb ×5, index ×5, and so on.
2. `fit_profile` on the synthetic data:
   - every threshold is between that finger's noise + 0.05 and its weakest tap;
   - the pinky threshold is lower than the index threshold;
   - `crosstalk["index"]["middle"]` is about 0.3 (`assertAlmostEqual(..., 0.3, delta=0.05)`);
   - `crosstalk["index"]["ring"]` is below 0.1;
   - `warnings` is empty.
3. Where the ring taps are removed (ring stays at noise level), `warnings` mentions `ring`.
4. `save_profile` then `load_profile` round-trips (temp dir). `load_profile` on a missing file, or on a JSON missing a finger, returns None.
5. `TapCalibration`:
   - feed `types.SimpleNamespace(magnitudes=lambda: (1.0, 1.5, 1.0, 1.0, 1.0))` → `devs[-1][1] == 0.5`;
   - a sample object without `magnitudes` (an IMU sample) is ignored;
   - driving `update` at a time after the last cue + 0.6 returns None, with 25 beeps counted.

**Verify:** the new tests pass. Commit 1.

### Step 3: Per-finger thresholds in `TapMonitor`
- In `__init__`, add `self.thresholds = {f: TAP_G for f in FINGERS}  # Replaced by a fitted tap profile.`
- In `on_sample`, use `thr = self.thresholds[f]` in place of both uses of `TAP_G`.
- In `render`, the bar turns red when `a > self.thresholds[f]` (read the thresholds under the lock along with `activity`).
- Add:
  ```python
      def set_profile(self, profile):
          with self.lock:
              self.thresholds = {f: float(profile["thresholds"][f]) for f in FINGERS}
  ```
- Add a test in `tests/test_tap_view.py`: `set_profile({"thresholds": {... index: 0.2, others 0.5}})`, then an index sample at dev 0.3 → 1 event (with the default it would be 0).

**Verify:** `tests.test_tap_view` passes (all old tests still pass unchanged). Commit 2.

### Step 4: Wire into `phone_server.py`
1. Constant: `TAP_PROFILE = CALIBRATION_DIR / "tap_profile.json"`.
2. After `tap.start()`:
   ```python
           from tap_profile import load_profile
           profile = load_profile(TAP_PROFILE)
           if profile is not None:
               tap.set_profile(profile)
               print(f"Tap profile loaded ({profile['created']}).")
   ```
3. State: `tap_cal = None` next to `session = None`.
4. T key:
   ```python
               elif key == ord("t") and tap is not None and tap_cal is None and session is None:
                   from m0_record import click
                   from tap_profile import TapCalibration
                   tap_cal = TapCalibration(time.time() + 3, beep=click)
                   tap.listeners.append(tap_cal)
   ```
5. Before `cv2.imshow("Phone Camera Feed", frame)` (next to the session overlay):
   ```python
               if tap_cal is not None:
                   text = tap_cal.update(time.time())
                   if text is None:
                       tap.listeners.remove(tap_cal)
                       try:
                           profile = tap_cal.fit()
                           CALIBRATION_DIR.mkdir(exist_ok=True)
                           save_profile(profile, TAP_PROFILE)
                           tap.set_profile(profile)
                           msg = "Tap calibrated: " + "  ".join(
                               f"{f[0]}:{profile['thresholds'][f]:.2f}" for f in profile["thresholds"])
                           for w in profile["warnings"]:
                               print("Tap calibration warning:", w)
                       except ValueError as error:
                           msg = f"Tap calibration failed: {error} Press T to retry."
                       print(msg)
                       with frame_lock:
                           status_text = msg
                       tap_cal = None
                   else:
                       cv2.putText(frame, text, (5, frame.shape[0] // 2),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
   ```
   Import `save_profile` together with `load_profile`.
6. Update the startup print to mention `T = tap calibration` when a strap is on.

**Verify:**
- the full suite passes;
- `<python> -c "import phone_server"` is not required (it loads MediaPipe), but `--help` must still work.

Optional smoke test (report whether you ran it):
- run `--camera 0 --tap-demo`, press T and wait about 40 s;
- `calibration/tap_profile.json` is written and the status shows thresholds.

  With `DemoStream`, every finger spikes to about 2.5 g in turn regardless of cues, so the numbers are meaningless. Only check that it completes.

### Step 5: README
Under `### Camera + Tap Strap together`, append:
```markdown
**Tap calibration (T).** With the strap on, press T. Rest your hand still on the paper for 3 s, then tap each finger 5 times on the beeps. The app saves per-finger tap thresholds and finger crosstalk to `calibration/tap_profile.json` and loads it on every start. Redo it if you re-seat the strap. Run a guided session (G) before and after to see the difference.
```
Then add a **controls manual** to the README: a new `## Controls` section placed directly after `## Running`. Its content (keep the tables; adjust wording only if a key or flag differs in the live code — check `phone_server.py` before writing):

```markdown
## Controls

### Keys (click the Phone Camera Feed window first)

| Key | What it does | When it works |
|---|---|---|
| `C` | Calibrate the paper keyboard. Keep your hands out of view for about a second. | Always |
| `S` | Save the current camera frame to `samples/` (for debugging calibration). | Always |
| `T` | Tap calibration: rest your hand 3 s, then tap each finger 5 times on the beeps. Saves `calibration/tap_profile.json`. | With `--tap` or `--tap-demo` |
| `G` | Guided accuracy session: tap the named finger/key on each beep. Saves `recordings/session_<time>_*.csv`. | With `--session` and a strap, after `C` |
| `Q` | Quit. Puts the strap back into normal typing mode. `Ctrl+C` in the terminal also works. | Always |

### Windows

| Window | What it shows |
|---|---|
| Phone Camera Feed | Camera image, detected paper keys (numbered), hand landmarks, status lines. Keys under a fingertip turn yellow. |
| Calibration settings | **Sens** slider: raise if key lines are missed, lower if shadows become keys. **Key** slider: lower for small drawings. |
| Tap Strap | One bar per finger (red = tap-sized spike), the key the camera sees each finger on, thumb gyro. Only with `--tap`/`--tap-demo`. |

### Command-line options (`python phone_server.py ...`)

| Option | What it does |
|---|---|
| `--camera N` | Use local camera N (e.g. the iPhone through Camo) instead of the phone web page. |
| `--list-cameras` | Print working camera numbers and exit. |
| `--https` | Serve the phone page over HTTPS with `cert.pem`/`key.pem` (no ngrok). |
| `--tap` | Connect the Tap Strap (paired in Windows Bluetooth, Developer mode on). |
| `--tap-demo` | Fake strap data, no hardware. |
| `--tap-address ADDR` | Connect to a specific strap. |
| `--tap-hand left\|right` | Which hand wears the strap (default `right`). |
| `--program N` | MIDI instrument: 0 piano, 24 guitar, 40 violin, 73 flute. |
| `--base-note N` | MIDI note of key 1 (default 60 = middle C). |
| `--no-sound` | Log taps without playing notes. |
| `--session` | Enable `G` (guided accuracy session). |

Typical run: `python phone_server.py --camera 1 --tap`, press `C`, then `T` once per strap fit, then play.
```

Commit 3.

## Test plan
Synthetic-signal tests for fitting (Step 2), and a threshold-behaviour test for `TapMonitor` (Step 3). The real check is a guided session (plan 017) before and after calibrating on the real strap. Record both in METRICS.md.

## Done criteria
- [ ] `<python> -m unittest tests.test_tap_profile -v`: all ok
- [ ] Full suite OK
- [ ] `grep -n "TAP_G" tap_view.py` shows only the constant definition and the `thresholds` default (no direct comparisons)
- [ ] `--help` still works
- [ ] The diff touches only `tap_profile.py`, `tests/test_tap_profile.py`, `tap_view.py`, `tests/test_tap_view.py`, `phone_server.py`, `README.md`, `plans/README.md`

## STOP conditions
- The drift check fails (plan 017 isn't in).
- A test needs a real strap or audio device.
- Per-finger thresholds seem to need a change to the event rule beyond swapping `TAP_G` for `self.thresholds[f]`.

## Maintenance notes
- The next plan (chord-aware crosstalk) reads `profile["crosstalk"]`. When several fingers fire within about 25 ms, a finger B event is dropped as crosstalk if `peak_B < k * crosstalk[A][B] * peak_A` for the strongest finger A (k ≈ 2, tuned with guided sessions). That keeps real chords and removes shake. Don't use winner-take-all, because it would kill chords.
- The rest phase measures a *still* hand. Moving-hand false taps are measured by plan 017's idle block. If false taps remain high, consider fitting the noise floor from that block too.
- Thresholds are per strap fit. A profile older than the last re-seat may be wrong; the README tells the user to redo it.
