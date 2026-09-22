#!/usr/bin/env python3
import asyncio
from bleak import BleakClient

ADDR = "628A1160-0E76-D5A7-CCB6-5DA73EC96391"
CHAR_FEC7 = "0000fec7-0000-1000-8000-00805f9b34fb"

async def main():
    async with BleakClient(ADDR, timeout=10.0) as client:
        try:
            val = await client.read_gatt_char(CHAR_FEC7)
            print("Last 36 bytes:", val[:36].hex(' '))
            print("Full packet count:", len(val) / 36)
            for i in range(0, len(val), 36):
                chunk = val[i:i+36]
                if chunk[0] == 0xF0:
                    cmd = chunk[1]
                    group = chunk[3]
                    mode = chunk[4]
                    power = chunk[5]
                    lamp_level = chunk[6]
                    lamp_mode = chunk[8]
                    print(f"Chunk {i//36}: CMD=0x{cmd:02X} Group=0x{group:02X} Mode={mode} Power={power} LampLvl={lamp_level} LampMode={lamp_mode}")
        except Exception as e:
            print("Read error:", e)

if __name__ == "__main__":
    asyncio.run(main())
