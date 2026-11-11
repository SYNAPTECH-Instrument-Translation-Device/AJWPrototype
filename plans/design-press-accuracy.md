# Design draft: more accurate finger presses

**Status:** DRAFT (2026-11-10). Phase 0 became plan 017 and Phase 1 became plan 018.

**Decisions (user, 2026-11-10):** accuracy as high as possible (no fixed stop: track the numbers in METRICS.md and keep improving); one user, so calibrate and train on that person only; chords must work eventually, so no fix may suppress real simultaneous taps.

## What "accurate" means here

A press is right when all four of these are right:

| Stage | Question | Code today | Main ways it fails |
|---|---|---|---|
| 1. Detect | Did a finger tap? | `tap_view.py:97`: one fixed threshold `TAP_G = 0.5 g`, 0.15 s refractory | Resting or moving hands cross 0.5 g; soft taps don't |
| 2. Attribute | Which finger? | Each finger is thresholded on its own | Crosstalk: a hard index tap also shakes middle/ring and fires them too (M0 synthetic data had 30%) |
| 3. Locate | Which key was it on? | `phone_server.py:511`: the **latest** camera frame's fingertip landmark | The frame is up to about 33 ms + processing old or new; the landmark is the fingernail tip, not the pad touching paper; tips on key borders flicker |
| 4. Hand | Is it the strap hand? | MediaPipe handedness label (`--tap-hand`) | The label mapping is unverified (see lesson 1) |

We have **no ground truth yet**. There are no real strap recordings in `recordings/` and no labelled camera data. Any improvement, ML or not, needs that first.

## Phase 0: Measure before changing (do first, small)

**Guided test session.** This is `m0_record.py` extended to the camera. The app shows "tap key 5 with your index" about 50 times, covering random keys and all fingers, and logs:
- the strap stream and the cue times (already supported by `m0_record.py`);
- the camera fingertip positions at about 30 Hz, with host timestamps;
- every detected event and the key the pipeline chose (already in `taps_*.csv`).

The report gives one number per stage: detection precision/recall, finger attribution accuracy, key accuracy, and median tap→sound latency. Those go into `METRICS.md`. This is also the labelled dataset for any later ML, so it isn't throwaway work.

## Phase 1: A per-user calibration step (no ML)

Add a 30-second step after the paper calibration (C), started with a key such as T:
1. **Rest for 3 s:** record the noise level on each finger.
2. **Tap each finger 5 times on any key:** record each finger's tap peaks and how much it shakes the other fingers.
3. Save the results to `calibration/tap_profile.json`. Each finger gets its own threshold, set between its noise and its weakest tap (for example, the midpoint, but at least noise + 5σ). It also gets a crosstalk ratio.

This replaces the guessed `TAP_G` with values measured on this person and this strap fit.

## Phase 2: Cheap algorithm fixes (no ML), each checked against Phase 0

1. **Chord-aware crosstalk filter.** When several fingers fire within about 25 ms, drop finger B only if `peak_B < k × crosstalk[A][B] × peak_A` for the strongest finger A (the matrix comes from plan 018; tune k with guided sessions). Real chords survive; shake doesn't. Plain winner-take-all is rejected because it would kill chords. Fixes stage 2.
2. **Look up the key at the tap's time.** Keep a short ring buffer of `(frame_time, fingers)` (about 0.5 s). Use the frame closest to `tap_time − camera_lag`, with the lag measured in Phase 0, instead of the latest frame. Fixes stage 3 timing.
3. **Contact-point correction.** Move the point from the tip landmark a little way back along the DIP→TIP direction (a fraction learned from the calibration taps), so it sits on the pad.
4. **Border tolerance.** If the point is in a gap or within a few pixels of a border, choose the nearest key, or keep that finger's last key. Fixes flicker.
5. **Camera gate (optional).** Ignore a strap event unless that fingertip was over a key and moving down in the last about 100 ms. This cuts false taps from waving or typing.

## Phase 3: ML, only where Phase 2 isn't good enough

Pick the model by what Phase 0 shows is still wrong.

- **Detection or attribution errors remain:** train a small **tap classifier on strap windows**. The input is 120 ms at 200 Hz around a candidate peak: 5 fingers × 3 axes, plus thumb IMU = about 500 numbers. The output is one of: none / thumb / index / middle / ring / pinky.
  - Start with simple features (each finger's peak, energy and ratio to the others) and a logistic regression or gradient-boosted trees (scikit-learn). Move to a small 1-D CNN only if needed.
  - Training data: the labelled M0 and Phase 0 sessions (a few hundred taps per person). Personalise by fine-tuning on the Phase 1 calibration taps.
  - It runs in microseconds, so it doesn't affect latency.
- **Key location errors remain:** fit a **per-finger offset model**. This is linear regression from (landmark position, hand angle) to the true contact point, using the guided taps where the target key is known. It's tiny, easy to understand, and probably enough.
- **Not recommended for now:** an end-to-end video model, or a custom press detector trained on camera frames. They need much more data and a GPU, and the strap already detects press timing well.

## Suggested order

| Step | Effort | Unlocks |
|---|---|---|
| Phase 0 guided session + report | M | Numbers, and a labelled dataset |
| Phase 1 calibration step | S–M | Per-user thresholds |
| Phase 2.1 + 2.2 | S each | Likely the biggest accuracy gains |
| Phase 2.3–2.5 | S each | Only if the Phase 0 numbers show key errors |
| Phase 3 classifier | M–L | Only if detection or attribution is still below target |

Target: as high as possible. Each plan must show a gain in the plan 017 session report, measured on the same user before and after.

