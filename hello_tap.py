import asyncio
from tapsdk import InputModeController, connect


def on_tap(identifier, tapcode):
    code = tapcode[0] if isinstance(tapcode, (list, tuple)) else tapcode
    print(f"{identifier} tapped {code}")


def on_connect(sdk):
    print("Connected:", sdk)


async def main():
    sdk = await connect()
    if not hasattr(sdk, "set_input_mode"):
        raise SystemExit("This device uses set_feature. See the TapSDK2 tutorial.")

    sdk.register_connection_events(on_connect)
    sdk.register_tap_events(on_tap)

    await sdk.start()
    await sdk.set_input_mode(InputModeController())

    await asyncio.Event().wait()


asyncio.run(main())