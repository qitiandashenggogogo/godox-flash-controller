#!/usr/bin/env python3
"""
Godox X3 Pro BLE Scanner
Scans for nearby BLE devices, recording advertised names, UUIDs, RSSI,
service UUIDs, and manufacturer data.
"""

import asyncio
import sys
from datetime import datetime
from bleak import BleakScanner


async def scan(duration: float = 10.0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始 BLE 扫描 (持续 {duration} 秒)...")
    print("提示：请确保神牛 X3 Pro 引闪器已开机，并已在设置菜单中开启蓝牙(Bluetooth: ON)。\n")

    discovered = []

    def detection_callback(device, advertisement_data):
        # Save for later summary
        discovered.append((device, advertisement_data))
        name = advertisement_data.local_name or device.name or "未知设备"
        is_candidate = any(
            keyword in name.lower()
            for keyword in ["godox", "x3", "flash", "trigger", "mesh"]
        )
        prefix = ">>> [候选目标] " if is_candidate else "    "
        print(
            f"{prefix}{name:25s} | 地址/UUID: {device.address} | RSSI: {advertisement_data.rssi} dBm"
        )

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 扫描结束，共发现 {len(discovered)} 个设备广播。")
    print("=" * 80)

    godox_candidates = []
    for dev, adv in discovered:
        name = adv.local_name or dev.name or ""
        is_match = False
        if any(k in name.lower() for k in ["godox", "x3", "flash", "trigger"]):
            is_match = True
        if is_match:
            godox_candidates.append((dev, adv))

    if godox_candidates:
        print(f"找到 {len(godox_candidates)} 个高疑似 Godox / X3 设备：")
        for dev, adv in godox_candidates:
            print(f"- 名称: {adv.local_name or dev.name}")
            print(f"  地址: {dev.address}")
            print(f"  RSSI: {adv.rssi} dBm")
            print(f"  服务 UUIDs: {adv.service_uuids}")
            print(f"  厂商数据: {adv.manufacturer_data}")
            print(f"  服务数据: {adv.service_data}")
    else:
        print("未在名称中发现含 Godox / X3 / Flash 的设备。")
        print("若设备在附近：")
        print("1. 确认 X3 Pro 屏幕上蓝牙图标是否开启并处于广播状态；")
        print("2. 确认 X3 Pro 是否已被手机 Godox Flash App 占用连接；")
        print("3. 可以查阅上述所有扫描到的设备列表，比对信号最强的设备。")


if __name__ == "__main__":
    duration = 10.0
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
        except ValueError:
            pass
    asyncio.run(scan(duration))
