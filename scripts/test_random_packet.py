#!/usr/bin/env python3
import asyncio
from bleak import BleakClient

ADDR = "628A1160-0E76-D5A7-CCB6-5DA73EC96391"
CHAR_FEC7 = "0000fec7-0000-1000-8000-00805f9b34fb"
CHAR_FEC8 = "0000fec8-0000-1000-8000-00805f9b34fb"

async def main():
    async with BleakClient(ADDR, timeout=10.0) as client:
        def on_fec8(sender, data):
            print(f"[FEC8] {data.hex(' ')}")
        await client.start_notify(CHAR_FEC8, on_fec8)

        print("Reading FEC7 before wait...")
        v1 = await client.read_gatt_char(CHAR_FEC7)
        print("Before:", v1[:12].hex(' '))

        await asyncio.sleep(2.0)
        v2 = await client.read_gatt_char(CHAR_FEC7)
        print("After 2s:", v2[:12].hex(' '))

if __name__ == "__main__":
    asyncio.run(main())
