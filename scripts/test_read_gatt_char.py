#!/usr/bin/env python3
import asyncio
from bleak import BleakClient

ADDR = "628A1160-0E76-D5A7-CCB6-5DA73EC96391"
CHAR_FEC7 = "0000fec7-0000-1000-8000-00805f9b34fb"

async def main():
    async with BleakClient(ADDR, timeout=10.0) as client:
        try:
            mtu = await client.exchange_mtu(576)
            print("Negotiated MTU:", mtu)
        except Exception as e:
            print("MTU change failed:", e)

        try:
            val = await client.read_gatt_char(CHAR_FEC7)
            print("Read length:", len(val))
            if len(val) >= 36:
                for i in range(0, len(val), 36):
                    chunk = val[i:i+36]
                    if len(chunk) < 4: break
                    cmd = chunk[1]
                    if cmd == 0xA1 and chunk[0] == 0xF0:
                        group = chunk[3]
                        mode = chunk[4]
                        power = chunk[5]
                        lamp_level = chunk[6]
                        sound = chunk[7]
                        lamp_mode = chunk[8]
                        auto = chunk[9]
                        crc = chunk[10]
                        print(f"Chunk {i//36}: Group=0x{group:02X} Mode={mode} Power={power} LampLvl={lamp_level} Sound={sound} LampMode={lamp_mode} Auto={auto} CRC={crc:02X}")
        except Exception as e:
            print("Read error:", e)

if __name__ == "__main__":
    asyncio.run(main())
