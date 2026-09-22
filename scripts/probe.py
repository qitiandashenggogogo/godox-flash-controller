#!/usr/bin/env python3
"""
Godox X3 Pro Hardware Probe & Verification Script
Directly adjusts flash group power/mode and triggers test flashes over BLE.
"""

import asyncio
import argparse
import sys
import time
from datetime import datetime
from bleak import BleakClient, BleakScanner

SERVICE_FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_WRITE   = "0000fff1-0000-1000-8000-00805f9b34fb" # PHONE->BLE
CHAR_NOTIFY  = "0000fff4-0000-1000-8000-00805f9b34fb" # BLE->PHONE

CRC8_TABLE = [
    0x00, 0x5e, 0xbc, 0xe2, 0x61, 0x3f, 0xdd, 0x83, 0xc2, 0x9c, 0x7e, 0x20, 0xa3, 0xfd, 0x1f, 0x41,
    0x9d, 0xc3, 0x21, 0x7f, 0xfc, 0xa2, 0x40, 0x1e, 0x5f, 0x01, 0xe3, 0xbd, 0x3e, 0x60, 0x82, 0xdc,
    0x23, 0x7d, 0x9f, 0xc1, 0x42, 0x1c, 0xfe, 0xa0, 0xe1, 0xbf, 0x5d, 0x03, 0x80, 0xde, 0x3c, 0x62,
    0xbe, 0xe0, 0x02, 0x5c, 0xdf, 0x81, 0x63, 0x3d, 0x7c, 0x22, 0xc0, 0x9e, 0x1d, 0x43, 0xa1, 0xff,
    0x46, 0x18, 0xfa, 0xa4, 0x27, 0x79, 0x9b, 0xc5, 0x84, 0xda, 0x38, 0x66, 0xe5, 0xbb, 0x59, 0x07,
    0xdb, 0x85, 0x67, 0x39, 0xba, 0xe4, 0x06, 0x58, 0x19, 0x47, 0xa5, 0xfb, 0x78, 0x26, 0xc4, 0x9a,
    0x65, 0x3b, 0xd9, 0x87, 0x04, 0x5a, 0xb8, 0xe6, 0xa7, 0xf9, 0x1b, 0x45, 0xc6, 0x98, 0x7a, 0x24,
    0xf8, 0xa6, 0x44, 0x1a, 0x99, 0xc7, 0x25, 0x7b, 0x3a, 0x64, 0x86, 0xd8, 0x5b, 0x05, 0xe7, 0xb9,
    0x8c, 0xd2, 0x30, 0x6e, 0xed, 0xb3, 0x51, 0x0f, 0x4e, 0x10, 0xf2, 0xac, 0x2f, 0x71, 0x93, 0xcd,
    0x11, 0x4f, 0xad, 0xf3, 0x70, 0x2e, 0xcc, 0x92, 0xd3, 0x8d, 0x6f, 0x31, 0xb2, 0xec, 0x0e, 0x50,
    0xaf, 0xf1, 0x13, 0x4d, 0xce, 0x90, 0x72, 0x2c, 0x6d, 0x33, 0xd1, 0x8f, 0x0c, 0x52, 0xb0, 0xee,
    0x32, 0x6c, 0x8e, 0xd0, 0x53, 0x0d, 0xef, 0xb1, 0xf0, 0xae, 0x4c, 0x12, 0x91, 0xcf, 0x2d, 0x73,
    0xca, 0x94, 0x76, 0x28, 0xab, 0xf5, 0x17, 0x49, 0x08, 0x56, 0xb4, 0xea, 0x69, 0x37, 0xd5, 0x8b,
    0x57, 0x09, 0xeb, 0xb5, 0x36, 0x68, 0x8a, 0xd4, 0x95, 0xcb, 0x29, 0x77, 0xf4, 0xaa, 0x48, 0x16,
    0xe9, 0xb7, 0x55, 0x0b, 0x88, 0xd6, 0x34, 0x6a, 0x2b, 0x75, 0x97, 0xc9, 0x4a, 0x14, 0xf6, 0xa8,
    0x74, 0x2a, 0xc8, 0x96, 0x15, 0x4b, 0xa9, 0xf7, 0xb6, 0xe8, 0x0a, 0x54, 0xd7, 0x89, 0x6b, 0x35
]

POWER_MAP = {
    "1/1": 100,
    "1/1-0.3": 97,
    "1/2+0.7": 97,
    "1/1-0.7": 93,
    "1/2+0.3": 93,
    "1/2": 90,
    "1/2-0.3": 87,
    "1/4+0.7": 87,
    "1/2-0.7": 83,
    "1/4+0.3": 83,
    "1/4": 80,
    "1/4-0.3": 77,
    "1/8+0.7": 77,
    "1/4-0.7": 73,
    "1/8+0.3": 73,
    "1/8": 70,
    "1/8-0.3": 67,
    "1/16+0.7": 67,
    "1/8-0.7": 63,
    "1/16+0.3": 63,
    "1/16": 60,
    "1/16-0.3": 57,
    "1/32+0.7": 57,
    "1/16-0.7": 53,
    "1/32+0.3": 53,
    "1/32": 50,
    "1/32-0.3": 47,
    "1/64+0.7": 47,
    "1/32-0.7": 43,
    "1/64+0.3": 43,
    "1/64": 40,
    "1/64-0.3": 37,
    "1/128+0.7": 37,
    "1/64-0.7": 33,
    "1/128+0.3": 33,
    "1/128": 30,
    "1/128-0.3": 27,
    "1/256+0.7": 27,
    "1/128-0.7": 23,
    "1/256+0.3": 23,
    "1/256": 20,
}

GROUP_MAP = {
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4,
    "a": 0, "b": 1, "c": 2, "d": 3, "e": 4,
}

MODE_MAP = {
    "M": 0, "MANUAL": 0,
    "TTL": 1,
    "MULTI": 2,
    "OFF": 3,
}

def calc_crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = CRC8_TABLE[crc ^ b]
    return crc

def build_group_packet(group_letter="A", mode_str="M", power_str="1/128", sound=0, lamp_level=0, lamp_mode=0, auto_num=0):
    g_idx = GROUP_MAP.get(group_letter, 0)
    m_idx = MODE_MAP.get(mode_str.upper(), 0)
    dec_power = POWER_MAP.get(power_str, 30)
    power_byte = (100 - dec_power) & 0xFF
    if m_idx == 1:
        power_byte = 0x32
    payload = [
        0xF0,
        0xA1,
        0x07,
        g_idx,
        m_idx,
        power_byte,
        lamp_level,
        sound,
        lamp_mode,
        auto_num,
    ]
    crc = calc_crc8(bytes(payload))
    payload.append(crc)
    return bytes(payload)

def build_test_flash_packet():
    base_ms = 1483228800000
    now_ms = int(time.time() * 1000)
    diff_ms = now_ms - base_ms
    cmd = f"{diff_ms},Test"
    return cmd.encode("ascii")

async def find_x3pro():
    print("扫描附近的神牛 X3 Pro 设备 (查找 GDBH- 开头设备)...")
    devs = await BleakScanner.discover(timeout=4.0)
    for d in devs:
        name = d.name or ""
        if name.startswith("GDBH-") or any(k in name.lower() for k in ["x3", "godox"]):
            return d
    for d in devs:
        if d.address == "628A1160-0E76-D5A7-CCB6-5DA73EC96391":
            return d
    return None

async def main():
    parser = argparse.ArgumentParser(description="Godox X3 Pro BLE Probe")
    parser.add_argument("--address", type=str, default=None, help="BLE UUID or MAC address")
    parser.add_argument("--group", type=str, default="A", help="Group: A, B, C, D, E")
    parser.add_argument("--mode", type=str, default="M", help="Mode: M, TTL, OFF")
    parser.add_argument("--power", type=str, default="1/64", help="Power: 1/1, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64, 1/128, 1/256 (or +/- 0.3/0.7)")
    parser.add_argument("--test-fire", action="store_true", help="Trigger test flash")
    args = parser.parse_args()

    target_address = args.address
    if not target_address:
        dev = await find_x3pro()
        if not dev:
            print("未发现神牛 X3 Pro 设备，请检查设备是否开机并开启蓝牙。")
            sys.exit(1)
        target_address = dev.address
        print(f"找到设备: {dev.name} ({target_address}) RSSI: {dev.rssi} dBm")

    print(f"正在建立 BLE 连接至 {target_address} ...")
    async with BleakClient(target_address, timeout=12.0) as client:
        if not client.is_connected:
            print("连接失败！")
            sys.exit(1)
        print("BLE 连接建立成功！")

        rx_events = []
        def notify_handler(sender, data):
            rx_events.append(data)
            print(f"<- [X3 Pro 通知/回包] {data.hex(' ')}")

        try:
            await client.start_notify(CHAR_NOTIFY, notify_handler)
            print(f"已订阅通知通道 {CHAR_NOTIFY}")
        except Exception as e:
            print(f"订阅通知失败: {e}")

        if args.test_fire:
            pkt = build_test_flash_packet()
            print(f"-> [发送试闪指令] 字符串: {pkt.decode()} | Hex: {pkt.hex(' ')}")
            await client.write_gatt_char(CHAR_WRITE, pkt, response=False)
            print("试闪指令已发送，观察引闪器/闪光灯是否试闪！")
            await asyncio.sleep(1.0)
        else:
            pkt = build_group_packet(args.group, args.mode, args.power)
            print(f"-> [发送调参指令] 组别: {args.group}, 模式: {args.mode}, 功率: {args.power}")
            print(f"   Hex 数据帧: {pkt.hex(' ')} (共 {len(pkt)} 字节)")
            await client.write_gatt_char(CHAR_WRITE, pkt, response=False)
            print("调参指令已发送！等待引闪器响应...")
            await asyncio.sleep(1.0)

        print("\n验证操作完成。")

if __name__ == "__main__":
    asyncio.run(main())
