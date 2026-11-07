# Mission: Own the AJWPrototype tap-to-note pipeline

## Why
AJWPrototype is now the master repo, and Claude wrote most of the new pipeline code (camera → strap tap → note). The goal is to understand that code well enough to explain it to teammates, debug it on real hardware, and extend it without breaking it.

## Success looks like
- Trace any tap through the code and predict the note, velocity and log row
- Explain why each of the session's changes (plans 009, 011–016) was needed and where it lives
- Diagnose a live problem (wrong hand, missed taps, no sound) from the logs and the Tap window
- Make the next change yourself (e.g. lift detection, tuning TAP_G) with a test

## Constraints
- Learning happens alongside building the prototype; lessons must be short
- Hardware (Tap Strap, Camo camera) isn't always at hand

## Out of scope
- MediaPipe/ML internals, BLE protocol details, music theory beyond MIDI note numbers
