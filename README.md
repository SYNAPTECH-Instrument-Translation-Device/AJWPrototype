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

3. Open the HTTPS forwarding URL displayed by ngrok on your phone.
4. Select **Start Camera** and allow camera access.
5. Press `Q` in the OpenCV window to stop the server.

Keep both the Python server and ngrok running while using the camera.

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
   `https://<that-ip>:5000` on your phone.
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
- `debug.py` — Old standalone viewer: paper-detection mask from webcam 0. Not used by the app.
- `tapstrap/` — Tap Strap 2 raw-sensor decoding (`decode.py`) and Bluetooth streaming (`stream.py`).
- `tap_view.py` — Tap Strap window shown by `phone_server.py --tap` / `--tap-demo`.
- `tap_strap_live.py`, `hello_tap.py` — Standalone strap scripts from the old demo repo (console readout, tap codes). Not used by the app.
- `stream_raw.py`, `live_plot.py` — Live Tap Strap readout and plot (`--demo` works without a strap).
- `m0_record.py`, `m0_analyze.py` — Milestone 0 recording sessions and reports (see Tap Strap (M0)).
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

## Tests

Run the unit tests from the repo root:

```
python -m unittest discover -s tests -t .
```

## Notes

- Phone camera access requires HTTPS; use the ngrok forwarding URL or `--https`
  (see [Local HTTPS](#local-https-no-ngrok)).
- Do not commit `.venv/`, `*.pem` certificate files, authentication tokens, or other secrets.