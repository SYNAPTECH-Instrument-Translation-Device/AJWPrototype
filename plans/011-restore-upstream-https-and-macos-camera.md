# Plan 011: Restore `--https`, the macOS camera backend and the camera-list retry that the merge lost

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat c6e260f..HEAD -- phone_server.py .gitignore`
> If it prints anything, compare the "Current state" excerpts below with the
> live code. On any mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `c6e260f`, 2026-11-06

## Why this matters

This repo was built by uploading files from the camera repo
(`SYNAPTECH-Instrument-Translation-Device/Instrument-Translation-Camera`). The
copy of `phone_server.py` that was uploaded predates that repo's latest commit,
`77d5cbd` ("Add --https flag for local HTTPS without ngrok"). Every other file
matches upstream byte for byte. Three things were lost:

1. **The `--https` flag.** The README's "Local HTTPS (no ngrok)" section still
   tells users to run `python phone_server.py --https`. Today that fails with
   `error: unrecognized arguments: --https`.
2. **The macOS camera backend.** `open_camera` always uses `cv2.CAP_DSHOW`, which is
   Windows only, so `--camera N` can't work on a Mac. The README even has a
   "macOS notes" section.
3. **The camera-list retry.** `--list-cameras` reads one frame. Continuity Camera
   (an iPhone used as a Mac webcam) needs up to about a second to send its
   first frame, so it gets skipped.

This plan puts those hunks back, exactly as upstream wrote them. It keeps
everything the local copy added since: the Tap Strap flags, and the Windows
`TerminateProcess` exit in the `finally` block.

## Current state

`phone_server.py` is the main app (Flask phone-page server or webcam input,
hand tracking, calibration, OpenCV windows). The `--tap*` flags and `TapMonitor`
are newer local additions and must stay.

`phone_server.py:1-6` (imports, note: no `import sys`):
```python
import argparse
import os
import threading
import time
import traceback
from pathlib import Path
```

`phone_server.py:159-172`:
```python
def open_camera(index):
    # DirectShow is the Windows backend that lists virtual webcams like Camo.
    # Use the camera's own resolution: asking Camo for 640x480 makes it send
    # all-black frames.
    return cv2.VideoCapture(index, cv2.CAP_DSHOW)


def list_cameras(max_index=6):
    for index in range(max_index):
        cap = open_camera(index)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        if ok:
            print(f"  camera {index}: {frame.shape[1]}x{frame.shape[0]}")
```

`phone_server.py:322-329`:
```python
def run_server():
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
```

`phone_server.py:338-350` (inside `if __name__ == "__main__":`):
```python
    parser.add_argument(
        "--list-cameras", action="store_true", help="print working camera indices and exit",
    )
    parser.add_argument("--tap", action="store_true", help="also stream a Tap Strap into a 'Tap Strap' window")
    parser.add_argument("--tap-demo", action="store_true", help="like --tap, but with synthetic data (no strap)")
    parser.add_argument("--tap-address", metavar="ADDR", help="Tap Strap BLE address (default: first found)")
    args = parser.parse_args()
    if args.list_cameras:
        list_cameras()
        raise SystemExit

    if args.camera is None:
        threading.Thread(target=run_server, daemon=True).start()
```

`.gitignore` ends with a bare `*.pem` line and no trailing newline.

**Conventions:** short `# Comment.` lines that explain why. Plain imperative
commit messages, no prefix (example from history: `Keep the processing thread
alive if one frame fails`).

## Commands you will need

Run from the repo root with the project venv (`.venv\Scripts\python.exe` on Windows).

| Purpose | Command | Expected on success |
|---|---|---|
| All tests | `.venv/Scripts/python.exe -m unittest discover -s tests -t .` | ends with `Ran 38 tests` and `OK (skipped=1, expected failures=1)` (M0 report text in the output is normal) |
| Flag check | `.venv/Scripts/python.exe phone_server.py --help` | lists `--https`, `--tap`, `--tap-demo`, `--tap-address` |

A fresh worktree has no `.venv`. If `.venv/Scripts/python.exe` is missing, use the
main checkout's interpreter at `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`
(same packages). Do not install anything.

## Scope

**In scope**: `phone_server.py` (only `import sys`, `open_camera`, `list_cameras`, `run_server`, the `--https` argument, and the `run_server` thread start), and `.gitignore`.

**Out of scope**: the `--tap*` flags, `TapMonitor`, the `finally:` block including
its Windows `TerminateProcess` code (a local fix that is NOT in upstream; keep
it), `README.md` (it already documents `--https`), and everything else.

## Git workflow

- Branch: whatever branch your worktree is on.
- One commit: `Restore --https, the macOS camera backend and the camera-list retry`
- Do not push.

## Steps

### Step 1: Add `import sys`
Insert `import sys` after `import os` (alphabetical stdlib block).

**Verify**: `grep -n "^import sys" phone_server.py` → one line.

### Step 2: Replace `open_camera` and `list_cameras` with upstream's versions

```python
def open_camera(index):
    # DirectShow is the Windows backend that lists virtual webcams like Camo;
    # AVFoundation is the macOS one (built-in camera, Continuity Camera, Camo).
    # Use the camera's own resolution: asking Camo for 640x480 makes it send
    # all-black frames.
    if sys.platform == "win32":
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if sys.platform == "darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def list_cameras(max_index=6):
    for index in range(max_index):
        cap = open_camera(index)
        opened = cap.isOpened()
        ok, frame = False, None
        if opened:
            # Continuity Camera (iPhone) can take a second to send its first frame.
            for _ in range(30):
                ok, frame = cap.read()
                if ok:
                    break
                time.sleep(0.1)
        cap.release()
        if ok:
            print(f"  camera {index}: {frame.shape[1]}x{frame.shape[0]}")
        elif opened:
            print(f"  camera {index}: opened but sent no frames")
```

**Verify**: `grep -n "CAP_AVFOUNDATION\|opened but sent no frames" phone_server.py` → 2 lines.

### Step 3: Replace `run_server` with upstream's version

```python
def run_server(use_https=False):
    # Phones only allow camera access over HTTPS. --https serves it directly
    # with a local self-signed certificate; otherwise put ngrok in front.
    ssl_context = None
    if use_https:
        cert, key = BASE_DIR / "cert.pem", BASE_DIR / "key.pem"
        if not (cert.exists() and key.exists()):
            print("cert.pem/key.pem not found; see 'Local HTTPS' in the README.")
            os._exit(1)
        ssl_context = (str(cert), str(key))
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context,
    )
```

### Step 4: Add the flag and pass it through
Directly after the `--list-cameras` argument (before `--tap`), add:
```python
    parser.add_argument(
        "--https", action="store_true",
        help="serve the phone page over HTTPS with cert.pem/key.pem (no ngrok needed)",
    )
```
Change `threading.Thread(target=run_server, daemon=True).start()` to
`threading.Thread(target=run_server, args=(args.https,), daemon=True).start()`.

**Verify**: `.venv/Scripts/python.exe phone_server.py --help` lists `--https` and all three `--tap*` flags. (This loads MediaPipe; a few seconds is normal.)

### Step 5: Restore the `.gitignore` comment
Replace the final `*.pem` line with these lines (end the file with a newline):
```
# Local HTTPS certificate (private key must never be committed)
*.pem
```
**Verify**: `tail -2 .gitignore` shows the comment line and `*.pem`.

### Step 6: Full suite
**Verify**: all tests → `Ran 38 tests`, `OK (skipped=1, expected failures=1)`.

## Test plan

No new unit tests. `run_server` starts a real server, and `open_camera` needs camera
hardware. The `--help` check covers the argument wiring, and the existing suite
covers regressions.

## Done criteria

- [ ] `grep -c "ssl_context" phone_server.py` prints `3`
- [ ] `grep -n "args=(args.https,)" phone_server.py` → one line
- [ ] `grep -n "TerminateProcess" phone_server.py` still finds the Windows exit code
- [ ] `--help` lists `--https --tap --tap-demo --tap-address`
- [ ] Full test suite: `Ran 38 tests`, `OK (skipped=1, expected failures=1)`
- [ ] `git diff --stat` touches only `phone_server.py` and `.gitignore`

## STOP conditions

- The excerpts above don't match the live code.
- `phone_server.py --help` fails to import (for example, `tap_view` is missing). Report it; don't stub it.
- Any step seems to need a README change.

## Maintenance notes

- The camera repo is now upstream of nothing. This repo is the master. If anyone
  keeps committing to `Instrument-Translation-Camera`, port those changes here, or
  this kind of loss happens again.
- `--https` and `--camera` are independent: `--https` only matters for the phone page.
