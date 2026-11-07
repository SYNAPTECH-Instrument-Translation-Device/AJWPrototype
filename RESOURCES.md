# AJWPrototype Pipeline Resources

## Knowledge

- [The repo itself: phone_server.py, tap_view.py, sound.py, plans/](./plans/README.md)
  The primary source. Each plan in `plans/` explains why a change was made. Use for: any "why is it like this?" question.
- [Google: MediaPipe Hand Landmarker guide](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker)
  Official docs: landmark indices (index tip = 8), and handedness and mirroring. Use for: the `--tap-hand` question, fingertip mapping.
- [mido: Message Types](https://mido.readthedocs.io/en/stable/message_types.html)
  Every MIDI message and its value range (note, velocity, program 0..127). Use for: anything in sound.py.
- [Python docs: threading, Lock objects](https://docs.python.org/3/library/threading.html#lock-objects)
  Use for: why `TapMonitor` guards its state with a lock and how `pop_events` stays safe.
- [Python docs: asyncio.run](https://docs.python.org/3/library/asyncio-runner.html)
  Use for: how the strap thread runs its own event loop.
- [TapWithUs tap-python-sdk (pinned commit e92d130)](https://github.com/TapWithUs/tap-python-sdk/tree/e92d13011ff95f2182604b130aeda633c225cd20)
  Use for: raw sensor mode, and how typing mode is restored.

## Wisdom (Communities)

- [MediaPipe GitHub issues](https://github.com/google-ai-edge/mediapipe/issues)
  Search here for real-world handedness and mirroring reports before changing the `--tap-hand` default.
- [Tap Strap developer community (TapWithUs on GitHub)](https://github.com/TapWithUs)
  Use for: questions about raw sensor mode and the SDK.

## Gaps
- No trusted source yet for tap-detection thresholds on finger accelerometers. Your own M0 recordings (`m0_analyze.py`) are the best evidence.
