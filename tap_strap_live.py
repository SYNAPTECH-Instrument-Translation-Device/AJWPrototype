"""
Tap Strap 2 - live console tracker (template, tap-python-sdk 0.9+ API)

Setup:
    pip install tap-python-sdk          # needs Python 3.10+
    1. Pair the strap in your OS Bluetooth settings first (the SDK doesn't scan
       for unpaired devices).
    2. Enable "Developer mode" in the TapManager phone app (required for raw mode).
    3. python tap_strap_live.py

Shows, refreshed in place ~10x per second:
    - Per-finger accelerometer x / y / z, magnitude, and a movement bar
    - Thumb IMU gyro and accel
    - Incoming sample rate

Units (because InputModeRaw(scaled=True)):
    accelerometers -> mg,  gyro -> mdps

Ctrl+C stops; the strap is returned to normal Text mode (types as usual).

If something errors, check the SDK docs: https://tapwithus.github.io/tap-python-sdk/
Spots most likely to need a tweak are marked with "VERIFY".
"""

import asyncio
import math
import os
import time

from tapsdk import (
    InputModeRaw,
    InputModeText,
    TapSDK,
    connect,
)
from tapsdk.enumerations import (
    FingerAcclSensitivity,
    ImuAcclSensitivity,
    ImuGyroSensitivity,
)

# ----------------------------- CONFIG ---------------------------------------

FINGERS = ["thumb", "index", "middle", "ring", "pinky"]
REFRESH_HZ = 10              # console redraw rate
BAR_WIDTH = 24
BAR_FULL_SCALE = 2000.0      # change in magnitude (mg) that fills the bar

# Dynamic range. Other members are listed in tapsdk.enumerations.
RAW_MODE = InputModeRaw(
    scaled=True,                                   # mg / mdps instead of raw counts
    finger_accl_sens=FingerAcclSensitivity.G4,
    imu_gyro_sens=ImuGyroSensitivity.DPS250,
    imu_accl_sens=ImuAcclSensitivity.G4,
)

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
    for pkt in packets:
        p = pkt["payload"]
        if pkt["type"] == "accl":
            # 15 values: thumb(x,y,z) ... pinky(x,y,z)
            for i, f in enumerate(FINGERS):
                x, y, z = p[i * 3:i * 3 + 3]
                latest["accl"][f] = (x, y, z)
                m = mag(x, y, z)
                movement[f] = 0.8 * movement[f] + 0.2 * abs(m - last_mag[f])
                last_mag[f] = m
            counts["accl"] += 1
        elif pkt["type"] == "imu":
            # VERIFY: 6 values, gyro xyz then accel xyz
            latest["gyro"] = tuple(p[0:3])
            latest["imu_accel"] = tuple(p[3:6])
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
             f"{'finger':<8}{'x (mg)':>10}{'y (mg)':>10}{'z (mg)':>10}{'|a| mg':>10}   movement",
             "-" * 74]
    for f in FINGERS:
        x, y, z = latest["accl"][f]
        lines.append(f"{f:<8}{x:10.1f}{y:10.1f}{z:10.1f}{mag(x, y, z):10.1f}   "
                     f"{bar(movement[f])}")
    gx, gy, gz = latest["gyro"]
    ax, ay, az = latest["imu_accel"]
    lines += ["",
              "thumb IMU",
              f"  gyro  (mdps) x={gx:10.1f} y={gy:10.1f} z={gz:10.1f}",
              f"  accel (mg)   x={ax:10.1f} y={ay:10.1f} z={az:10.1f}"]
    print("\n".join(lines), flush=True)


async def display_loop():
    prev, prev_t = dict(counts), time.time()
    while True:
        await asyncio.sleep(1.0 / REFRESH_HZ)
        now = time.time()
        dt = now - prev_t
        render((counts["accl"] - prev["accl"]) / dt,
               (counts["imu"] - prev["imu"]) / dt)
        prev, prev_t = dict(counts), now


# ------------------------------ MAIN ----------------------------------------

async def main():
    os.system("")  # enables ANSI escape codes in Windows terminals

    print("Connecting to Tap Strap...")
    sdk = await connect()          # auto-detects protocol; returns TapSDK or TapSDK2
    if not isinstance(sdk, TapSDK):
        raise SystemExit(
            "Connected device uses the v2 protocol (TapSDK2), which has no input "
            "modes. Use its DeviceFeatures / IMU raw API instead - see the v2 docs."
        )

    sdk.register_raw_data_events(on_raw_data)   # register callbacks first...
    await sdk.start()                           # ...then arm notifications
    await sdk.set_input_mode(RAW_MODE)

    try:
        await display_loop()
    finally:
        await sdk.set_input_mode(InputModeText())   # back to normal typing
        print("\nStopped. Strap returned to normal mode.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass