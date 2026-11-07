# Plan 009: Server tests use a temp calibration dir, rotating back reloads the saved calibration, README lists every file

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ce1af56..HEAD -- phone_server.py tests/test_server.py README.md`
> If it prints anything, compare the "Current state" excerpts below with the
> live code. On any mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests + bug + docs
- **Planned at**: commit `ce1af56`, 2026-11-03

## Why this matters

This plan makes three small, independent fixes. Do them in this order:

1. **Tests read the developer's real calibration.** `tests/test_server.py` runs `phone_server.process_frame`. That function loads `calibration/calibration.npz` from the repo, which is the developer's real, git-ignored calibration. Test results can therefore change depending on what is saved on that machine. The tests should use an empty temp folder.
2. **Rotating back doesn't reload the saved calibration.** The server tries to load the saved calibration only once per run. Say the frame size changes (phone rotated, or a different camera resolution) and then changes back. The calibration stays dropped until the user presses C again, even though a valid one is on disk.
3. **The README's "Project Structure" list is out of date.** It lists 7 files and leaves out `calibration.py`, `calibrate_image.py`, the `tapstrap/` package, the M0 tools, `tests/` and `plans/`. It also never explains the legacy `debug.py`.

## Current state

Files:
- `phone_server.py`: Flask server plus the processing thread. `process_frame()` (lines 194–270) does paper detection, hand tracking, loading the calibration and running a calibration capture.
- `tests/test_server.py`: unittest tests for the server (78 lines). They drive the pipeline with `phone_server.submit_frame(...)` / an HTTP POST, then `phone_server.process_pending()`.
- `tests/test_calibration.py`: calibration tests. Its helpers `make_sheet`, `solid` and `STRAIGHT` (lines 21–42) build a synthetic 640×480 photo of white paper with 4 black boxes on a dark desk.
- `README.md`: the "## Project Structure" section (around lines 71–79).

`phone_server.py:42-49` (module globals):
```python
CALIBRATION_DIR = BASE_DIR / "calibration"
SAMPLES_DIR = BASE_DIR / "samples"
CALIBRATION_FRAMES = 15

calibration = None
calibration_checked = False
calibrating = False
calibration_frames = []
```

`phone_server.py:194-198`:
```python
def process_frame(frame):
    global latest_frame, latest_mask, last_timestamp_ms
    global calibration, calibration_checked, calibrating, calibration_frames
    global latest_raw, latest_fingers, status_text
    global ink_ratio_setting, line_kernel_setting
```

`phone_server.py:216-250`. This is the bug: `calibration_checked` becomes True after the first frame and never resets.
```python
    with frame_lock:
        latest_raw = frame
        if not calibration_checked:
            calibration = load_calibration(CALIBRATION_DIR, frame.shape)
            calibration_checked = True
            if calibration is not None:
                ink_ratio_setting = calibration["settings"]["ink_ratio"]
                line_kernel_setting = calibration["settings"]["line_kernel"]
                status_text = (
                    f"Loaded calibration: {len(calibration['regions'])} regions."
                )
        if calibrating:
            ...
        frame_size = (frame.shape[1], frame.shape[0])
        if calibration is not None and calibration["frame_size"] != frame_size:
            calibration = None
            status_text = "Frame size changed (phone rotated?): press C to recalibrate."
        cal = calibration if not calibrating else None
```

`calibration.load_calibration(directory, frame_shape)` (`calibration.py:273`) already returns `None` when the folder has no saved files **or** when the saved frame size differs from `frame_shape`. It never raises for those cases. Only `process_frame` uses `calibration_checked` (checked with grep: lines 47, 196, 218, 220).

`tests/test_server.py:25-27`. There is no isolation today:
```python
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = phone_server.app.test_client()
```

**Conventions to match:**
- Stdlib `unittest` only. No pytest, no new dependencies.
- Short `# Comment.` lines that explain *why*, as in `phone_server.py:292-293`: `# One bad frame must not kill this thread: the window would freeze for good.`
- Temp folders use `tempfile.TemporaryDirectory()`, as in `tests/test_calibration.py:154-161` (`test_save_load_roundtrip`).
- Commit messages are plain imperative sentences with no prefix, for example `Keep the processing thread alive if one frame fails`.

## Commands you will need

Run from the repo root, using the project venv (`.venv\Scripts\python.exe` on Windows; `python` once the venv is activated).

| Purpose | Command | Expected on success |
|---|---|---|
| All tests | `python -m unittest discover -s tests -t .` | Last lines: `Ran N tests` and `OK (skipped=1, expected failures=1)` |
| Server tests only | `python -m unittest tests.test_server -v` | all `ok` |

The baseline at `ce1af56` is `Ran 35 tests … OK (skipped=1, expected failures=1)`. The test run prints M0 report text to stdout. That is normal. If you see a one-off `OpenBLAS error: Memory allocation still failed`, run again with `OPENBLAS_NUM_THREADS=1` set. It was seen once during planning and did not come back.

## Scope

**In scope** (the only files you may modify):
- `phone_server.py`: only the globals block (lines 42–49), the `global` line in `process_frame`, and the calibration-load block (lines 216–249).
- `tests/test_server.py`
- `README.md`: only the "## Project Structure" section.
- `plans/README.md`: only this plan's status row.

**Out of scope** (do NOT touch):
- `calibration.py`. `load_calibration` already does the size check this plan relies on.
- The `__main__` block of `phone_server.py` (lines 333+: sliders, key handling). It also reads `calibration`, but needs no change.
- The `calibration/` folder in the repo. Never write to it, delete it, or commit it (it is git-ignored on purpose).
- Deleting or changing `debug.py`. Only document it.
- Any other README section.

## Git workflow

- Branch: `advisor/009-test-isolation-calibration-reload`
- One commit per step. Suggested messages:
  - `Run server tests against a temp calibration folder`
  - `Reload the saved calibration when the frame size changes back`
  - `List every file in the README's project structure`
- Do not push. Do not open a PR.

## Steps

### Step 1: Isolate the server tests from the real calibration folder

In `tests/test_server.py`:

1. Add `import tempfile` and `from unittest import mock` with the other stdlib imports.
2. Replace `setUp` so that every test points `phone_server.CALIBRATION_DIR` at a fresh empty temp folder and starts with no calibration loaded:

```python
    def setUp(self):
        self.client = phone_server.app.test_client()
        # Never read or write the developer's real calibration/ folder.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cal_dir = Path(tmp.name)
        patcher = mock.patch.object(phone_server, "CALIBRATION_DIR", self.cal_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        phone_server.calibration = None
        phone_server.calibration_checked = False
```

(In Step 2, `calibration_checked` gets renamed. Update this line there.)

This works because `process_frame` reads the module-level `CALIBRATION_DIR` each time it runs, so patching the module attribute takes effect.

**Verify**: `python -m unittest tests.test_server -v` shows 9 tests, all `ok`. Then run the full suite: `Ran 35 tests` and `OK (skipped=1, expected failures=1)`.

### Step 2: Retry loading the saved calibration once per new frame size

In `phone_server.py`:

1. In the globals block, replace `calibration_checked = False` with:
   ```python
   checked_size = None        # Frame size the saved calibration was last tried for.
   ```
2. In `process_frame`'s `global` line, replace `calibration_checked` with `checked_size`.
3. Replace the load block. Compute `frame_size` once at the top of the locked section and reuse it in the size-mismatch check below. The target shape:

```python
    frame_size = (frame.shape[1], frame.shape[0])
    with frame_lock:
        latest_raw = frame
        # Try the saved calibration once per frame size, so rotating back reloads it.
        if calibration is None and checked_size != frame_size:
            checked_size = frame_size
            calibration = load_calibration(CALIBRATION_DIR, frame.shape)
            if calibration is not None:
                ink_ratio_setting = calibration["settings"]["ink_ratio"]
                line_kernel_setting = calibration["settings"]["line_kernel"]
                status_text = (
                    f"Loaded calibration: {len(calibration['regions'])} regions."
                )
        if calibrating:
            ...  # unchanged
        if calibration is not None and calibration["frame_size"] != frame_size:
            calibration = None
            status_text = "Frame size changed (phone rotated?): press C to recalibrate."
        cal = calibration if not calibrating else None
```

Delete the old `frame_size = (frame.shape[1], frame.shape[0])` line that sat just before the mismatch check, so it is defined only once. Leave everything inside `if calibrating:` exactly as it is.

How it behaves (for checking your work):
- First frame at 640×480 tries the file once.
- A switch to 480×640 drops the calibration. The next frame tries the file once for 480×640 and gets `None`, because the saved size differs.
- Switching back to 640×480 tries the file again and reloads it.
- With no saved file, it tries once per distinct size and nothing more, so it does not read the disk on every frame.

4. In `tests/test_server.py`'s `setUp`, change `phone_server.calibration_checked = False` to `phone_server.checked_size = None`.

**Verify**:
- `grep -rn "calibration_checked" --include=*.py .` prints nothing. Ignore matches under `.claude/`, which holds old agent worktrees. If your grep follows that folder, add `--exclude-dir=.claude`.
- `python -m unittest tests.test_server -v` → all `ok`.

### Step 3: Add regression tests for Steps 1 and 2

Add these tests to `ServerTests` in `tests/test_server.py`. Build the saved calibration with the existing calibration-test helpers. Import them at the top of the file, next to the existing imports:

```python
from calibration import build_calibration, save_calibration
from tests.test_calibration import STRAIGHT, make_sheet, solid
```

(`tests/` is a package with `__init__.py`, and the file already puts the repo root on `sys.path`, so this import works under `unittest discover -s tests -t .`.)

Tests to add:

1. `test_no_saved_calibration_in_temp_dir`: submit `make_image()` (320×240), call `process_pending()`, then assert `phone_server.calibration is None`. This shows the empty temp folder is the one being read.
2. `test_saved_calibration_loads`:
   - Build `img = make_sheet(solid, STRAIGHT)[0]` (640×480).
   - Run `save_calibration(build_calibration([img]), self.cal_dir)`.
   - Submit `img` and call `process_pending()`.
   - Assert `phone_server.calibration` is not None and `len(phone_server.calibration["regions"]) == 4`.
3. `test_rotating_back_reloads_calibration`: same saved calibration as test 2, then:
   - Submit `img` and process. Assert the calibration is loaded.
   - Submit `np.ascontiguousarray(np.rot90(img))` (480×640) and process. Assert `phone_server.calibration is None`.
   - Submit `img` again and process. Assert the calibration is loaded again, with 4 regions.

Model these on the existing `test_submit_frame_feeds_pipeline` (`tests/test_server.py:62-65`). Feed frames with `phone_server.submit_frame(...)`, then call `phone_server.process_pending()`.

**Verify**:
- `python -m unittest tests.test_server -v` → 12 tests, all `ok`.
- To confirm test 3 catches the bug: temporarily put the old `calibration_checked` logic back (`git stash` of the `phone_server.py` change only). Test 3 must then FAIL on its last assertion. Restore the change afterwards (`git stash pop`). If test 3 passes against the old code, STOP: it doesn't test the bug.
- Full suite → `Ran 38 tests`, `OK (skipped=1, expected failures=1)`.
- `git status --short calibration/` prints nothing (the real folder was not touched).

### Step 4: Update the README's Project Structure list

Replace the bullet list under `## Project Structure` in `README.md` with the list below. Keep the `- \`path\` — description.` style that is already there.

```markdown
- `phone_server.py` — Main app: phone-page server or `--camera` webcam input, hand tracking, calibration, key overlay and sliders.
- `phone_camera.html`, `phone_camera.css`, `phone_camera.js` — Phone camera page that sends frames to the server.
- `calibration.py` — Finds the paper, flattens it, detects and numbers the keys, and saves/loads `calibration/`.
- `calibrate_image.py` — Writes a `_debug.png` for one saved frame (see Calibration).
- `paper_detector.py` — White-paper mask used by calibration and the live overlay.
- `debug.py` — Old standalone viewer: paper-detection mask from webcam 0. Not used by the app.
- `tapstrap/` — Tap Strap 2 raw-sensor decoding (`decode.py`) and Bluetooth streaming (`stream.py`).
- `stream_raw.py`, `live_plot.py` — Live Tap Strap readout and plot (`--demo` works without a strap).
- `m0_record.py`, `m0_analyze.py` — Milestone 0 recording sessions and reports (see Tap Strap (M0)).
- `models/hand_landmarker.task` — MediaPipe hand-tracking model.
- `tests/` — Unit tests; `tests/fixtures/` holds real camera frames used as regression tests.
- `plans/` — Implementation plans and their status.
- `METRICS.md` — Measured and synthetic results over time.
- `requirements.txt` — Python dependencies.
```

Before writing it, check each description against the file (open it and read its top lines). If a description is wrong, fix the wording and keep it to one line.

**Verify**: for each path in the list, check that it exists. For example, in bash:
`for p in phone_server.py phone_camera.html phone_camera.css phone_camera.js calibration.py calibrate_image.py paper_detector.py debug.py tapstrap stream_raw.py live_plot.py m0_record.py m0_analyze.py models/hand_landmarker.task tests plans METRICS.md requirements.txt; do test -e "$p" || echo "MISSING $p"; done`
This prints nothing.

## Test plan

- Three new tests in `tests/test_server.py` (Step 3): empty temp folder, saved calibration loads, and rotating back reloads it.
- The existing 9 server tests now run against an isolated temp folder (Step 1).
- Pattern: `test_submit_frame_feeds_pipeline` (`tests/test_server.py:62-65`) for driving the pipeline, and `test_save_load_roundtrip` (`tests/test_calibration.py:154-161`) for using a temp folder.
- Final: `python -m unittest discover -s tests -t .` → `Ran 38 tests`, `OK (skipped=1, expected failures=1)`.

## Done criteria

ALL must hold:

- [ ] `python -m unittest discover -s tests -t .` ends with `Ran 38 tests` and `OK (skipped=1, expected failures=1)`
- [ ] `grep -n "calibration_checked" phone_server.py tests/test_server.py` prints nothing
- [ ] `grep -n "CALIBRATION_DIR" tests/test_server.py` shows the `mock.patch.object` line
- [ ] Test 3 was shown to fail against the old logic (stated in your report)
- [ ] The README path-existence loop in Step 4 prints nothing
- [ ] `git status --short` shows changes only in `phone_server.py`, `tests/test_server.py`, `README.md`, `plans/README.md`. Untracked `samples/*.jpg` files may already be there. Leave them alone.
- [ ] `plans/README.md` row for 009 updated

## STOP conditions

Stop and report back, without improvising, if:

- The drift check shows changes and the excerpts above no longer match the code.
- `calibration_checked` is used anywhere other than `phone_server.py` lines 47, 196, 218 and 220, or `tests/test_server.py` after Step 1.
- `from tests.test_calibration import ...` fails to import under `unittest discover`. Do not copy the helpers into `test_server.py` without reporting first.
- `build_calibration([make_sheet(solid, STRAIGHT)[0]])` does not give 4 regions.
- Test 3 passes against the old `calibration_checked` logic.
- Any step seems to need a change to `calibration.py` or to the `__main__` block of `phone_server.py`.
- Anything writes to the repo's real `calibration/` folder.

## Maintenance notes

- `checked_size` makes the server read the disk once per *new* frame size, never once per frame. If a future change adds a "camera moved" watcher (draft plan 003), that watcher must set `calibration = None` **and** reset `checked_size = None`. Otherwise it would reload the same stale file, or never reload it.
- A reloaded calibration is only correct if the camera and paper are back where they were at calibration time. The existing frame-size check can't detect a moved camera. Plan 003's watcher is the place for that.
- Any new server test that saves a calibration must use `self.cal_dir`, never `phone_server.BASE_DIR / "calibration"`.
- Reviewer: check that `frame_size` is defined once, and that nothing inside the `if calibrating:` block changed.
