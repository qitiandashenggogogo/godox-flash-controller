#!/usr/bin/env python3
"""
被动监听实验：连接 X3 Pro，不写任何命令，只听 12 秒。
目的（第一性原则验证）：
  1. 引闪器是否周期性广播自身状态？
  2. 在实体引闪器上按键/转旋钮，是否会广播状态变化？
如果没有任何包到达，证明 X3 Pro 蓝牙是「单向命令通道」，
真正的状态同步只能采用「本地记忆为准、主动接管」模型。
"""
import asyncio
from bleak import BleakClient

ADDR = "628A1160-0E76-D5A7-CCB6-5DA73EC96391"
CHAR_FEC8 = "0000fec8-0000-1000-8000-00805f9b34fb"
CHAR_FFF4 = "0000fff4-0000-1000-8000-00805f9b34fb"
CHAR_FEC7 = "0000fec7-0000-1000-8000-00805f9b34fb"

received = []

async def main():
    async with BleakClient(ADDR, timeout=10.0) as client:
        print("已连接。开始纯被动监听 12 秒（不发送任何命令）...")
        print(">>> 请在这 12 秒内，在实体引闪器上转动旋钮或切换组别 <<<")

        def on_fec8(sender, data):
            received.append(("FEC8", data))
            print(f"[被动收到 FEC8] {data.hex(' ')}")

        def on_fff4(sender, data):
            received.append(("FFF4", data))
            print(f"[被动收到 FFF4] {data.hex(' ')}")

        await client.start_notify(CHAR_FEC8, on_fec8)
        await client.start_notify(CHAR_FFF4, on_fff4)

        for i in range(12):
            print(f"  监听中 {i+1}/12 秒...")
            await asyncio.sleep(1.0)

        # 再读一次 FEC7，确认它只是"最后写入帧"的回显
        try:
            val = await client.read_gatt_char(CHAR_FEC7)
            print(f"FEC7 当前缓存(前12字节): {val[:12].hex(' ')}")
        except Exception as e:
            print("FEC7 读取失败:", e)

        print(f"\n结论：12 秒内共收到 {len(received)} 个被动包")
        if len(received) == 0:
            print("判定：X3 Pro 不主动广播状态 → 蓝牙为单向命令通道")

if __name__ == "__main__":
    asyncio.run(main())
