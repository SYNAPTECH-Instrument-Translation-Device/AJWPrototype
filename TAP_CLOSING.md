# Closing the Tap Strap safely

Skipping a step can leave the strap stuck in raw mode, where it doesn't type. On Windows it can also leave a stale Bluetooth session that breaks the next connect.

## The order

1. **Stop the 10 s mode refresh** (`sdk.input_mode_refresh.stop()`). Otherwise it can re-send raw mode after you leave it.
2. **Write Text mode**, `03 0C 00 00`. Tap's BLE docs call this the "exit controller mode" packet and say to send it when the app closes.
3. **Wait about 0.5 s.** The firmware applies mode commands slowly while raw data streams.
4. **Disconnect** (`sdk.client.disconnect()`). Windows keeps the GATT session alive past process exit unless you do.

Run every step even if an earlier one fails, and give each Bluetooth step a timeout so none can hang.

## Code to include

**Using `TapRawStream`** (recommended): `async with` closes it for you. A failed connect also cleans up.

```python
from tapstrap import SensorConfig, TapRawStream

async with TapRawStream(SensorConfig()) as tap:
    async for sample in tap.samples():
        ...
```

**Using the raw `tapsdk` directly:** put everything after connecting in `try`, and call `close_tap` in `finally`.

```python
import asyncio
from tapsdk import connect
from tapstrap import close_tap

async def main():
    sdk = await connect()
    try:
        await sdk.start()
        await sdk.set_input_mode(...)   # raw or controller mode
        ...                             # your loop
    finally:
        ok = await close_tap(sdk)       # refresh off -> Text -> wait -> disconnect
        if not ok:
            print("WARNING: Text mode not confirmed; power-cycle the strap.")

try:
    asyncio.run(main())                 # Ctrl+C cancels main(), so finally still runs
except KeyboardInterrupt:
    pass
```

**In a background thread** (as `tap_view.TapMonitor` does): before the process exits, signal the thread and **join it**. Never kill the process (`os._exit`, `TerminateProcess`) while the close is still running. `TapMonitor.stop()` returns `True` once the strap is back in Text mode and disconnected.

## Don'ts

- Don't call `sdk.set_input_mode(InputModeText())` as your only cleanup. It restarts the refresh task and never disconnects.
- Don't close the terminal window while the strap is closing. A second Ctrl+C is safe: `close_tap` ignores Ctrl+C while it runs (on the main thread), and `phone_server.py` ignores it for its whole shutdown. If your own script joins a strap thread before exiting, add `signal.signal(signal.SIGINT, signal.SIG_IGN)` at the start of that shutdown.
- Don't run two strap programs at once. Their mode commands fight each other.
- If a close fails, switch the strap off and on (or toggle Windows Bluetooth) before reconnecting.

Sources: Tap BLE API Documentation 1.0.1 (Controller mode section) and tap-python-sdk `docs/windows-ble-connect-notes.md`.
