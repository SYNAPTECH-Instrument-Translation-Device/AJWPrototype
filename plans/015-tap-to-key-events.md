# Plan 015: Turn strap taps into "finger tapped key N" events and log them to CSV

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: confirm plans 013 and 014 have landed:
> `grep -n "k.lower()" tap_view.py` and `grep -n "def hand_fingers" phone_server.py` must each print one line.
> If either prints nothing, STOP. Then compare the excerpts below with the live code.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: 013, 014
- **Category**: direction (core pipeline)
- **Planned at**: commit `c6e260f`, 2026-11-06 (excerpts assume 013 and 014 applied)

## Why this matters

The project is a virtual piano on paper. A phone camera looks down at a paper
keyboard, `calibration.py` numbers the keys 1..N left to right (chromatic
order on a piano drawing), and MediaPipe tells us which key each fingertip is
over. A Tap Strap 2 on the same hand measures each finger's acceleration at
200 Hz. Today the two only meet visually in the "Tap Strap" window.

This plan joins them: whenever a finger's acceleration spikes (a tap), we look up
which key the camera sees that finger on, and emit an event `(time, finger, key,
peak)`. Events go to a CSV under `recordings/`, and the app prints a summary on
quit (taps, and how many landed on a key). Plan 016 turns these events into sound.
The CSV is also the data for the METRICS.md items "Tap ↔ key agreement" and
"Tap Strap tap detection".

## Current state

`tap_view.py` (after plan 013):
- Constants: `FULL_SCALE_G = 2.0`, `TAP_G = 0.5` ("Bars turn red above this"), `HALF_LIFE_S = 0.1`, `STALE_S = 1.0`.
- `class TapMonitor(demo=False, address=None)`. A background thread runs the
  strap stream, and `on_sample(self, sample, _host_time=None)` is called per sample under
  `self.lock`. For `FingerAccelSample` it does:
  ```python
                self.count += 1
                self.last_sample = time.monotonic()
                for f, m in zip(FINGERS, sample.magnitudes()):
                    self.activity[f] = max(self.activity[f], abs(m - 1.0))
  ```
  `FINGERS = ("thumb", "index", "middle", "ring", "pinky")`, lowercase. `m` is
  |accel| in g, about 1.0 at rest. The stream calls callbacks as
  `cb(sample, host_time)`, where `host_time = time.time()`.

`phone_server.py` (after plan 014):
- `latest_fingers` holds the strap hand's fingers as `{"Thumb": region, "Index": ..., ...}`
  (capitalised names from `calibration.FINGERTIPS`; region 0 or None = not on a key).
- In `__main__`, `tap = TapMonitor(...)` when `--tap`/`--tap-demo` is given, else `tap = None`.
- The display loop copies `fingers = dict(latest_fingers)` and shows windows:
  ```python
            cv2.imshow("Phone Camera Feed", frame)
            if tap is not None:
                cv2.imshow("Tap Strap", tap.render(fingers))
  ```
- The `finally:` block calls `tap.stop()` and then kills the process (`os._exit` /
  Windows `TerminateProcess`). Anything that must be flushed has to happen before that.
- `recordings/` is git-ignored and already used by `m0_record.py` (file names like `recordings/m0_<time>_fingers.csv`).

Conventions: stdlib only (`csv`, `collections`), short `# why` comments, `unittest`
tests in `tests/test_tap_view.py` that call `on_sample` directly with
`FingerAccelSample(device_ms, thumb, index, middle, ring, pinky)` (each a 3-tuple in g;
rest is `(0.0, 0.0, -1.0)`). Plain imperative commit messages.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tap tests | `<python> -m unittest tests.test_tap_view -v` | all `ok` |
| All tests | `<python> -m unittest discover -s tests -t .` | `OK (skipped=1, expected failures=1)` |

`<python>` is `.venv/Scripts/python.exe`, or `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`
if the worktree has no `.venv`. Don't install anything.

## Scope

**In scope**: `tap_view.py`, `tests/test_tap_view.py`, `phone_server.py` (only the
display loop and the `finally:` block), `README.md` (the "Camera + Tap Strap together" section).
**Out of scope**: `tapstrap/`, `calibration.py`, `process_frame`, sound (plan 016),
and any change to `TAP_G`'s value.

## Git workflow

Commits: `Detect strap taps as events`, `Log tap-to-key events to CSV`. Do not push.

## Steps

### Step 1: Tap onset detection in `TapMonitor`
In `tap_view.py`:
- Add `import collections`.
- Add the constant `REFRACTORY_S = 0.15  # One tap per finger per this long (bounces and ringing).`
- In `__init__`, add:
  ```python
        self.above = {f: False for f in FINGERS}   # Was the last sample over TAP_G?
        self.last_tap = {f: -1e9 for f in FINGERS}
        self.events = collections.deque(maxlen=64)  # (host_time_s, finger, peak_g)
  ```
- In `on_sample`, use the host time (`host_time = _host_time if _host_time is not None else time.time()`;
  rename the parameter to `host_time=None`). In the per-finger loop, after updating `activity`:
  ```python
                    dev = abs(m - 1.0)
                    if dev > TAP_G and not self.above[f] and host_time - self.last_tap[f] >= REFRACTORY_S:
                        self.events.append((host_time, f, dev))
                        self.last_tap[f] = host_time
                    self.above[f] = dev > TAP_G
  ```
  (Compute `dev` once and reuse it for `activity`.)
- Add:
  ```python
    def pop_events(self):
        """Taps since the last call, oldest first: [(host_time_s, finger, peak_g)]."""
        with self.lock:
            events = list(self.events)
            self.events.clear()
        return events
  ```
  `peak_g` is the deviation at the crossing sample, not the true peak. That is good
  enough for loudness in v1. Say so in a `# shortcut:` comment.

Tests in `tests/test_tap_view.py` (helper: `sample(index_z)` returns a `FingerAccelSample`
with index at `(0, 0, index_z)` and the others at rest):
1. `test_one_event_per_tap`: feed rest, then `-2.5` (dev 1.5), then `-2.5`, then rest, with host times 0.0, 0.005, 0.010, 0.015 → `pop_events()` returns exactly one event `(0.005, "index", 1.5)` (use `assertAlmostEqual` on the floats), and a second `pop_events()` returns `[]`.
2. `test_refractory`: a tap at t=0.0, back to rest at 0.01, another tap at 0.05 → 1 event. Another at 0.30 → 2 events total.
3. `test_rest_noise_no_event`: 100 samples with dev 0.2 → no events.

**Verify**: tap tests all `ok`.

### Step 2: `TapLog`, a CSV writer with a summary
Add to `tap_view.py`:
```python
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
```
(Add `import csv` and `from pathlib import Path`.)

Test `test_tap_log` with `tempfile.TemporaryDirectory()`: add `(1.0, "index", 3, 1.2)` and
`(2.0, "ring", None, 0.8)`. Close, read back with `csv.reader`, and check the header plus 2 rows
(`key` column `"3"` and `"0"`). `summary()` → `"Taps: 2, on a key: 1 (50%)"`.

**Verify**: tap tests all `ok`.

### Step 3: Wire it into `phone_server.py`
- Import: `from tap_view import TapLog, TapMonitor`.
- Where `tap` is created (inside `if args.tap or args.tap_demo:`), also create
  `tap_log = TapLog(BASE_DIR / "recordings" / f"taps_{time.strftime('%Y%m%d_%H%M%S')}.csv")`.
  Set `tap_log = None` next to `tap = None`.
- In the display loop, right after `cv2.imshow("Tap Strap", tap.render(fingers))` (inside the same `if`):
  ```python
                for host_time, finger, peak in tap.pop_events():
                    # Strap names are lowercase; camera names are capitalised.
                    key = fingers.get(finger.capitalize())
                    tap_log.add(host_time, finger, key, peak)
  ```
- In `finally:`, before `tap.stop()`:
  ```python
        if tap_log is not None:
            print(tap_log.summary())
            tap_log.close()
  ```

**Verify**: full suite passes. Then a 6-second headless smoke test (no window needed):
```
<python> -c "import time; from tap_view import TapMonitor; t=TapMonitor(demo=True); t.start(); time.sleep(3); e=t.pop_events(); t.stop(); print(len(e), sorted({f for _,f,_ in e}))"
```
→ about 15 events (demo: each finger taps about once per second), and all 5 finger names listed.

### Step 4: README
Append to `### Camera + Tap Strap together`:
```markdown
Each strap tap is logged to `recordings/taps_<time>.csv` (time, finger, the key the camera saw that finger on, peak g). On quit the app prints how many taps landed on a key.
```

## Test plan

Five new tests in `tests/test_tap_view.py`: one event per tap, refractory, no
events from noise, TapLog CSV, and summary. The headless demo smoke test in Step 3
checks the threaded path.

## Done criteria

- [ ] Tap tests all `ok` (5 new)
- [ ] Full suite `OK (skipped=1, expected failures=1)`
- [ ] Smoke command prints a count between 10 and 20 and all 5 fingers
- [ ] `grep -n "pop_events" phone_server.py` → one line
- [ ] Diff touches only `tap_view.py`, `tests/test_tap_view.py`, `phone_server.py`, `README.md`

## STOP conditions

- 013/014 not landed (see drift check).
- The demo smoke test gives fewer than 10 events or a missing finger. Report the counts; don't change `TAP_G`.
- Wiring seems to need changes inside `process_frame`.

## Maintenance notes

- `TAP_G = 0.5 g` and `REFRACTORY_S = 0.15 s` are guesses. Tune them from real
  `recordings/m0_*` sessions (`m0_analyze.py` reports per-finger thresholds).
- The key comes from the newest processed camera frame, which is about 15–40 ms old.
  If keys are wrong at fast play, compare the CSV with camera `age` (METRICS "Camera freshness").
- Plan 016 plays a note for each event that has a key.
