# Plan 014: Use the hand that wears the strap for the Tap window, and highlight keys under both hands

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat c6e260f..HEAD -- phone_server.py tests/test_server.py README.md`
> Plans 011 (camera/https functions, argparse) and 009 (calibration-load block,
> server test `setUp`, README Project Structure) may already have changed these
> files. That is expected. Compare only the regions excerpted below. On a
> content mismatch in those regions, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the per-frame pipeline)
- **Depends on**: 013 (the Tap window must accept capitalised finger names)
- **Category**: bug
- **Planned at**: commit `c6e260f`, 2026-11-06

## Why this matters

The project is a virtual piano on paper. A phone camera looks down at a paper
keyboard, MediaPipe finds the hands, and a Tap Strap 2 worn on **one** hand
reports finger taps. `phone_server.py` asks MediaPipe for 2 hands
(`num_hands=2`) but only ever uses `result.hand_landmarks[0]`, whichever hand
MediaPipe happens to list first. So:

- the Tap Strap window's "camera" column (which key each finger is on) can show
  the hand **without** the strap, which makes the strap ↔ key pairing wrong;
- keys under the second hand are never highlighted.

After this plan, `--tap-hand left|right` (default `right`) picks the strap hand.
`latest_fingers` holds that hand's fingers (or the first hand when no strap is
used), and keys under every detected hand are highlighted.

## Current state

MediaPipe's `HandLandmarkerResult` has `hand_landmarks` (list per hand, 21
points with normalised `.x`, `.y`) and `handedness` (list per hand, each a list
of categories; `handedness[i][0].category_name` is `"Left"` or `"Right"`).
**MediaPipe assumes a mirrored (selfie) image when labelling.** The phone page
uses the rear camera (`facingMode: "environment"` in `phone_camera.js:136`), and
Camo/webcam frames are also unmirrored, so MediaPipe's label is the **opposite**
of the real hand. This is an assumption that hasn't been checked with a real hand.
See STOP conditions and Maintenance notes.

`calibration.py:11`: `FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}`.
`calibration.region_at(cal, x_norm, y_norm)` (`calibration.py:273-277`) returns the
region number at a normalised point (0 = no region). It reads only
`cal["frame_size"]` (w, h) and `cal["key_map"]` (2-D int array, shape h×w).

`phone_server.py`, end of `process_frame` (around lines 252-269 at `c6e260f`):
```python
    fingers = {}
    if cal is not None:
        if result.hand_landmarks:
            hand = result.hand_landmarks[0]
            fingers = {
                name: region_at(cal, hand[i].x, hand[i].y)
                for name, i in FINGERTIPS.items()
            }
        annotated = draw_calibration(
            annotated, cal, {r for r in fingers.values() if r}
        )

    # Draw detected hand landmarks on top of the overlay.
    annotated = draw_hand_landmarks(annotated, result)

    with frame_lock:
        latest_frame = annotated
        latest_fingers = fingers
```

`__main__` (around lines 341-359): the `--tap`, `--tap-demo`, `--tap-address`
arguments, then:
```python
    tap = None
    if args.tap or args.tap_demo:
        tap = TapMonitor(demo=args.tap_demo, address=args.tap_address)
        tap.start()
```
The display loop copies `fingers = dict(latest_fingers)`, prints it on the bottom
line of the camera window as `T:3  I:-  ...`, and calls `tap.render(fingers)`.

Module globals live near the top (`latest_fingers = {}` at line 51).

**Conventions:** module-level globals guarded by `frame_lock`; short `# why`
comments; stdlib `unittest`; plain imperative commit messages. Server tests are in
`tests/test_server.py` (class `ServerTests`, `unittest.TestCase`).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Server tests | `<python> -m unittest tests.test_server -v` | all `ok` |
| All tests | `<python> -m unittest discover -s tests -t .` | `OK (skipped=1, expected failures=1)` |
| Flags | `<python> phone_server.py --help` | shows `--tap-hand {left,right}` |

`<python>` is `.venv/Scripts/python.exe`, or `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`
if the worktree has no `.venv`. Don't install anything.

## Scope

**In scope**: `phone_server.py` (new pure helper, end of `process_frame`, one
global, one argument), `tests/test_server.py` (new tests only), `README.md`
(one paragraph in the "Camera + Tap Strap together" section).
**Out of scope**: `calibration.py`, `tap_view.py`, `draw_hand_landmarks`, the
calibration-capture logic in `process_frame`, the slider code.

## Git workflow

Commits: `Pick the strap hand's fingers by handedness` and `Document --tap-hand`. Do not push.

## Steps

### Step 1: Add a pure helper and test it

Add to `phone_server.py`, just above `process_frame`:
```python
def hand_fingers(result, cal, strap_label=None):
    """Return (fingers of the chosen hand, regions under any fingertip).

    The chosen hand is the one MediaPipe labels strap_label, or the first hand if
    strap_label is None. fingers is {} when that hand isn't visible.
    """
    chosen, touched = {}, set()
    for i, hand in enumerate(result.hand_landmarks):
        fingers = {name: region_at(cal, hand[k].x, hand[k].y) for name, k in FINGERTIPS.items()}
        touched |= {r for r in fingers.values() if r}
        label = result.handedness[i][0].category_name if i < len(result.handedness) else None
        if (strap_label is None and i == 0) or (strap_label is not None and label == strap_label):
            chosen = fingers
    return chosen, touched
```

In `tests/test_server.py`, add a class `HandFingersTests(unittest.TestCase)` with
fakes built from `types.SimpleNamespace` (no MediaPipe):
- a fake `cal = {"frame_size": (100, 100), "key_map": km}`, where `km = np.zeros((100, 100), int)`, `km[:, :50] = 1`, `km[:, 50:] = 2`;
- `make_hand(x)` returns 21 `SimpleNamespace(x=x, y=0.5)` points;
- `make_result(hands)` takes a list of `(label, x)` pairs and returns
  `SimpleNamespace(hand_landmarks=[make_hand(x) ...], handedness=[[SimpleNamespace(category_name=label)] ...])`.

Tests:
1. `test_first_hand_without_strap_label`: hands `[("Left", 0.2), ("Right", 0.8)]`, `strap_label=None` → every finger is `1`, `touched == {1, 2}`.
2. `test_strap_label_picks_that_hand`: same hands, `strap_label="Right"` → every finger is `2`, `touched == {1, 2}`.
3. `test_strap_hand_missing`: hands `[("Left", 0.2)]`, `strap_label="Right"` → fingers `{}`, `touched == {1}`.
4. `test_no_hands`: no hands → `({}, set())`.

**Verify**: `<python> -m unittest tests.test_server -v` → the 4 new tests `ok`, all others `ok`.

### Step 2: Use the helper in `process_frame`
- Add a global near `latest_fingers`:
  `strap_label = None          # MediaPipe label of the strap hand; None = first hand.`
- Replace the `fingers = {}` / `if cal is not None:` block shown above with:
```python
    fingers = {}
    if cal is not None:
        fingers, touched = hand_fingers(result, cal, strap_label)
        annotated = draw_calibration(annotated, cal, touched)
```
  `strap_label` is only read here, so it needs no `global` statement in `process_frame`.

**Verify**: full suite passes (same count as after Step 1).

### Step 3: Add `--tap-hand`
After the `--tap-address` argument:
```python
    parser.add_argument(
        "--tap-hand", choices=["left", "right"], default="right",
        help="hand wearing the strap; its fingers fill the Tap window's key column",
    )
```
Inside `if args.tap or args.tap_demo:`, before creating `TapMonitor`, add:
```python
        # MediaPipe labels hands as if the image were mirrored; ours aren't, so swap.
        strap_label = {"left": "Right", "right": "Left"}[args.tap_hand]
```
This assignment is at module level (inside `if __name__ == "__main__":`), so it
sets the global that `process_frame` reads. Keep it before any frames are processed
(the processing thread is already running, but a frame or two read with the
default `None` is harmless).

**Verify**: `--help` shows `--tap-hand {left,right}`.

### Step 4: README
In `README.md`, section `### Camera + Tap Strap together`, after the existing
paragraph, add:
```markdown
`--tap-hand left|right` (default `right`) says which hand wears the strap, so the key column follows that hand. Keys under both hands are highlighted. If the column follows your other hand, switch the value: hand labels assume an unmirrored camera image, which hasn't been checked with every camera yet.
```

## Test plan

Four pure-function tests (Step 1) cover hand choice, the missing strap hand, no
hands, and highlighting both hands. The existing server tests cover `process_frame`
with no hands present.

## Done criteria

- [ ] `<python> -m unittest tests.test_server -v` → all `ok`, including the 4 `HandFingersTests`
- [ ] Full suite `OK (skipped=1, expected failures=1)`, 4 more tests than before
- [ ] `grep -n "hand_landmarks\[0\]" phone_server.py` → no output
- [ ] `--help` shows `--tap-hand`
- [ ] Diff touches only `phone_server.py`, `tests/test_server.py`, `README.md`

## STOP conditions

- `result.handedness` doesn't exist on MediaPipe's result in this venv
  (`<python> -c "from mediapipe.tasks.python import vision; print(vision.HandLandmarkerResult.__dataclass_fields__.keys())"`
  must list `handedness`).
- The excerpted `process_frame` block doesn't match.
- A change seems to be needed in `tap_view.py` or `calibration.py`.

## Maintenance notes

- **Unverified assumption:** label swapping for unmirrored cameras. The first real
  run with a strap should check it. If it's wrong for every camera, flip the dict in
  Step 3, not the README advice.
- When MediaPipe gives both hands the same label (rare, crossed hands), the last
  one wins. That's acceptable for v1.
- Plan 015 reads `latest_fingers` (the strap hand) to turn strap taps into keys.
