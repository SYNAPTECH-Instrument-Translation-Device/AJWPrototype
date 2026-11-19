# Instrument Translation

A computer-vision project exploring a virtual piano played on paper using a phone camera, OpenCV, and MediaPipe.

## Requirements

- Python 3.12
- `pip`
- A phone with a camera and browser
- [ngrok](https://ngrok.com/download) for HTTPS camera access

## Setup

Clone the repository:

```powershell
git clone <repository-url>
cd Instrument-Translation
```

Make sure Python 3.12 is selected as the project interpreter. In VS Code, use
**Python: Select Interpreter** and choose the Python 3.12 interpreter (or the
project's `.venv` after creating it). In PowerShell, use `py -3.12` to create
the environment with Python 3.12 even if the `python` command points to a
different installation.

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

After activation, confirm the project environment is being used:

```powershell
python -c "import sys; print(sys.executable)"
```

The printed path should point to `.venv\Scripts\python.exe`.

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

The MediaPipe Hand Landmarker model is included in `models/hand_landmarker.task`.

Install and configure ngrok using its [official documentation](https://ngrok.com/docs/).

## Running

1. Start the server:

   ```powershell
   python phone_server.py
   ```

2. Open a separate terminal and start the HTTPS tunnel:

   ```powershell
   ngrok http 5000
   ```

3. On your phone, open the HTTPS forwarding URL displayed by ngrok plus the
   `/?token=...` part the server printed at startup (e.g.
   `https://abc.ngrok-free.app/?token=XYZ`). Without the token the server rejects
   frames (403). The token changes every start; set `PHONE_TOKEN` to keep one fixed.
4. Select **Start Camera** and allow camera access.
5. Press `Q` in the OpenCV window to stop the server.

Keep both the Python server and ngrok running while using the camera.

## Controls

### Keys (click the Phone Camera Feed window first)

| Key | What it does | When it works |
|---|---|---|
| `C` | Calibrate the paper keyboard. Keep your hands out of view for about a second. | Always |
| `S` | Save the current camera frame to `samples/` (for debugging calibration). | Always |
| `V` | Start/stop saving every processed frame to `recordings/frames_<time>/`. Each file is named by its wall-clock time (`host_time_s` in the tap logs), so you can pull up the frames around any tap. About 50 MB per minute. | Always |
| `T` | Tap calibration: rest your hand 3 s, then tap each finger 5 times on the beeps. Saves `calibration/tap_profile.json`. | With `--tap` or `--tap-demo` |
| `G` | Guided accuracy session: tap the named finger/key on each beep. Saves `recordings/session_<time>_*.csv`. | With `--session` and a strap, after `C` |
| `Q` | Quit. Puts the strap back into normal typing mode and disconnects; wait for the confirmation line (see Closing the strap safely). `Ctrl+C` once in the terminal also works. | Always |

### Windows

| Window | What it shows |
|---|---|
| Phone Camera Feed | Camera image, detected paper keys (numbered), hand landmarks, status lines. Keys under a fingertip turn yellow. |
| Calibration settings | **Sens** slider: raise if key lines are missed, lower if shadows become keys. **Key** slider: lower for small drawings. |
| Tap Strap | One bar per finger (red = tap-sized spike), the key the camera sees each finger on, thumb gyro. Only with `--tap`/`--tap-demo`. |

### Command-line options (`python phone_server.py ...`)

| Option | What it does |
|---|---|
| `--camera N` | Use local camera N (e.g. the iPhone through Camo) instead of the phone web page. |
| `--list-cameras` | Print working camera numbers and exit. |
| `--https` | Serve the phone page over HTTPS with `cert.pem`/`key.pem` (no ngrok). |
| `--tap` | Connect the Tap Strap (paired in Windows Bluetooth, Developer mode on). |
| `--tap-demo` | Fake strap data, no hardware. |
| `--tap-address ADDR` | Connect to a specific strap. |
| `--tap-hand left\|right` | Which hand wears the strap (default `right`). |
| `--program N` | MIDI instrument: 0 piano, 24 guitar, 40 violin, 73 flute. |
| `--base-note N` | MIDI note of key 1 (default 60 = middle C). |
| `--no-sound` | Log taps without playing notes. |
| `--session` | Enable `G` (guided accuracy session). |

Typical run: `python phone_server.py --camera 1 --tap`, press `C`, then `T` once per strap fit, then play.

## Local HTTPS (no ngrok)

Phone browsers only allow camera access over HTTPS. Instead of ngrok, the server
can serve HTTPS itself on your local network using a self-signed certificate.
The phone and computer must be on the same Wi-Fi, and the network must let devices
reach each other (many school and public networks block this).

1. Create a certificate once, from the repo root (on macOS `openssl` is built in;
   on Windows run it from Git Bash):

   ```bash
   openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
     -keyout key.pem -out cert.pem -subj "/CN=localhost"
   ```

   `*.pem` is gitignored. Never commit `key.pem`.

2. Start the server with `--https`:

   ```bash
   python phone_server.py --https
   ```

3. Find your computer's local IP address (macOS: `ipconfig getifaddr en0`;
   Windows: `ipconfig`, look for the IPv4 address) and open
   `https://<that-ip>:5000/?token=...` (token as printed by the server) on your phone.
4. The phone warns that the certificate isn't trusted. Continue anyway
   (Safari: **Show Details → visit this website**; Chrome: **Advanced → Proceed**),
   then select **Start Camera**.

The certificate expires after 365 days; rerun step 1 to make a new one.

### macOS notes

- Activate the environment with `source .venv/bin/activate` (not `Activate.ps1`),
  or run `.venv/bin/python phone_server.py --https` directly.
- If port 5000 is already in use, turn off **AirPlay Receiver** in
  **System Settings → General → AirDrop & Handoff**.
- `No module named cv2` means the system Python is running instead of the `.venv`.

## Project Structure

- `phone_server.py` — Main app: phone-page server or `--camera` webcam input, hand tracking, calibration, key overlay and sliders.
- `phone_camera.html`, `phone_camera.css`, `phone_camera.js` — Phone camera page that sends frames to the server.
- `calibration.py` — Finds the paper, flattens it, detects and numbers the keys, and saves/loads `calibration/`.
- `calibrate_image.py` — Writes a `_debug.png` for one saved frame (see Calibration).
- `paper_detector.py` — White-paper mask used by calibration and the live overlay.
- `tapstrap/` — Tap Strap 2 raw-sensor decoding (`decode.py`) and Bluetooth streaming (`stream.py`).
- `tap_view.py` — Tap Strap window shown by `phone_server.py --tap` / `--tap-demo`.
- `stream_raw.py`, `live_plot.py` — Live Tap Strap readout and plot (`--demo` works without a strap).
- `recording.py` — Shared strap CSV recorder and cue click (used by the app, `stream_raw.py` and `m0_record.py`).
- `m0_record.py`, `m0_analyze.py` — Milestone 0 recording sessions and reports (see Tap Strap (M0)).
- `frames_analyze.py` — Fingertip-to-key check on frames recorded with V (see Checking hand tracking).
- `models/hand_landmarker.task` — MediaPipe hand-tracking model.
- `tests/` — Unit tests; `tests/fixtures/` holds real camera frames used as regression tests.
- `plans/` — Implementation plans and their status.
- `METRICS.md` — Measured and synthetic results over time.
- `requirements.txt` — Python dependencies.

## Using the iPhone over USB (no ngrok)

Install **Camo Camera** (iPhone) and **Camo Studio** (Windows, camo.com), plug in the cable, and open both. Then:

```powershell
python phone_server.py --list-cameras    # find Camo's index
python phone_server.py --camera 1        # use that index
```

The free Camo tier (720p) is enough. Without `--camera`, the phone page + ngrok setup above still works.

Tips:
- Use the iPhone's **1×** lens, not 0.5× (the ultra-wide is softer, bends the paper's edges, and makes keys tiny).
- Keep Camo Camera open and the phone unlocked (Auto-Lock → Never while testing); Camo Studio can stay minimised.
- Run one server at a time, from the project `.venv` (select it as VS Code's interpreter).
- Webcam frames are shrunk to 640 px wide for speed. The second status line shows `rx` (frames arriving), `proc` (ms to process one) and `age` (ms from arrival to ready).
- Plug the laptop in and use the **Best performance** power mode: on low battery the CPU throttles and `proc` can jump past 100 ms.
- Q or Ctrl+C quits cleanly.

## Calibration

The template is black solid boxes or black outlines on white Letter paper, landscape.

- Press `C` with your hands out of view; regions are numbered left to right.
- Press `S` to save the current frame to `samples/`.
- `python calibrate_image.py samples/<file>.jpg` writes a `_debug.png` showing the
  flattened paper, the ink mask and the numbered regions.
- The **Calibration settings** window has **Sens** (sensitivity) (raise it if lines are missed, lower it if
  paper texture or shadows become regions) and **Key** (min black key) (lower it for small drawings).
  Changes re-detect instantly.

## Tap Strap (M0)

`tapstrap/` reads raw finger accelerometer data from a Tap Strap 2 (`python stream_raw.py --demo` for a live readout without a strap).

- `python m0_record.py` runs a prompted session (clicks cue each tap) and writes `recordings/m0_<time>_{fingers,imu,cues}.csv`; the columns are documented in the script. Add `--demo` to try it without a strap.
- `python m0_analyze.py recordings/m0_<time>` writes `_report.txt` and `_report.png` (stream health, per-finger separability, crosstalk, a simple detector's precision/recall).

### Camera + Tap Strap together

```powershell
python phone_server.py --camera 1 --tap        # real strap (paired, Developer mode on)
python phone_server.py --camera 1 --tap-demo   # synthetic strap data
```

A **Tap Strap** window opens next to the camera feed. Each finger has a live accelerometer bar (red = tap-sized spike) and, on the right, the key the camera sees that fingertip on. If the strap can't connect, the window says so and the camera keeps running. Q puts the strap back into normal typing mode.

**Closing the strap safely.** Every script closes the strap the same way (`tapstrap.close_tap`): stop the 10 s mode refresh, write Text mode, wait 0.5 s for the firmware to apply it, then disconnect. Skipping the disconnect leaves Windows holding a stale Bluetooth session that the next connect collides with. Writing your own strap code? See [TAP_CLOSING.md](TAP_CLOSING.md). To quit:

1. Press Q (or Ctrl+C once). Once `Closing Tap Strap...` appears, further Ctrl+C presses are ignored until the close finishes. Don't close the terminal window: that still kills the process mid-close.
2. Wait for `Tap Strap back in typing mode and disconnected.`
3. Only then switch the strap off or start another run. Run one strap program at a time.
4. If it prints a WARNING instead, switch the strap off and on (or toggle Windows Bluetooth) before reconnecting.

`--tap-hand left|right` (default `right`) says which hand wears the strap, so the key column follows that hand. Keys under both hands are highlighted. If the column follows your other hand, switch the value: hand labels assume an unmirrored camera image, which hasn't been checked with every camera yet.

Each strap tap is logged to `recordings/taps_<time>.csv` (time, finger, the key the camera saw that finger on, peak g). On quit the app prints how many taps landed on a key.

Taps on a key play a note through the computer's MIDI synth (on Windows, the built-in GS Wavetable Synth): key 1 is `--base-note` (default 60, middle C), and each key to the right is a semitone up. `--program N` picks the General MIDI instrument (0 piano, 24 guitar, 40 violin, 73 flute). Harder taps play louder. `--no-sound` only logs.

To try the full pipeline without a strap: calibrate a paper keyboard (C), then run with `--tap-demo` and hold your hand over the keys. The demo strap taps each finger about once a second.

**Measuring accuracy.** Run with `--session`, calibrate (C), then press G. Follow the on-screen cues and tap on each beep: 40 single taps on named keys, 10 chords, then 20 s of moving your hand without tapping. Then run `python session_analyze.py recordings/session_<time>` for detection, right-key, crosstalk, chord and false-tap rates. Add the headline numbers to METRICS.md.

**Checking hand tracking.** To see whether MediaPipe puts your fingertips on the right keys, press V to start recording frames, play, then press V again. Each frame is saved to `recordings/frames_<time>/`, named by its wall-clock time, the same as `host_time_s` in the tap logs. To check a tap, find the frames whose names are closest to its time. Then run `python frames_analyze.py recordings/frames_<time>`. It prints the key under each fingertip for every frame, e.g. `I:0->17` when the app's correction moved a folded-back tip onto key 17, and a total of fingertips on a key. It also writes `recordings/frames_<time>_overlay/` with keys in green, MediaPipe's tips in red and corrected tips in cyan. It uses your saved calibration, so don't move the camera between calibrating and recording.

**Tap calibration (T).** With the strap on, press T. Rest your hand still on the paper for 3 s, then tap each finger 5 times on the beeps. The app saves per-finger tap thresholds (and noise floor) to `calibration/tap_profile.json` and loads it on every start. Redo it if you re-seat the strap. Run a guided session (G) before and after to see the difference.

## Tests

Run the unit tests from the repo root:

```
python -m unittest discover -s tests -t .
```

## Notes

- Phone camera access requires HTTPS; use the ngrok forwarding URL or `--https`
  (see [Local HTTPS](#local-https-no-ngrok)).
- Do not commit `.venv/`, `*.pem` certificate files, authentication tokens, or other secrets.