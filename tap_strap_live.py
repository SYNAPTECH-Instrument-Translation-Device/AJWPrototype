"""
Tap Strap 2 - live console tracker (template)

Setup:
    pip install tap-python-sdk
    Pair the strap with your computer first, then run:
    python tap_strap_live.py

Shows, refreshed in place ~10x per second:
    - Per-finger accelerometer x / y / z, magnitude, and a movement bar
    - Thumb IMU gyro and accel
    - Incoming sample rate

Press Ctrl+C to stop (the strap is returned to normal tap mode).

NOTE: SDK calls and payload layouts vary slightly between tap-python-sdk
versions. If something errors, compare with the raw_sensors example in the
TapSystems/TapPythonSDK repo. Spots most likely to need a tweak are marked.
"""

import asyncio
import math
import os
import time

from tapsdk import InputModeRaw, InputModeText, TapSDK, connect
from tapsdk.enumerations import (
    FingerAcclSensitivity,
    ImuAcclSensitivity,
    ImuGyroSensitivity,
)

# ----------------------------- CONFIG ---------------------------------------

FINGERS = ["thumb", "index", "middle", "ring", "pinky"]

RAW_MODE = InputModeRaw(
    scaled=True,                                   # mg / mdps instead of raw counts
    finger_accl_sens=FingerAcclSensitivity.G4,
    imu_gyro_sens=ImuGyroSensitivity.DPS250,
    imu_accl_sens=ImuAcclSensitivity.G4,
)

SENSITIVITY = [0, 0, 0]      # [finger accel, imu gyro, imu accel], levels 0-4
REFRESH_HZ = 10              # console redraw rate
BAR_WIDTH = 24
BAR_FULL_SCALE = 2000.0      # magnitude change that fills the bar (raw units)

# Raw counts by default. Fill in scale factors from the Tap docs for real units.
FINGER_ACCEL_SCALE = 1.0
IMU_ACCEL_SCALE = 1.0
IMU_GYRO_SCALE = 1.0

# ----------------------------- STATE ----------------------------------------

latest = {
    "accl": {f: (0.0, 0.0, 0.0) for f in FINGERS},
    "gyro": (0.0, 0.0, 0.0),
    "imu_accel": (0.0, 0.0, 0.0),
}
movement = {f: 0.0 for f in FINGERS}   # smoothed change in magnitude
last_mag = {f: 0.0 for f in FINGERS}
counts = {"accl": 0, "imu": 0}


def mag(x, y, z):
    return math.sqrt(x * x + y * y + z * z)


# ----------------------------- CALLBACK -------------------------------------

def on_raw_data(identifier, packets):
    for m in packets:
        p = m["payload"]
        if m["type"] == "accl":
            # 15 values: thumb(x,y,z) ... pinky(x,y,z)
            for i, f in enumerate(FINGERS):
                x, y, z = (v * FINGER_ACCEL_SCALE for v in p[i * 3:i * 3 + 3])
                latest["accl"][f] = (x, y, z)
                mg = mag(x, y, z)
                delta = abs(mg - last_mag[f])
                movement[f] = 0.8 * movement[f] + 0.2 * delta   # smoothing
                last_mag[f] = mg
            counts["accl"] += 1
        elif m["type"] == "imu":
            # 6 values: gyro xyz, then accel xyz (verify order for your version)
            latest["gyro"] = tuple(v * IMU_GYRO_SCALE for v in p[0:3])
            latest["imu_accel"] = tuple(v * IMU_ACCEL_SCALE for v in p[3:6])
            counts["imu"] += 1


# ----------------------------- DISPLAY --------------------------------------

def bar(value):
    filled = min(BAR_WIDTH, int(BAR_WIDTH * value / BAR_FULL_SCALE))
    return "█" * filled + "·" * (BAR_WIDTH - filled)


def render(rate_accl, rate_imu):
    lines = ["\033[H\033[J",   # cursor home + clear screen
             "TAP STRAP 2 - LIVE   (Ctrl+C to quit)",
             f"sample rate: accl {rate_accl:5.0f} Hz | imu {rate_imu:5.0f} Hz",
             "",
             f"{'finger':<8}{'x':>9}{'y':>9}{'z':>9}{'|a|':>9}   movement",
             "-" * 72]
    for f in FINGERS:
        x, y, z = latest["accl"][f]
        lines.append(f"{f:<8}{x:9.1f}{y:9.1f}{z:9.1f}{mag(x, y, z):9.1f}   "
                     f"{bar(movement[f])}")
    gx, gy, gz = latest["gyro"]
    ax, ay, az = latest["imu_accel"]
    lines += ["",
              "thumb IMU",
              f"  gyro  x={gx:9.1f} y={gy:9.1f} z={gz:9.1f}",
              f"  accel x={ax:9.1f} y={ay:9.1f} z={az:9.1f}"]
    print("\n".join(lines), flush=True)


async def display_loop():
    prev = dict(counts)
    prev_t = time.time()
    while True:
        await asyncio.sleep(1.0 / REFRESH_HZ)
        now = time.time()
        dt = now - prev_t
        rate_accl = (counts["accl"] - prev["accl"]) / dt
        rate_imu = (counts["imu"] - prev["imu"]) / dt
        prev, prev_t = dict(counts), now
        render(rate_accl, rate_imu)


# ------------------------------ MAIN ----------------------------------------

async def main():
    os.system("")  # enables ANSI escape codes in Windows terminals

    loop = asyncio.get_running_loop()
    tap = TapSDK(None, loop)   # use TapSDK() if your SDK version has no loop arg

    if not await tap.manager.is_connected():
        print("Connecting to Tap Strap...")
        await tap.manager.connect()

    await tap.register_raw_data_events(on_raw_data)
    await tap.set_input_mode(InputModeController())

    try:
        await display_loop()
    finally:
        await tap.set_input_mode(InputModeController())
        print("\nStopped. Strap returned to normal mode.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass