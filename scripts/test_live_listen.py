#!/usr/bin/env python3
import asyncio
import time
from bleak import BleakClient

ADDR = "628A1160-0E76-D5A7-CCB6-5DA73EC96391"
CHAR_FEC7 = "0000fec7-0000-1000-8000-00805f9b34fb"
CHAR_FEC8 = "0000fec8-0000-1000-8000-00805f9b34fb"
CHAR_FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
CHAR_FFF4 = "0000fff4-0000-1000-8000-00805f9b34fb"

async def main():
    print(f"Connecting to {ADDR}...")
    async with BleakClient(ADDR, timeout=10.0) as client:
        print("Connected.")

        def on_fec8(sender, data):
            print(f"[FEC8 Notification] {len(data)} bytes: {data.hex(' ')}")

        def on_fff4(sender, data):
            print(f"[FFF4 Notification] {len(data)} bytes: {data.hex(' ')}")

        await client.start_notify(CHAR_FEC8, on_fec8)
        await client.start_notify(CHAR_FFF4, on_fff4)
        print("Subscribed to FEC8 and FFF4.")

        # Try reading FEC7, FEC8, FFF1, FFF4 to see if they hold current state
        for name, ch in [("FEC7", CHAR_FEC7), ("FFF1", CHAR_FFF1)]:
            try:
                val = await client.read_gatt_char(ch)
                print(f"[Read {name}] {len(val)} bytes: {val.hex(' ')}")
            except Exception as e:
                print(f"[Read {name} failed]: {e}")

        # Try query frames:
        # Does X3 Pro reply to a status request?
        # In Godox, let's test: F0 FD ... (Status request, as in ha-godox-mesh) or F0 A0 query
        query_frames = [
            bytes.fromhex("f0 fd 01 01 00 00 00 00 00 00 00"), # FD query
            bytes.fromhex("f0 a2 00 00 00 00 00 00 00 00 00"), # A2 query
            bytes.fromhex("f0 e0 00 00 00 00 00 00 00 00 00"), # E0 query
            bytes.fromhex("f0 a0 00 00 00 00 00 00 00 00 00"), # A0 query
        ]
        for qf in query_frames:
            print(f"Testing query frame: {qf.hex(' ')}")
            try:
                await client.write_gatt_char(CHAR_FEC7, qf, response=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                print("Write query failed:", e)

        print("Waiting 5 seconds for any notifications...")
        await asyncio.sleep(5.0)

if __name__ == "__main__":
    asyncio.run(main())
