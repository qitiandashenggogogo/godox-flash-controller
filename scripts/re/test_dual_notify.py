#!/usr/bin/env python3
import asyncio
import time
from bleak import BleakClient

ADDR = "628A1160-0E76-D5A7-CCB6-5DA73EC96391"

async def main():
    print(f"Connecting to {ADDR}...")
    async with BleakClient(ADDR, timeout=10.0) as client:
        print("Connected.")

        def on_fff4(sender, data):
            print(f"[NOTIFY FFF4] {data.hex(' ')}")

        def on_fec8(sender, data):
            print(f"[NOTIFY FEC8] {data.hex(' ')}")

        try:
            await client.start_notify("0000fff4-0000-1000-8000-00805f9b34fb", on_fff4)
            print("Subscribed to FFF4.")
        except Exception as e:
            print("Failed to sub FFF4:", e)

        try:
            await client.start_notify("0000fec8-0000-1000-8000-00805f9b34fb", on_fec8)
            print("Subscribed to FEC8.")
        except Exception as e:
            print("Failed to sub FEC8:", e)

        # Test frame A 1/128
        # f0 a1 07 00 00 46 00 00 00 00 6e
        frame = bytes.fromhex("f0 a1 07 00 00 46 00 00 00 00 6e")
        print("Sending to FFF1 (with response=True)...")
        try:
            await client.write_gatt_char("0000fff1-0000-1000-8000-00805f9b34fb", frame, response=True)
            print("Write with response succeeded!")
        except Exception as e:
            print("Write with response failed:", e)
            print("Trying write without response...")
            await client.write_gatt_char("0000fff1-0000-1000-8000-00805f9b34fb", frame, response=False)
            print("Write without response sent.")

        await asyncio.sleep(2.0)

        # Also try test fire command:
        base_ms = 1483228800000
        diff_ms = int(time.time() * 1000) - base_ms
        test_cmd = f"{diff_ms},Test".encode("ascii")
        print(f"Sending test fire cmd '{test_cmd.decode()}' to FFF1...")
        await client.write_gatt_char("0000fff1-0000-1000-8000-00805f9b34fb", test_cmd, response=False)
        await asyncio.sleep(2.0)
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
