# Plans

Plans are listed in execution order where they depend on each other. Each one says which commit it was written against.

| # | Plan | Status | Depends on |
|---|---|---|---|
| 001 | [Camera server hardening + test baseline](001-camera-server-hardening.md) | DONE: merged to main | — |
| 002 | [Paper region calibration (M-1)](002-paper-region-calibration.md) | DONE: merged to main | 001 |
| 003 | [Calibration robustness](003-calibration-robustness.md) | DRAFT, stale: it names `receive_frame` (the logic is now in `process_frame`), and its "first hand only" edge stabilisation conflicts with the open two-hands finding below. Rewrite against current code before running it. | 002 |
| 004 | [Hand-drawn outlines and portrait paper](004-hand-drawn-outlines-and-portrait.md) | DONE: merged to main | 002 |
| 005 | [Frame rate and 640×480 capture](005-frame-rate-and-resolution.md) | DONE: merged to main | 004 |
| 006 | [Piano ordering, small keys, rotation](006-piano-ordering-small-keys-rotation.md) | DONE: merged to main (aa9324e) | 005 |
| 007 | [Live calibration sliders](007-calibration-sliders.md) | DONE: merged to main (fb2dadb) | 006 |
| 008 | [Strap import + M0 tools](008-strap-import-and-m0-tools.md) | DONE: merged to main (97f37e6); awaiting strap for real sessions | 007 |
| 009 | [Test isolation, calibration reload, README structure](009-test-isolation-calibration-reload-readme.md) | DONE: reviewed (one review fix), merged to pipeline | 011 |
| 010 | [Seal faint keyboard borders (printed piano on white desk)](010-seal-faint-keyboard-borders.md) | DONE: reviewed and approved, merged to main (810b120, 0df79c5) on 2026-11-03; 36 tests OK, 24/24 chromatic on all 3 user photos | — (independent of 009) |
| 011 | [Restore --https, macOS camera, camera-list retry lost in the merge](011-restore-upstream-https-and-macos-camera.md) | DONE: reviewed, merged to pipeline (20bd555) | — |
| 012 | [Pin the Tap SDK, drop the demo package.json](012-pin-tap-sdk-drop-package-json.md) | DONE: reviewed, merged to pipeline (4f35b4a) | — |
| 013 | [Tap window: camera finger names, stale status, clean shutdown](013-tap-window-names-liveness-shutdown.md) | DONE: reviewed, merged to pipeline | — |
| 014 | [Strap-hand selection (`--tap-hand`), highlight both hands](014-strap-hand-selection.md) | DONE: reviewed, merged to pipeline (20f51a8) | 013 (and after 009/011 to avoid conflicts) |
| 015 | [Strap taps → key events, CSV log](015-tap-to-key-events.md) | DONE: reviewed, merged to pipeline (bb9afae) | 013, 014 |
| 016 | [Play notes over MIDI (`--program`, `--base-note`)](016-play-notes-over-midi.md) | DONE: reviewed, merged to pipeline (d4f45aa) | 012, 015 |

## Open findings, not planned yet (audit 2026-11-06, at c6e260f)

- **Repo of record:** this repo (AJWPrototype) is now the master, as the user said on 2026-11-06. The camera repo and demo-repository are upstream of nothing. Port anything still committed there by hand; plan 011 exists because one commit was missed.
- **LICENSE copyright** says jennifer-m-gao (demo repo); the camera repo said Alex. This is the user's decision, not a plan.
- **The slider/trackbar logic is untested** (carried over): it's inline in `__main__`, and the sens↔ink_ratio formula is written twice.
- **Direction after 016:** an end-to-end latency harness (METRICS "Still to measure"), lift detection for note length, and note names/scales.

## Decisions from the design-doc grilling (2026-10-29)

- **Translation:** v1 plays the paper layout and swaps the output instrument (option a). Remapping to other layouts (b) and re-voicing real instruments (c) are future work.
- **Camera:** the phone sits on a stand looking straight down; a slight tilt is tolerated. Angled views are future work.
- **Transport:** iPhone over ngrok to localhost:5000 for now. Free upgrades later: Cloudflare quick tunnel, or LAN HTTPS with mkcert.
- **Template:** black ink on white US Letter, landscape. Regions are solid black boxes or black-outlined white areas, and solid wins where they overlap. Regions are numbered 1..N left to right, which gives chromatic order on a piano drawing. Note names (C4, C#4, ...) come later, anchored to MIDI numbers.
- **Repo:** this repo is the master repo. Tap Strap code joins it when strap work starts.
- **Parked:** synth choice (default idea: built-in Windows GS synth via mido), instrument switching UX, strap M0 measurements, lift detection for note length (test, then decide; fixed length is the fallback), light-coloured desks.
- **Reminder owed to the user:** when 002 lands, take 3 S-key snapshots (normal light, dim light, slight tilt) for fixtures.

## Considered and rejected

- Deleting `tap_strap_live.py` / `hello_tap.py` (2026-11-06): they're teammates' standalone strap scripts and still run. Plan 009 documents them as not used by the app.
- Restoring upstream's `finally:` block (2026-11-06): the local Windows `TerminateProcess` exit isn't in upstream `77d5cbd`; it's a local fix and stays.

- Binding to 127.0.0.1: the transport may move to LAN HTTPS, which needs LAN reachability.
- The ngrok URL in git history: it's a hostname, not a credential.
- Unauthenticated `/frame` (2026-11-03): the worst case is fake frames into a local toy, and it follows from the LAN-reachability decision above.
- Skipping paper detection per frame once calibrated (2026-11-03): processing is about 13 ms per frame, so the headroom is fine. Revisit only if `proc` becomes a bottleneck on AC power.
- The slider float round-trip (2026-11-03): checked, and `0.5 + 0.4*70/100 == 0.78` exactly. Saved settings don't trigger a spurious rebuild.
- A one-off OpenBLAS memory-allocation error during a test run (2026-11-03): it didn't happen again on two reruns.
- Pixel tweaks to make faint printed borders count as ink (2026-11-03): ratio on a 3×3/unblurred image recovered at most 3 keys and broke `test_blank_piano_needs_higher_sensitivity`. Faint printed borders and ruled lines have the same darkness (~0.8) and the same colour (saturation ≈ 23–29, not blue), so no pixel threshold separates them. Plan 010's hull seal is the shape-based answer.
- Light desks: separating paper from a white desk by colour or brightness (2026-11-03): measured on the user's frames, paper V 188–212 vs desk V 186–197, with the same low saturation and the same Lab b. There is no usable threshold.
- Light desks: using the drawing's printed outline (Canny 4-gon, ×1.15–1.25 margin) as the "paper" when the paper merges with the desk (2026-11-03): it found the outline reliably, but flattening the long keyboard to Letter proportions added a false white key (25 instead of 24) on all 3 frames, which is worse than plan 010 alone (24/24). Revisit only if flattening keeps the quad's own aspect ratio, and only with a failing photo to justify it.
