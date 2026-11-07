# Plan 013: Tap window shows the camera's keys, says when strap data stops, and shuts the strap down cleanly

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat c6e260f..HEAD -- tap_view.py tests/test_tap_view.py`
> If it prints anything, compare with "Current state". On any mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `c6e260f`, 2026-11-06

## Why this matters

`tap_view.py` draws the "Tap Strap" OpenCV window that `phone_server.py --tap`
(real strap) or `--tap-demo` (synthetic data) shows next to the camera feed. It
has three bugs:

1. **The "camera" column is always `-`.** `phone_server.py` passes
   `render(fingers)` a dict keyed by `calibration.FINGERTIPS` names, which are
   capitalised (`"Thumb"`, `"Index"`, `"Middle"`, `"Ring"`, `"Pinky"`).
   `render` looks them up with the strap's lowercase names from
   `tapstrap.FINGERS` (`"thumb"`, `"index"`, ...), so it never matches. The
   existing test passes lowercase keys, so it doesn't catch this.
2. **The status says "connected" forever.** It's set once after connecting. A
   strap that falls asleep or drops Bluetooth looks the same as one at rest.
3. **Unclean exit.** If connecting fails partway (after the Bluetooth link is up
   but before raw mode is set), `async with` never calls `stream.stop()`, so the
   link is left open. On quit, `stop()` waits only 2 s for the strap to be put back
   in typing mode. After that, `phone_server.py` kills the process outright (Windows
   `TerminateProcess`), and a slow Bluetooth write leaves the strap stuck in raw
   mode, where it doesn't type.

## Current state

`tapstrap.FINGERS = ("thumb", "index", "middle", "ring", "pinky")` (`tapstrap/decode.py`).
`calibration.FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}` (`calibration.py:11`).

`tap_view.py` (relevant parts):
```python
FULL_SCALE_G = 2.0   # |accel - 1 g| that fills a bar.
TAP_G = 0.5          # Bars turn red above this, so taps stand out.
HALF_LIFE_S = 0.1    # Peak-hold decay of the bars.
WIDTH, HEIGHT = 480, 300


class TapMonitor:
    def __init__(self, demo=False, address=None):
        ...
        self.status = "Tap: connecting..."
        ...
        self.last_rate_time = self.last_render = time.monotonic()

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
                ...

    def render(self, finger_regions=None):
        finger_regions = finger_regions or {}
        ...
        with self.lock:
            ...
            status, rate, gyro = self.status, self.rate, self.gyro
        ...
            region = finger_regions.get(f)
```

`TapRawStream.stop()` (`tapstrap/stream.py:80-97`) is safe to call when not fully
started: it returns at once if `self._sdk is None`, and it catches its own errors.
`DemoStream.stop()` cancels `self._task`, which exists only after `start()`.

`tests/test_tap_view.py` has 2 tests (`test_spike_raises_only_that_finger`,
`test_render_size_and_decay`). They build `TapMonitor(demo=True)` and call
`on_sample` / `render` directly, with no thread. Match that style: stdlib
`unittest`, no mocks unless needed.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tap tests | `<python> -m unittest tests.test_tap_view -v` | all `ok` |
| All tests | `<python> -m unittest discover -s tests -t .` | `OK (skipped=1, expected failures=1)` |

`<python>` is `.venv/Scripts/python.exe`, or `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`
if the worktree has no `.venv`. Don't install anything. Baseline: 38 tests at `c6e260f`.
Other plans may add tests before yours, so compare against the count before your change.

## Scope

**In scope**: `tap_view.py`, `tests/test_tap_view.py`.
**Out of scope**: `phone_server.py` (it keeps calling `tap.render(fingers)` and
`tap.stop()` unchanged), `tapstrap/`, `calibration.py` (don't rename FINGERTIPS).

## Git workflow

One commit per step, plain imperative messages, for example `Match camera finger names in the Tap window`. Do not push.

## Steps

### Step 1: Accept capitalised finger names in `render`
At the top of `render`, normalise the keys once:
```python
        # Camera names are capitalised (calibration.FINGERTIPS); strap names are not.
        finger_regions = {k.lower(): v for k, v in (finger_regions or {}).items()}
```
(This replaces `finger_regions = finger_regions or {}`.) Leave the `.get(f)` lookup as it is.

In `tests/test_tap_view.py`, add `test_render_accepts_camera_finger_names`. Render
once with `{"Index": 3}` and once with `{}` on two fresh monitors. Assert the two
images differ (`not np.array_equal(...)`), because the first draws `key 3`. Import
`numpy as np`.

**Verify**: the new test fails if you temporarily remove the normalising line, and passes with it.

### Step 2: Show when data stops
- In `__init__`, add `self.last_sample = None` (monotonic time of the newest finger sample).
- In `on_sample`, inside the `FingerAccelSample` branch, set `self.last_sample = time.monotonic()`.
- Add a module constant `STALE_S = 1.0  # No finger data for this long means the strap went quiet.`
- In `render`, inside the existing `with self.lock:` block, compute the status shown:
```python
            status = self.status
            if self.last_sample is not None and now - self.last_sample > STALE_S:
                status = "Tap: no data - strap asleep or out of range?"
```
  and keep the `rate, gyro` assignment. Only the *displayed* status changes. Never overwrite `self.status`.

Test `test_status_goes_stale`: on a monitor, call `on_sample` with one finger
sample, set `tap.last_sample -= 2`, and check that `render()` returns the right
size. Factor the status choice into a small method,
`display_status(self, now)`, that returns the string. `render` calls it under the
lock. The test asserts that `tap.display_status(time.monotonic())` starts with
`"Tap: no data"`, and that a fresh sample makes it go back to `tap.status`.

**Verify**: tap tests all `ok`.

### Step 3: Always stop the stream; give the restore time
Rewrite `_run` so `stop()` runs even if `start()` fails partway:
```python
    async def _run(self):
        stream = (DemoStream if self.demo else TapRawStream)(SensorConfig(), address=self.address)
        stream.on_sample(self.on_sample)
        try:
            await stream.start()
            with self.lock:
                self.status = "Tap: demo data" if self.demo else "Tap: connected"
            while not self.stop_event.is_set():
                await asyncio.sleep(0.1)
        except Exception as error:
            with self.lock:
                self.status = f"Tap: not connected - {error}"[:70]
        finally:
            try:
                # Also after a half-finished connect, so the link isn't left open.
                await stream.stop()
            except Exception:
                pass  # DemoStream.stop fails if start never ran; nothing to clean up.
```
Change `stop(self, timeout=2.0)` to `stop(self, timeout=5.0)` and add one comment line
above the join: `# Restoring typing mode is a Bluetooth write; the caller kills the process right after.`

Test `test_demo_thread_starts_and_stops`: `t = TapMonitor(demo=True); t.start()`.
Poll for up to 2 s until `t.last_sample is not None`. Then `t.stop()` and assert
`not t.thread.is_alive()`.

**Verify**: tap tests all `ok`; the full suite passes, with 3 more tests than before your change.

## Test plan

Three new tests in `tests/test_tap_view.py`: camera finger names, stale status, and
the demo thread start/stop. Pattern: the existing tests in the same file.

## Done criteria

- [ ] `<python> -m unittest tests.test_tap_view -v` → 5 tests, all `ok`
- [ ] Full suite `OK (skipped=1, expected failures=1)`, 3 more tests than before
- [ ] `grep -n "k.lower()" tap_view.py` → one line
- [ ] `grep -n "finally:" tap_view.py` → one line
- [ ] `git diff --stat c6e260f -- . ':!plans'` (or against your branch base) shows only `tap_view.py` and `tests/test_tap_view.py`

## STOP conditions

- `phone_server.py` would need a change.
- The demo thread test is flaky (fails 1 run in 3). Report it; don't add sleeps beyond 2 s.

## Maintenance notes

- Plan 014 passes the strap hand's fingers into `render`, and plan 015 reads taps
  from this class. Both rely on `render` accepting `FINGERTIPS`-style names.
- If a real strap's restore takes longer than 5 s, raise the timeout, not the number of retries.
