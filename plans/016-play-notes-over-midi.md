# Plan 016: Play a note for every strap tap on a paper key (MIDI, instrument selectable)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: confirm plan 015 has landed: `grep -n "pop_events" phone_server.py`
> must print one line, and `grep -n "class TapLog" tap_view.py` one line. If not, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (new dependency; audio device differs per machine)
- **Depends on**: 012 (requirements.txt edit), 015
- **Category**: direction (core pipeline)
- **Planned at**: commit `c6e260f`, 2026-11-06 (excerpts assume 015 applied)

## Why this matters

This is the last link of the pipeline: paper key → camera → strap tap → **sound**.
After plan 015, `phone_server.py` gets events `(host_time, finger, key, peak_g)`,
where `key` is the paper key number 1..N, numbered left to right, which is chromatic
order on a piano drawing. This plan plays MIDI note `base_note + key - 1` for each
event that has a key. Loudness comes from how hard the tap was. The instrument
is a General MIDI program number, which delivers the project's "instrument
translation" decision: *v1 plays the paper layout and swaps the output
instrument*. The decided default synth is the built-in Windows GS synth through
`mido`. A fixed note length (0.3 s) is the decided fallback until lift detection exists.

## Current state

`phone_server.py` display loop (after 015):
```python
            if tap is not None:
                cv2.imshow("Tap Strap", tap.render(fingers))
                for host_time, finger, peak in tap.pop_events():
                    # Strap names are lowercase; camera names are capitalised.
                    key = fingers.get(finger.capitalize())
                    tap_log.add(host_time, finger, key, peak)
```
`key` is an int ≥1, or 0/None for no key. `peak` is in g. `tap_view.TAP_G = 0.5`
is the smallest peak an event can have.
The `finally:` block prints `tap_log.summary()`, closes it, calls `tap.stop()`, then
kills the process (so release audio before that).
Arguments live in `if __name__ == "__main__":`, including `--tap`, `--tap-demo`,
`--tap-address` and `--tap-hand`.

`requirements.txt` after plan 012:
```
opencv-python==5.0.0.93
mediapipe==1.1.1
numpy==2.5.4
flask==3.1.3
tap-python-sdk @ git+https://github.com/TapWithUs/tap-python-sdk.git@e92d13011ff95f2182604b130aeda633c225cd20
matplotlib>=3.7
```

Verified during planning: wheels exist for this venv (Python 3.12, win_amd64):
`mido-1.3.3-py3-none-any.whl`, `python_rtmidi-1.5.8-cp312-cp312-win_amd64.whl`.

Conventions: small single-purpose modules at the repo root (`paper_detector.py`,
`tap_view.py`); stdlib `unittest`; short `# why` comments; plain imperative commit messages.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Install the 2 new deps | `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe -m pip install mido==1.3.3 python-rtmidi==1.5.8` | `Successfully installed` (or already satisfied) |
| Sound tests | `<python> -m unittest tests.test_sound -v` | all `ok` |
| All tests | `<python> -m unittest discover -s tests -t .` | `OK (skipped=1, expected failures=1)` |
| List MIDI outputs | `<python> -c "import mido; print(mido.get_output_names())"` | a list; on Windows it includes `Microsoft GS Wavetable Synth` |

`<python>` is `.venv/Scripts/python.exe`, or `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`
if the worktree has no `.venv`. Installing exactly these two pinned packages into
that venv is allowed. Install nothing else.

## Scope

**In scope**: `sound.py` (create), `tests/test_sound.py` (create), `phone_server.py`
(the arguments, the display loop's event loop, and `finally:`), `requirements.txt`
(append 2 lines), `README.md` ("Camera + Tap Strap together" section).
**Out of scope**: `tap_view.py`, `tapstrap/`, `calibration.py`, `process_frame`,
note names or scales (future work), lift detection.

## Git workflow

Commits: `Add a MIDI note player`, `Play a note for each tap on a key`. Do not push.

## Steps

### Step 1: Dependencies
Append to `requirements.txt`:
```
mido==1.3.3
python-rtmidi==1.5.8
```
Run the install command.
**Verify**: the "List MIDI outputs" command prints a list without error.

### Step 2: `sound.py`
```python
"""Plays paper keys as MIDI notes (default output: the OS synth, e.g. Microsoft GS Wavetable Synth)."""
import time

import mido

NOTE_S = 0.3  # shortcut: fixed note length until lift detection exists.


def key_note(key, base_note=60):
    """Paper keys are numbered 1..N left to right, so key 1 is base_note (60 = middle C)."""
    return base_note + key - 1


def tap_velocity(peak_g, low=0.5, high=3.0):
    """Harder taps play louder: low g -> 40, high g or more -> 127."""
    t = min(max((peak_g - low) / (high - low), 0.0), 1.0)
    return int(40 + t * 87)


class NotePlayer:
    def __init__(self, program=0, port=None):
        self.port = port if port is not None else mido.open_output()  # System default output.
        self.port.send(mido.Message("program_change", program=program))
        self.off_at = []  # (monotonic time, note) still sounding

    def play(self, note, velocity):
        if not 0 <= note <= 127:
            return  # Keys beyond the MIDI range stay silent.
        self.port.send(mido.Message("note_on", note=note, velocity=velocity))
        self.off_at.append((time.monotonic() + NOTE_S, note))

    def update(self, now=None):
        now = time.monotonic() if now is None else now
        due = [n for t, n in self.off_at if t <= now]
        self.off_at = [(t, n) for t, n in self.off_at if t > now]
        for note in due:
            self.port.send(mido.Message("note_off", note=note))

    def close(self):
        for _, note in self.off_at:
            self.port.send(mido.Message("note_off", note=note))
        self.off_at = []
        self.port.close()
```

### Step 3: `tests/test_sound.py`
Use a fake port: a class with `self.sent = []`, `send(msg)` that appends, and `close()`
that sets `self.closed = True`. Use the same `sys.path.insert` header as the other test
files (copy from `tests/test_tap_view.py`). Tests:
1. `key_note(1) == 60`, `key_note(13) == 72`, `key_note(1, base_note=48) == 48`.
2. `tap_velocity(0.5) == 40`, `tap_velocity(3.0) == 127`, `tap_velocity(10) == 127`, `tap_velocity(0) == 40`.
3. `NotePlayer(program=40, port=fake)` sends `program_change` with `program == 40` first.
4. `play(60, 100)` sends `note_on` 60. `update(now=time.monotonic())` sends nothing more. `update(now=time.monotonic() + 1)` sends `note_off` 60.
5. `play(200, 100)` sends nothing.
6. `close()` sends `note_off` for sounding notes and closes the port.

**Verify**: `<python> -m unittest tests.test_sound -v` → 6 `ok`.

### Step 4: Wire into `phone_server.py`
- Arguments (after `--tap-hand`):
  ```python
    parser.add_argument("--program", type=int, default=0, metavar="N",
                        help="General MIDI instrument 0-127 for tapped keys (0 = piano, 40 = violin)")
    parser.add_argument("--base-note", type=int, default=60, metavar="N",
                        help="MIDI note for paper key 1 (60 = middle C)")
    parser.add_argument("--no-sound", action="store_true", help="log taps without playing notes")
  ```
- Set `player = None` next to `tap = None`. Inside `if args.tap or args.tap_demo:`, after
  `TapLog` is created:
  ```python
        if not args.no_sound:
            try:
                from sound import NotePlayer
                player = NotePlayer(program=args.program)
            except Exception as error:  # No MIDI output or missing package: keep running silently.
                print(f"Sound off: {error}")
  ```
- In the event loop, after `tap_log.add(...)`:
  ```python
                    if player is not None and key:
                        player.play(key_note(key, args.base_note), tap_velocity(peak))
  ```
  and right after the `for` loop (still inside `if tap is not None:`): `if player is not None: player.update()`.
  Import `key_note, tap_velocity` from `sound` next to `NotePlayer` (inside the same `try`, so a
  missing `mido` doesn't break `--no-sound` runs). If the names aren't bound because the
  import failed, `player` is None and they're never used.
- In `finally:`, before the tap log summary:
  ```python
        if player is not None:
            player.close()
  ```

**Verify**: full suite passes; `<python> phone_server.py --help` shows `--program`, `--base-note`, `--no-sound`.

Audible check (optional, Windows only, needs speakers):
`<python> -c "import time; from sound import NotePlayer; p=NotePlayer(); p.play(60,100); time.sleep(0.5); p.update(); p.close()"`
plays one piano note. Report whether you could check this. Its absence isn't a failure.

### Step 5: README
Append to `### Camera + Tap Strap together`:
```markdown
Taps on a key play a note through the computer's MIDI synth (on Windows, the built-in GS Wavetable Synth): key 1 is `--base-note` (default 60, middle C), and each key to the right is a semitone up. `--program N` picks the General MIDI instrument (0 piano, 24 guitar, 40 violin, 73 flute). Harder taps play louder. `--no-sound` only logs.

To try the full pipeline without a strap: calibrate a paper keyboard (C), then run with `--tap-demo` and hold your hand over the keys. The demo strap taps each finger about once a second.
```
Also add `mido` / `python-rtmidi` to nothing else. `requirements.txt` already covers setup.

## Test plan

Six unit tests on `sound.py` with a fake port (no audio device needed). Wiring is
covered by the full suite (import safety) and `--help`.

## Done criteria

- [ ] `<python> -m unittest tests.test_sound -v` → 6 `ok`
- [ ] Full suite `OK (skipped=1, expected failures=1)`
- [ ] `grep -n "mido==1.3.3\|python-rtmidi==1.5.8" requirements.txt` → 2 lines
- [ ] `--help` lists `--program`, `--base-note`, `--no-sound`
- [ ] Diff touches only `sound.py`, `tests/test_sound.py`, `phone_server.py`, `requirements.txt`, `README.md`

## STOP conditions

- `pip install` of the two pinned packages fails. Report the error; don't try other versions.
- `mido.open_output()` raises on this machine during the optional audible check. Report it
  (the app degrades to "Sound off"). That's not a blocker for the code, but say so.
- A change seems to be needed in `tap_view.py`.

## Maintenance notes

- `NOTE_S` is the decided fallback. Lift detection (finger leaves the paper) is the
  planned upgrade: replace `update()` timing with an explicit `note_off`.
- macOS has no built-in MIDI synth output. `mido.open_output()` will fail there, and the
  app prints "Sound off". A future option is a soft synth (e.g. FluidSynth) or a virtual port.
- Latency budget (METRICS target ≤50 ms tap→sound): the BLE strap, the 30 fps display loop
  (up to about 33 ms before events are drained), and the synth's own latency
  (the Windows GS synth is known to be slow). Measure before optimising.
