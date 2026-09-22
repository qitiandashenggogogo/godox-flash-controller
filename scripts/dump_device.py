#!/usr/bin/env python3
"""
Godox X3 Pro BLE GATT Explorer & Inspector
Connects to the specified BLE device (by address/UUID or auto-detected Godox device),
enumerates all GATT services, characteristics, descriptors, and readable values.
"""

import asyncio
import sys
from datetime import datetime
from bleak import BleakClient, BleakScanner


async def find_godox_device():
    print("正在搜索 Godox / X3 / GDBH 设备...")
    devices = await BleakScanner.discover(timeout=5.0)
    candidates = []
    for d in devices:
        name = d.name or ""
        if any(k in name.lower() for k in ["godox", "x3", "flash", "trigger", "gdbh"]):
            candidates.append(d)
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.rssi or -999, reverse=True)
    return candidates[0]


async def dump_gatt(address: str = None):
    target_address = address
    if not target_address:
        dev = await find_godox_device()
        if not dev:
            print("未自动发现 Godox / X3 设备。请手动传入设备地址/UUID：")
            print("  python scripts/dump_device.py <UUID_OR_MAC>")
            return
        target_address = dev.address
        print(f"已选定目标设备: {dev.name} ({target_address})")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在连接 {target_address} ...")
    async with BleakClient(target_address, timeout=15.0) as client:
        connected = client.is_connected
        print(f"连接状态: {'成功' if connected else '失败'}")
        if not connected:
            return

        print("=" * 80)
        print("GATT 服务与特征值清单：")
        print("=" * 80)

        for service in client.services:
            print(f"[Service] {service.description} ({service.uuid})")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"  └─ [Char] {char.description} ({char.uuid}) | 属性: [{props}]")

                if "read" in char.properties:
                    try:
                        val = await client.read_gatt_char(char.uuid)
                        try:
                            val_str = val.decode("utf-8", errors="ignore").strip()
                            print(f"      值 (文本): '{val_str}'")
                        except Exception:
                            pass
                        print("      值 (十六进制): " + val.hex(" "))
                    except Exception as e:
                        print(f"      读取失败: {e}")

                for desc in char.descriptors:
                    print(f"      └─ [Desc] {desc.description} ({desc.uuid})")
                    try:
                        dval = await client.read_gatt_descriptor(desc.handle)
                        print("          描述符值: " + dval.hex(" "))
                    except Exception:
                        pass

        print("=" * 80)
        print("GATT 枚举完成。")


if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(dump_gatt(addr))
