#!/usr/bin/env python3
import asyncio
from bleak import BleakScanner

async def check():
    print("扫描 6 秒捕获全部广播包元数据...")
    devs = await BleakScanner.discover(timeout=6.0, return_adv=True)
    for addr, (d, adv) in devs.items():
        name = d.name or adv.local_name or "未命名的广播"
        print(f"[{name}] {addr} (RSSI: {adv.rssi})")
        if adv.service_uuids:
            print(f"   Service UUIDs: {adv.service_uuids}")
        if adv.manufacturer_data:
            m_str = {f"0x{k:04x}": v.hex() for k, v in adv.manufacturer_data.items()}
            print(f"   Manufacturer Data: {m_str}")
        if adv.service_data:
            s_str = {k: v.hex() for k, v in adv.service_data.items()}
            print(f"   Service Data: {s_str}")

if __name__ == "__main__":
    asyncio.run(check())
