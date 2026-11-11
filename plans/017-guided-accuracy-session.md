# Plan 017: Guided accuracy session (record cued taps and chords, then score them)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat c5161ca..HEAD -- phone_server.py tap_view.py stream_raw.py m0_record.py`
> If it prints anything, compare the "Current state" excerpts below with the
> live code. On any mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (new modules; small hooks in the app; no change to tap detection)
- **Depends on**: none
- **Category**: direction (accuracy measurement); Phase 0 of `plans/design-press-accuracy.md`
- **Planned at**: commit `c5161ca`, 2026-11-10

## Why this matters

The pipeline plays a note when the Tap Strap detects a tap and the camera sees that finger
over a paper key. The user wants accuracy "as high as possible", for one user (themselves),
and wants chords (several fingers at once) to work eventually. Today there are no
numbers. Nothing tells us whether errors come from missed taps, wrong fingers
(crosstalk), wrong keys, or false taps. Every later improvement (per-user thresholds,
chord-aware crosstalk, timing alignment, ML) is judged against this session's numbers.
The recordings are also the labelled training data for any later ML model.

The session runs inside the camera app. Press **G**. On-screen cues ("INDEX on key 5",
"INDEX + MIDDLE together") count down to a beep, and the user taps on the beep. Everything
is recorded under one file prefix. `session_analyze.py PREFIX` then prints and saves a report.

## Current state

**`tap_view.py`**: `TapMonitor` streams the strap in a background thread. Each sample
reaches `on_sample` (`tap_view.py:97`):
```python
    def on_sample(self, sample, host_time=None):
        host_time = host_time if host_time is not None else time.time()
        with self.lock:
            if isinstance(sample, FingerAccelSample):
                ...
            else:
                self.gyro = sample.gyro_dps
```
`TapLog(path)` (`tap_view.py:28`) writes `host_time_s,finger,key,peak_g` rows: `add(host_time, finger, key, peak)`, `summary()`, `close()`.

**`stream_raw.py`**: `Recorder(prefix)` is a callable `(sample, host_time)` that writes
`PREFIX_fingers.csv` and `PREFIX_imu.csv`, and has `close()`. Reuse it as is.

**`m0_record.py`**: `click()` plays a short beep in a thread (winsound; falls back to `\a`). Reuse it with `from m0_record import click`.

**`phone_server.py`**:
- `hand_fingers(result, cal, strap_label=None)` (line 211) returns `(fingers, touched)`.
  `fingers` maps the capitalised names in `FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}` (calibration.py:11) to a key number or None:
  ```python
  def hand_fingers(result, cal, strap_label=None):
      chosen, touched = {}, set()
      for i, hand in enumerate(result.hand_landmarks):
          fingers = {name: region_at(cal, hand[k].x, hand[k].y) for name, k in FINGERTIPS.items()}
          touched |= {r for r in fingers.values() if r}
          label = result.handedness[i][0].category_name if i < len(result.handedness) else None
          if (strap_label is None and i == 0) or (strap_label is not None and label == strap_label):
              chosen = fingers
      return chosen, touched
  ```
- `process_frame(frame)` ends with (around line 287):
  ```python
      fingers = {}
      if cal is not None:
          fingers, touched = hand_fingers(result, cal, strap_label)
          annotated = draw_calibration(annotated, cal, touched)
      ...
      with frame_lock:
          latest_frame = annotated
          latest_fingers = fingers
  ```
- `process_pending()` (line 300) runs `process_frame(frame)` in the processing thread. `arrived = pending_time` is the `time.perf_counter()` value at the frame's arrival.
- In `__main__`: the `tap`, `tap_log` and `player` setup is around line 407. The display loop does `fingers = dict(latest_fingers)`, then `cv2.imshow("Phone Camera Feed", frame)`, then the tap block:
  ```python
              if tap is not None:
                  cv2.imshow("Tap Strap", tap.render(fingers))
                  for host_time, finger, peak in tap.pop_events():
                      # Strap names are lowercase; camera names are capitalised.
                      key = fingers.get(finger.capitalize())
                      tap_log.add(host_time, finger, key, peak)
                      if player is not None and key:
                          player.play(key_note(key, args.base_note), tap_velocity(peak))
                  if player is not None:
                      player.update()
  ```
  Keys are handled by `key = cv2.waitKey(1) & 0xFF` / `elif key == ord("c"):` etc. The `finally:` block closes `player`, prints and closes `tap_log`, calls `tap.stop()`, then kills the process (Windows `TerminateProcess`). **Anything not closed before that is lost.**
- `calibration["regions"]` is the list of keys; keys are numbered `1..len(calibration["regions"])`.

**Conventions:**
- Small single-purpose modules at the repo root.
- stdlib `unittest`; test files start with `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` (copy the header of `tests/test_tap_view.py`).
- Short `# why` comments.
- Plain imperative commit messages, no prefix (for example `Detect strap taps as events`).

## Commands you will need

`<python>` is `.venv/Scripts/python.exe`. If the worktree has none, use `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`. Install nothing.

| Purpose | Command | Expected |
|---|---|---|
| New tests | `<python> -m unittest tests.test_session -v` | all `ok` |
| All tests | `<python> -m unittest discover -s tests -t .` | `OK (skipped=1, expected failures=1)` and no failures (count rises from 58) |
| Flags | `<python> phone_server.py --help` | lists `--session` |

## Scope

**In scope:**
- create `session.py`, `session_analyze.py` and `tests/test_session.py`;
- `tap_view.py`: add the `listeners` hook only;
- `phone_server.py`: `pick_hand`, `latest_hand`, the hand log in `process_pending`, the `--session` flag, the G key, the cue overlay and the `finally:` ordering;
- `README.md`: one short subsection.

**Out of scope:**
- tap detection logic (`TAP_G`, the refractory period, the event rule);
- `calibration.py`, `sound.py`, `m0_record.py`, `m0_analyze.py`.

## Git workflow

Commits:
1. `Add a guided accuracy session recorder`
2. `Score guided sessions`
3. `Record guided sessions from the camera app`

Do not push.

## Steps

### Step 1: `TapMonitor.listeners` hook (tap_view.py)
- In `__init__`, add `self.listeners = []  # Extra (sample, host_time) callbacks, e.g. a session recorder.`
- At the end of `on_sample`, **after** the `with self.lock:` block (not inside it), add:
  ```python
          for listener in self.listeners:
              listener(sample, host_time)
  ```

**Verify:** `tests.test_tap_view` still passes.

### Step 2: `session.py`

```python
"""Guided accuracy session: on-screen cues, a beep to tap on, and everything recorded.

Files, all on the host time.time() clock:
    PREFIX_fingers.csv / PREFIX_imu.csv   raw strap (stream_raw.Recorder)
    PREFIX_hand.csv    host_time_s, then per finger (thumb..pinky): tip_x, tip_y, tip_z, dip_x, dip_y, key
    PREFIX_cues.csv    host_time_s, kind, fingers, keys   kind: tap | chord | idle_start | idle_end
    PREFIX_events.csv  the app's detected taps (tap_view.TapLog format)
"""
import csv
import random
import threading

from tapstrap import FINGERS

CHORDS = [("index", "middle"), ("index", "ring"), ("thumb", "index"),
          ("middle", "ring"), ("index", "middle", "ring")]
TIPS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}  # MediaPipe landmark ids
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
        """hand: 21 landmarks (x, y, z attributes) or None; fingers: {"Index": key or None, ...}."""
        if hand is None:
            return
        row = [f"{host_time:.4f}"]
        for f in FINGERS:
            tip, dip = hand[TIPS[f]], hand[TIPS[f] - 1]
            row += [f"{tip.x:.4f}", f"{tip.y:.4f}", f"{tip.z:.4f}", f"{dip.x:.4f}", f"{dip.y:.4f}",
                    fingers.get(f.capitalize()) or 0]
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
```

Note: cue times are the **scheduled** beep times, not when `update` noticed them. The
display loop runs about 30 times a second, so this removes up to about 33 ms of jitter
from the labels.

### Step 3: Tests for `session.py` (`tests/test_session.py`)
1. `build_cues(12, singles=40, chords=10, seed=1)`:
   - has 51 items;
   - the last one is `("idle", (), ())`;
   - each finger appears in exactly 8 singles;
   - every single's key is within 1..12;
   - every chord's fingers are one of `CHORDS`.
2. Same seed gives the same list; different seeds give different lists.
3. `GuidedSession` with a temp `cues_path`, `start=100.0`, and cues `[("tap", ("index",), (3,)), ("chord", ("index", "middle"), ()), ("idle", (), ())]`, with a beep counter:
   - `update(100.0)` returns text containing `"INDEX on key 3"`, and no beep yet;
   - `update(101.6)` beeps once;
   - `update(104.6)` beeps again (chord);
   - `update(107.6)` returns text containing `"DON'T tap"`;
   - `update(107.6 + 20.1)` returns None, and `done` is True.
   - The cues CSV rows (after the header), in order, have kinds `tap, chord, idle_start, idle_end`. The first time is `101.5000`. The fingers column is `index`, then `index+middle`. The keys column is `3`, then empty.
4. `HandLog`:
   - fake landmarks: `[types.SimpleNamespace(x=i/100, y=i/100, z=0.0) for i in range(21)]`, and `fingers={"Index": 4}`;
   - `add(1.0, hand, fingers)` then `add(2.0, None, {})`, then `close()`;
   - the CSV has the header plus 1 row; `index_tip_x == "0.0800"`, `index_key == "4"`, `thumb_key == "0"`.

**Verify:** `<python> -m unittest tests.test_session -v`: all ok. Commit 1.

### Step 4: `session_analyze.py`

```python
#!/usr/bin/env python3
"""Score a guided session: python session_analyze.py PREFIX  (writes PREFIX_report.txt)."""
```
Implement `analyze(prefix) -> list[str]` (report lines) plus a `main()` that prints the lines and writes them to `PREFIX_report.txt`. Use only the stdlib `csv` module and `numpy` (already a dependency).

Inputs:
- `PREFIX_cues.csv`
- `PREFIX_events.csv` (`host_time_s,finger,key,peak_g`; key 0 means no key)
- `PREFIX_hand.csv` (optional: skip the lag section if it's missing or has no rows)

Definitions:
- `WINDOW = (-0.25, 0.5)`: an event belongs to a cue if `cue_t + WINDOW[0] <= event_t <= cue_t + WINDOW[1]`. The user aims at the beep, so taps can land slightly early.
- Each event belongs to at most one cue: the nearest cue whose window contains it.
- For **tap** cues (target finger F, target key K):
  - *detected*: some window event has finger F;
  - *right key*: the first window event of finger F has key == K;
  - *extra fingers*: the number of window events whose finger isn't F (crosstalk).
- For **chord** cues (finger set S):
  - *complete*: every finger in S has a window event;
  - *exact*: complete, and no window event from a finger outside S;
  - also report the per-finger hit rate inside chords.
- *false taps*: events inside `[idle_start, idle_end]`, reported as a count and as a count per minute. Events outside every window and outside idle are reported separately as "unmatched".

Report lines, one metric per line, with counts and percentages:
- tap detection rate, overall and per finger;
- right-key rate among detected taps, overall and per finger;
- tap cues with at least one extra finger, and the mean number of extra fingers;
- chord complete rate and exact rate;
- false taps per minute while idle;
- unmatched events.

**Lag sweep** (skip if there's no hand data):
- for each detected tap cue, take the event time `te`;
- for each lag `L` in `0, 10, …, 200` ms, find the latest `PREFIX_hand.csv` row with `host_time_s <= te - L/1000`, and read that row's `<finger>_key`;
- `acc(L)` = the fraction where that key == K;
- report `acc` at 0 ms, the best `L` with its `acc`, and the app's own right-key rate (from the events) for comparison.

This shows how much plan "look up the key at the tap's time" would gain.

Add tests to `tests/test_session.py`, writing small CSVs into a temp dir with `csv.writer`:
- 2 tap cues (index key 3 at t=10, ring key 5 at t=13);
- 1 chord cue (index+middle at t=16);
- idle 20–30 s;
- events:
  - `10.1 index 3`;
  - `10.11 middle 3` (an extra finger);
  - none for the ring cue;
  - `16.05 index 2` and `16.06 middle 3`;
  - `25.0 pinky 0` (false tap);
  - `40.0 thumb 1` (unmatched).

Assert that `analyze` returns lines that include:
- tap detection `1/2`;
- right key `1/1`;
- `1` tap cue with an extra finger;
- chord complete `1/1` and exact `1/1`;
- false taps `1` (6.0/min);
- unmatched `1`.

Match on stable substrings you define, for example `"tap detected: 1/2"`; put those exact formats in the code.

Add one lag-sweep test with a `PREFIX_hand.csv`. The index key is 2 for rows at `t < 10.05` and 3 from `t >= 10.05`; the event is at `10.1`, and the cue key is 3. Expect `acc` at 0 ms = 100% and at 100 ms = 0%. Use the header from `HandLog` (build it with `HandLog` itself and a fake hand).

**Verify:** the session tests pass. Commit 2.

### Step 5: Wire into `phone_server.py`
1. **`pick_hand`**. Add above `hand_fingers`:
   ```python
   def pick_hand(result, strap_label=None):
       """Index of the strap hand in result.hand_landmarks, or None (same rule as hand_fingers)."""
       for i in range(len(result.hand_landmarks)):
           label = result.handedness[i][0].category_name if i < len(result.handedness) else None
           if (strap_label is None and i == 0) or (strap_label is not None and label == strap_label):
               return i
       return None
   ```
   Do NOT change `hand_fingers` (its tests pin its behaviour). Keep its rule identical.
2. **Globals**. Add `latest_hand = None  # Strap-hand landmarks of the newest frame (for session logs).` next to `latest_fingers`, and `session_hands = None  # session.HandLog while a guided session runs.`
3. **`process_frame`**. Add `latest_hand` to the `global` line. Before the final `with frame_lock:`, compute:
   ```python
       i = pick_hand(result, strap_label) if cal is not None else None
       hand = result.hand_landmarks[i] if i is not None else None
   ```
   and inside that final lock add `latest_hand = hand`.
4. **`process_pending`**. After `process_frame(frame)`:
   ```python
       if session_hands is not None:
           with frame_lock:
               hand, fingers = latest_hand, dict(latest_fingers)
           # Arrival time on the wall clock, the same clock the strap and cue files use.
           session_hands.add(time.time() - (time.perf_counter() - arrived), hand, fingers)
   ```
5. **Flag**, after `--no-sound`:
   ```python
       parser.add_argument("--session", action="store_true",
                           help="enable G: a guided accuracy session (needs --tap or --tap-demo and a calibration)")
   ```
   Add the module-level global `session_hands` to the existing `global`/assignment pattern. `__main__` code is module level, so plain assignment works there.
6. **State in `__main__`**. Next to `player = None`, add `session = None` and `session_recorder = None`. Update the startup print to mention `G = guided session` when `args.session`.
7. **G key** (new `elif` in the key handling):
   ```python
               elif key == ord("g") and args.session and tap is not None and session is None:
                   with frame_lock:
                       n_keys = len(calibration["regions"]) if calibration is not None else 0
                   if n_keys == 0:
                       with frame_lock:
                           status_text = "Calibrate (C) before a guided session."
                   else:
                       from m0_record import click
                       from session import GuidedSession, HandLog, build_cues
                       from stream_raw import Recorder
                       prefix = BASE_DIR / "recordings" / f"session_{time.strftime('%Y%m%d_%H%M%S')}"
                       prefix.parent.mkdir(exist_ok=True)
                       session_recorder = Recorder(str(prefix))
                       tap.listeners.append(session_recorder)
                       session_hands = HandLog(f"{prefix}_hand.csv")
                       session_events = TapLog(f"{prefix}_events.csv")
                       session = GuidedSession(build_cues(n_keys), f"{prefix}_cues.csv", time.time() + 3, beep=click)
                       print(f"Guided session: {prefix}")
   ```
   Also initialise `session_events = None` with the other state.
8. **Display loop.** Inside `if tap is not None:`, right after `tap_log.add(...)` in the events loop, add `if session_events is not None: session_events.add(host_time, finger, key, peak)`.

   Before `cv2.imshow("Phone Camera Feed", frame)`, add:
   ```python
               if session is not None:
                   text = session.update(time.time())
                   if text is None:
                       print(f"Session done. Score it: python session_analyze.py {prefix}")
                       session = end_session()
                   else:
                       cv2.putText(frame, text, (5, frame.shape[0] // 2),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
   ```
   Write a small local helper `end_session()` defined in `__main__` before the loop. It must:
   - remove `session_recorder` from `tap.listeners`;
   - close the recorder, `session_hands`, `session_events` and `session`;
   - set the globals to None;
   - return None.

   Because it reassigns module-level names, put `global session_hands` handling at module level (the `__main__` block is module scope, so a nested function needs `global session_hands, session_recorder, session_events, session`). Keep it simple and correct.
9. **`finally:`**. Before `if player is not None:`, add `if session is not None: end_session()` so a quit mid-session keeps its files. Since `tap.listeners` is called from the strap thread, removing the recorder before closing it means no late write hits a closed file. Do the removal first, inside `end_session()`.

**Verify:**
- the full suite passes;
- `--help` lists `--session`;
- a manual smoke test, if a webcam is available (optional, report whether you ran it):
  - run `<python> phone_server.py --camera 0 --tap-demo --session`;
  - calibrate any paper with C, then press G;
  - cues appear, beeps sound, and after the session `recordings/session_*_{fingers,imu,hand,cues,events}.csv` exist;
  - `session_analyze.py` on that prefix prints a report.

  Without a camera, skip the smoke test and say so.

### Step 6: README
Under `### Camera + Tap Strap together`, append:
```markdown
**Measuring accuracy.** Run with `--session`, calibrate (C), then press G. Follow the on-screen cues and tap on each beep: 40 single taps on named keys, 10 chords, then 20 s of moving your hand without tapping. Then run `python session_analyze.py recordings/session_<time>` for detection, right-key, crosstalk, chord and false-tap rates. Add the headline numbers to METRICS.md.
```
Commit 3.

## Test plan
Pure-logic tests for cue building, session timing, hand logging and scoring (Steps 3–4). The app wiring is covered by the full suite (imports) and `--help`. The real check is the user's first session with the strap.

## Done criteria
- [ ] `<python> -m unittest tests.test_session -v`: all ok (at least 6 tests)
- [ ] Full suite `OK (skipped=1, expected failures=1)`
- [ ] `--help` lists `--session`
- [ ] `grep -n "listeners" tap_view.py`: 2 lines (init and loop)
- [ ] `hand_fingers` is unchanged: `git diff c5161ca -- phone_server.py | grep -c "^-.*def hand_fingers"` prints 0
- [ ] The diff touches only `session.py`, `session_analyze.py`, `tests/test_session.py`, `tap_view.py`, `phone_server.py`, `README.md`, `plans/README.md`

## STOP conditions
- The excerpts don't match the live code.
- Wiring seems to need a change to tap detection or to `hand_fingers`.
- `end_session` can't be written without restructuring `__main__` into a function. Report it; don't restructure.

## Maintenance notes
- Cue times are the scheduled beep times. If the beep itself lags (winsound runs in a thread), the cue/tap offset in the report shows it. A constant offset is fine; scoring uses a window.
- Chord cues name only fingers, not keys, so chord key accuracy isn't scored yet. Add keys once the camera can say where each finger of a chord landed.
- `PREFIX_hand.csv` (tip and DIP per finger) is the training data for the later "contact point" and offset-model work, and the lag sweep tells plan "key at tap time" what lag to use.
