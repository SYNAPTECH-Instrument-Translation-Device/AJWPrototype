# Plan 010: Printed piano keyboards with faint borders calibrate to every key, in chromatic order

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ce1af56..HEAD -- calibration.py tests/test_calibration.py`
> If it prints anything, compare the "Current state" excerpts below with the
> live code. On any mismatch, STOP.

## Status

- **Priority**: P1. This is the user's reported bug, on their real setup.
- **Effort**: S
- **Risk**: MED. It changes region detection, which every calibration test exercises.
- **Depends on**: none. Independent of plan 009 (different files).
- **Category**: bug
- **Planned at**: commit `ce1af56`, 2026-11-03

## Why this matters

The user printed a two-octave piano keyboard (14 white keys, 10 black keys) on white paper. They photographed it on a white desk with the iPhone over Camo, at 640×360. Calibration gets the white keys badly wrong. Some white keys disappear completely, and where they should be, the user sees short boxes that stop at the bottom of the black keys. The real keys run much further down.

The advisor diagnosed this on the user's three saved frames:

1. **Faint borders.** The keyboard's printed **top and left border lines are too thin and faint** at this camera distance to pass the ink test. Any white key whose top edge relied on that border is no longer enclosed. Its white area connects to the paper around the keyboard and is thrown away as "not enclosed". The black keys next to it are then grown 20 px outward by the gap-snapping step, which produces the short boxes the user saw.
   - Raising the sensitivity slider doesn't fully fix it: at the maximum, 1 white key is still missing.
   - It can't be fixed by darkness or colour. The faint printed border is as dark as (ratio ≈ 0.8) and the same colour as the ruled lines on notebook paper, which the code deliberately ignores (see the comment at `calibration.py:102-104`).
2. **Desk objects become keys.** On a white desk, the paper isn't separated from the desk, so `find_paper_corners` returns roughly the **whole frame**, for example `[[0,0],[599,0],[490,359],[0,359]]`. A laptop corner and a desk shadow then become "keys" 1 and 24/25/27, which shifts the 1..N numbering away from C = 1.

The fix is two small, shape-based changes in `find_regions`:

- **(a) Seal each ink drawing with its convex hull.** Before looking for enclosed white areas, draw each ink drawing's convex hull back onto the ink as a 3 px line. This puts back any missing *outside* border.
- **(b) Ignore anything touching the paper's edge band.** Don't seal, and don't keep as a region, any ink drawing that touches the strip within `BORDER_PX + 2` px of the flattened paper's edge.

The advisor prototyped exactly this outside the repo. At the user's slider settings (`ink_ratio 0.78, line_kernel 9`) and at `0.86, 9`, all three frames gave **24 regions with kinds `OSOSOOSOSOSOOSOSOOSOSOSO`**, which is perfect chromatic order. Before the fix they gave 7–12 of the 14 white keys. All other calibration tests still pass, except one that asserted the old limitation (Step 4).

## Current state

Files:
- `calibration.py`: calibration pipeline. `find_regions(flat, ink_ratio, line_kernel)` (lines 98–192) turns a flattened grayscale paper image (1100×850, or 850×1100 for portrait) into a numbered region map.
- `tests/test_calibration.py`: unittest tests, including real-photo regression tests from `tests/fixtures/`.
- `samples/frame_20261030_115735.jpg`, `samples/frame_20261030_115736.jpg`, `samples/frame_20261030_115741.jpg`: the user's three new 640×360 frames of the printed keyboard. They are **untracked** in git.
- `METRICS.md`: an append-only results log (rules at the top of the file: add rows, never edit old ones).

Constants, `calibration.py:10-19`:
```python
FLAT_W, FLAT_H = 1100, 850   # US Letter landscape, 100 px per inch.
FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}
BORDER_PX = 12               # Ignore ink this close to the paper edge.
DARK_RATIO = 0.7             # Darker than this fraction of the wider paper is solid ink.
INK_RATIO = 0.7            # Darker than this fraction of nearby paper is ink.
SPECK_AREA = 50
LINE_KERNEL = 15             # Wider than outlines, narrower than solid boxes.
MIN_REGION_AREA = 300  # About 0.2 cm²; allows small keys.
GAP_KERNEL = 11            # Closes small breaks in hand-drawn outlines.
SNAP_PX = 20                 # About 0.5 cm.
```

The part of `find_regions` you will change, `calibration.py:130-164`:
```python
    # Solid regions: ink that survives opening with a kernel wider than lines.
    opened = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((line_kernel, line_kernel), np.uint8)
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    solids = [
        labels == i for i in range(1, n)
        if stats[i, cv2.CC_STAT_AREA] >= MIN_REGION_AREA
    ]

    # Outlined regions: white areas enclosed by ink.
    closed = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE, np.ones((GAP_KERNEL, GAP_KERNEL), np.uint8)
    )
    closed = cv2.dilate(closed, np.ones((3, 3), np.uint8))
    white = np.where(closed == 0, 255, 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    outlined = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w == fw or y + h == fh:
            continue
        if area < MIN_REGION_AREA:
            continue
        outlined.append(labels == i)

    # Paint outlined first, then solid on top, with temporary IDs.
    flat_map = np.zeros((fh, fw), np.uint16)
```
`fh, fw = flat.shape` is set at the top of the function (line 99).

The test that encodes the old limitation, `tests/test_calibration.py:186-191`:
```python
    def test_blank_piano_needs_higher_sensitivity(self):
        img = cv2.imread(str(Path(__file__).parent / "fixtures" / "blank_piano_small.jpg"))
        cal = build_calibration([img])
        self.assertLess(len(cal["regions"]), 12)
        kinds = "".join(r["kind"][0].upper() for r in rebuild_calibration(cal, 0.8, 15)["regions"])
        self.assertEqual(kinds, "OSOSOOSOSOSO")
```
With the fix, the default settings now give `OSOSOOSOSOSO` (12 regions) on this photo, so `assertLess(..., 12)` fails. This is the improvement working, not a regression.

Kind letters: `O` = outlined (white key), `S` = solid (black key). One octave in chromatic order is `OSOSOOSOSOSO`.

**Conventions to match:**
- Module constants at the top of `calibration.py`, each with a short trailing `#` comment.
- Comments explain *why* in plain words, for example `calibration.py:111-112`: `# Solid boxes are too big for the 31 px estimate, so compare them with a much wider one. Relative, so a soft shadow never counts as a black box.`
- Real-photo tests follow `test_piano_sketch_on_lined_paper` (`tests/test_calibration.py:178-184`). They start with a comment saying what the photo is and what used to go wrong, loop over the fixture names, and pass the name as the assert message.
- Stdlib `unittest`, no new dependencies.
- Commit messages are plain imperative sentences, for example `Don't mistake soft shadows for solid black keys`.

## Commands you will need

Run from the repo root with the project venv (`.venv\Scripts\python.exe` on Windows; `python` once activated).

| Purpose | Command | Expected on success |
|---|---|---|
| Calibration tests | `python -m unittest tests.test_calibration -v` | all `ok` / `expected failure` |
| All tests | `python -m unittest discover -s tests -t .` | ends `OK (skipped=1, expected failures=1)` |
| Debug one photo | `python calibrate_image.py <photo> <out.png>` | prints the region count and each region |

The baseline at `ce1af56` is `Ran 35 tests … OK (skipped=1, expected failures=1)`. If plan 009 has landed, the total is 38. Either way, the totals must end up 1 above where you started (Step 3 adds one test). If you see a one-off `OpenBLAS error: Memory allocation still failed`, re-run with `OPENBLAS_NUM_THREADS=1`.

When running `calibrate_image.py`, always pass the second (output) argument pointing outside the repo, or delete the `_debug.png` it writes. Without it, it writes next to the input photo.

## Scope

**In scope** (the only files you may modify or create):
- `calibration.py`: new constants plus `find_regions` only.
- `tests/test_calibration.py`
- `tests/fixtures/printed_piano_white_desk_1.jpg` (create: a copy of `samples/frame_20261030_115735.jpg`)
- `tests/fixtures/printed_piano_white_desk_2.jpg` (create: a copy of `samples/frame_20261030_115741.jpg`)
- `METRICS.md`: append rows only.
- `plans/README.md`: only this plan's row.

**Out of scope** (do NOT touch):
- `paper_detector.py` and `find_paper_corners`. Better paper detection on light desks is real future work, but it's a much bigger change. Step 2's edge rule is enough for this bug.
- The ink tests (`adaptive`, `ratio`, `dark`, `INK_RATIO`, `DARK_RATIO`). Changing them brings back the ruled-line bug that `tests/test_calibration.py:178` guards against.
- `phone_server.py`, including the slider defaults.
- The `samples/` files. Copy them; never move, edit or `git add` them.
- `test_hand_drawn_box_portrait`. It is an `expectedFailure` and must stay one.

## Git workflow

- Branch: `advisor/010-seal-faint-keyboard-borders`
- One commit per step. Suggested messages:
  - `Seal faint outer borders so white keys don't leak into the paper`
  - `Ignore ink touching the paper edge, like desk objects on a white desk`
  - `Add printed-keyboard-on-white-desk regression photos`
  - `Blank small piano now calibrates at default sensitivity`
  - `Log printed-keyboard calibration result`
- Do not push. Do not open a PR.

## Steps

### Step 1: Seal each ink drawing's outside with its convex hull

In `calibration.py`, add two constants after `SNAP_PX`:
```python
HULL_MIN_AREA = 5000         # Smaller ink blobs (stray marks) don't get sealed.
EDGE_PX = BORDER_PX + 2      # Ink this close to the paper edge is the desk, not a drawing.
```

In `find_regions`, insert this block between `closed = cv2.dilate(...)` and `white = np.where(closed == 0, ...)`:
```python
    # Seal each drawing's outside edge with its convex hull. Thin printed
    # borders can be too faint to pass the ink test (they look like ruled
    # lines); without this, white keys leak into the paper and vanish.
    n_c, labels_c, stats_c, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    for i in range(1, n_c):
        x, y, w, h, area = stats_c[i]
        if area < HULL_MIN_AREA or touches_edge(x, y, w, h, fw, fh):
            continue
        pts = cv2.findNonZero((labels_c == i).astype(np.uint8))
        cv2.polylines(closed, [cv2.convexHull(pts)], True, 255, 3)
```

Add a small module-level helper just above `find_regions`:
```python
def touches_edge(x, y, w, h, fw, fh):
    # True if a bounding box reaches into the strip along the paper edge.
    return x <= EDGE_PX or y <= EDGE_PX or x + w >= fw - EDGE_PX or y + h >= fh - EDGE_PX
```

**Verify**: `python -m unittest tests.test_calibration -v`. Exactly one test fails, `test_blank_piano_needs_higher_sensitivity` (handled in Step 4). Every other test is `ok`, and `test_hand_drawn_box_portrait` is still `expected failure`. Any other failure means STOP.

### Step 2: Drop regions that touch the paper's edge strip

In `find_regions`, immediately before the `# Paint outlined first, then solid on top, with temporary IDs.` comment, add:
```python
    # On a light desk the "paper" can include the desk, so a laptop corner or
    # shadow at the edge would become key 1. Real drawings sit inside a margin.
    def inside(m):
        ys, xs = np.nonzero(m)
        return not touches_edge(xs.min(), ys.min(), xs.max() - xs.min() + 1,
                                ys.max() - ys.min() + 1, fw, fh)
    solids = [m for m in solids if inside(m)]
    outlined = [m for m in outlined if inside(m)]
```

**Verify**:
- Same as Step 1: only `test_blank_piano_needs_higher_sensitivity` fails.
- Then check the user's photos. Save this as a throwaway script *outside the repo*, or run it with `python -c`:
  ```python
  import cv2
  from calibration import build_calibration
  for f in ("115735", "115736", "115741"):
      img = cv2.imread(f"samples/frame_20261030_{f}.jpg")
      for s in ((0.78, 9), (0.86, 9)):
          k = "".join(r["kind"][0].upper() for r in build_calibration([img], *s)["regions"])
          print(f, s, len(k), k == "OSOSOOSOSOSO" * 2)
  ```
  Expected: 6 lines, each ending `24 True`.

### Step 3: Add the user's photos as regression fixtures and a test

Copy (don't move) the photos:
- `samples/frame_20261030_115735.jpg` → `tests/fixtures/printed_piano_white_desk_1.jpg`
- `samples/frame_20261030_115741.jpg` → `tests/fixtures/printed_piano_white_desk_2.jpg`

Add this test to `CalibrationTests`, after `test_piano_sketch_on_lined_paper`:
```python
    def test_printed_piano_on_white_desk(self):
        # Real 640x360 Camo frames: a printed two-octave keyboard on a white
        # desk. The thin top border was too faint to see, so white keys leaked
        # into the paper and vanished; desk objects at the edge became keys.
        for name in ("printed_piano_white_desk_1.jpg", "printed_piano_white_desk_2.jpg"):
            img = cv2.imread(str(Path(__file__).parent / "fixtures" / name))
            for settings in ((0.78, 9), (0.86, 9)):
                kinds = "".join(
                    r["kind"][0].upper()
                    for r in build_calibration([img], *settings)["regions"]
                )
                self.assertEqual(kinds, "OSOSOOSOSOSO" * 2, f"{name} {settings}")
```

**Verify**:
- `python -m unittest tests.test_calibration.CalibrationTests.test_printed_piano_on_white_desk -v` → `ok`.
- To confirm the test catches the bug: `git stash push calibration.py`, re-run that one test, and it must FAIL. Then `git stash pop`. If it passes without the fix, STOP.

### Step 4: Update the test that asserted the old limitation

Rename `test_blank_piano_needs_higher_sensitivity` to `test_blank_piano_small`, and replace its body so it asserts the photo now works at **both** the default settings and the old higher-sensitivity settings:
```python
    def test_blank_piano_small(self):
        # Used to need higher sensitivity (11/12 keys at default); the hull
        # seal now closes the faint outline, so the default works too.
        img = cv2.imread(str(Path(__file__).parent / "fixtures" / "blank_piano_small.jpg"))
        cal = build_calibration([img])
        self.assertEqual("".join(r["kind"][0].upper() for r in cal["regions"]), "OSOSOOSOSOSO")
        kinds = "".join(r["kind"][0].upper() for r in rebuild_calibration(cal, 0.8, 15)["regions"])
        self.assertEqual(kinds, "OSOSOOSOSOSO")
```

**Verify**: the full suite, `python -m unittest discover -s tests -t .`, ends `OK (skipped=1, expected failures=1)`. The test count is one higher than when you started.

### Step 5: Log the result in METRICS.md

Append two rows to the end of the "## Calibration (paper keyboard detection)" table. Don't edit existing rows.
```markdown
| 2026-11-03 | Printed two-octave keyboard (14 white + 10 black keys) on a white desk, 640×360 Camo frames, at the user's slider settings | Before: 7–12 of 14 white keys (thin top border too faint, so keys leaked into the paper), plus a laptop corner and a desk shadow counted as keys. After: **24/24 keys in chromatic order** on all 3 frames | Measured on real photos, now regression tests |
| 2026-11-03 | Small blank hand-drawn keyboard at the default sensitivity | 11/12 → **12/12 in chromatic order**, no slider change needed | Measured on a real photo (existing regression test) |
```
Use the date you actually run this. If it isn't 2026-11-03, use the real date.

**Verify**: `git diff METRICS.md` shows only added lines (`+`), no removed lines (`-`).

## Test plan

- New: `test_printed_piano_on_white_desk` covers 2 real photos × 2 slider settings, with exact chromatic kinds.
- Changed: `test_blank_piano_needs_higher_sensitivity` → `test_blank_piano_small`, which now asserts the default works.
- Unchanged and must still pass: every other test in `tests/test_calibration.py`. The important ones are the guards against ruled lines (`test_piano_sketch_on_lined_paper`), shadows (`test_shadow_is_not_a_black_key`) and a stray box skewing the order (`test_stray_box_does_not_rotate_order`).
- Pattern: `test_piano_sketch_on_lined_paper`, `tests/test_calibration.py:178-184`.

## Done criteria

ALL must hold:

- [ ] `python -m unittest discover -s tests -t .` ends `OK (skipped=1, expected failures=1)`, with one more test than at the start
- [ ] The Step 2 script prints 6 lines ending `24 True`
- [ ] `test_printed_piano_on_white_desk` was shown to fail without the `calibration.py` change (stated in your report)
- [ ] `grep -n "needs_higher_sensitivity" tests/test_calibration.py` prints nothing
- [ ] `git diff --stat` lists only `calibration.py`, `tests/test_calibration.py`, `METRICS.md`, `plans/README.md`, and the two new fixtures show as added. `samples/` is unchanged.
- [ ] `plans/README.md` row for 010 updated

## STOP conditions

Stop and report back, without improvising, if:

- After Step 1 or Step 2, any test other than `test_blank_piano_needs_higher_sensitivity` fails, or `test_hand_drawn_box_portrait` stops being an expected failure. Don't tune `HULL_MIN_AREA`, `EDGE_PX` or the ink thresholds to make it pass.
- The Step 2 script prints anything other than `24 True` on all 6 lines.
- The `samples/frame_20261030_*.jpg` files are missing. They're untracked and could have been cleaned. Don't substitute other photos.
- A fix seems to need changes to `find_paper_corners`, `paper_detector.py`, or the ink tests.

## Maintenance notes

- **Known limit: concave layouts.** The hull seal closes a drawing's *outside*. In a drawing with a large concave notch (an L-shape, or two drawings closer than about 11 px, which the gap-closing merges into one), the notch becomes a fake "outlined" region if it is larger than `MIN_REGION_AREA`. Keyboards and separate boxes are fine (tests cover a stray box). If concave layouts matter later, seal only hull edges that pass along existing ink, instead of the whole hull.
- **Known limit: default settings on these photos.** At the default sliders (`ink_ratio 0.7`, `line_kernel 15`), the new photos still come out in the wrong order (23–26 regions). The user's saved settings, or sens ≥ 70 with key 9, work. Black keys this small need `Key` ≤ ~9. A future change could pick `line_kernel` from the measured black-key width.
- **The edge rule assumes drawings keep a ~1.4 cm (14 px flat) margin from the paper edge.** A key drawn right up to the edge is now dropped. That fits the template (`plans/README.md`: black ink on white Letter).
- **The real fix for item 2 is paper detection on light desks**, which the design decisions list as parked. When that lands, the edge rule stays as a cheap safety net.
- **Reviewer:** check that the hull block runs after the `closed` dilation and before `white` is computed, and that `solids` (the black keys) are filtered only by `inside`, never sealed.
