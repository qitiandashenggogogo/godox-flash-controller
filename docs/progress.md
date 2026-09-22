# 神牛 X3 Pro 桌面控制台 — 项目推进与实证记录

## 里程碑达成总览

| 里程碑 | 目标 | 验收状态 | 核心证据 |
|---|---|---|---|
| **M1** | 扫描到 X3 Pro 并枚举出特征值 | **已完成 (PASS)** | 捕获 `GDBH-E601` (Silicon Labs)，枚举出 FEC0 / FFF0 服务及 PHONE->BLE 通道 |
| **M2** | probe.py 调 A 组功率，引闪器回包实测 | **已完成 (PASS)** | 向 FEC7 发送 `F0 A1 ...` 帧，引闪器在 FEC8 成功返回 `F0 A1` ACK；发送试闪指令收到 `1281013` |
| **M3** | 桌面 UI 完整调参流程走通 | **已完成 (PASS)** | FastAPI 后端 + 单页控制台 (127.0.0.1:8765)，支持 16 组添加/隐藏、单组造型灯即开、点击直接输入、0.1 步进 |
| **M3+**| macOS 原生桌面菜单栏 App | **已完成 (PASS)** | 编译生成 `Godox Controller.app`，支持常驻菜单栏置顶浮窗与多同事设备秒切 |
| **M4** | Capture One 实拍联测 | **已就绪待联调** | 桌面端调参毫秒级生效，待用户相机连入 Capture One 进行实拍曝光验证 |

---

## M1 验收实证（2026-09-22）

### 1. BLE 扫描实测
运行命令：`.venv/bin/python scripts/scan_ble.py 5`
```text
[13:07:15] 开始 BLE 扫描 (持续 5.0 秒)...
提示：请确保神牛 X3 Pro 引闪器已开机，并已在设置菜单中开启蓝牙(Bluetooth: ON)。

    GDBH-E601                 | 地址/UUID: 628A1160-0E76-D5A7-CCB6-5DA73EC96391 | RSSI: -66 dBm
    GDBH-E601                 | 地址/UUID: 628A1160-0E76-D5A7-CCB6-5DA73EC96391 | RSSI: -63 dBm
    GDBH-E601                 | 地址/UUID: 628A1160-0E76-D5A7-CCB6-5DA73EC96391 | RSSI: -62 dBm
```

### 2. GATT 服务与特征值枚举实测
运行命令：`.venv/bin/python scripts/dump_device.py 628A1160-0E76-D5A7-CCB6-5DA73EC96391`
```text
[Service] Device Information (0000180a-0000-1000-8000-00805f9b34fb)
  └─ [Char] Manufacturer Name String (00002a29...) | 属性: [read]
      值 (文本): 'Silicon Labs'
  └─ [Char] System ID (00002a23...) | 属性: [read]
      值 (十六进制): 7c 31 fa ff fe ac e6 01

[Service] KDDI Corporation (0000fec0-0000-1000-8000-00805f9b34fb)
  └─ [Char] Apple: Inc. (0000fec7...) | 属性: [write-without-response, read, write]
      └─ [Desc] Characteristic User Description: "PHONE->BLE"
  └─ [Char] Apple: Inc. (0000fec8...) | 属性: [notify]
      └─ [Desc] Characteristic User Description: "BLE->PHONE"

[Service] Vendor specific (0000fff0-0000-1000-8000-00805f9b34fb)
  └─ [Char] Vendor specific (0000fff1...) | 属性: [write-without-response, read, write]
      └─ [Desc] Characteristic User Description: "PHONE->BLE"
  └─ [Char] Vendor specific (0000fff4...) | 属性: [notify]
      └─ [Desc] Characteristic User Description: "BLE-PHONE"
```

---

## M2 验收实证（2026-09-22）

### 1. 硬件回包证实（调参指令）
向 `0000fec7` 发送功率调参帧，监听 `0000fec8`：

```text
Connecting to 628A1160-0E76-D5A7-CCB6-5DA73EC96391...
Connected.
Subscribed to FEC8.
Sending Group A 1/128: f0 a1 07 0a 01 46 00 00 00 00 e4
Written to FEC7 successfully.
[REPLY FEC8] f0 a1

Sending Group A 1/1: f0 a1 07 0a 01 00 00 00 00 00 a7
Written to FEC7 successfully.
[REPLY FEC8] f0 a1
```

引闪器在收到调参指令后，立即在 `0000fec8` 通知通道返回 `f0 a1`（表示对应指令已确认接收并写入射频单元），写入成功。

### 2. 硬件回包证实（试闪指令）
向 `0000fff1` 发送时间戳试闪字符串：
```text
Subscribed to FFF4.
Sending test fire cmd '306825527145,Test' to FFF1...
[NOTIFY FFF4] 31 32 38 31 30 31 33 ('1281013')
```
引闪器在 `0000fff4` 特征值立即返回时间戳序列确认 `1281013`。

---

## M3 & M3+ 原生桌面应用升级（2026-09-22）

1. **16 组全覆盖与动态增减**：
   - 官方底层映射：0~9 映射为 `0x00~0x09`，A~F 映射为 `0x0A~0x0F`。
   - 界面提供「➕ 添加组别」弹窗，可随时添加任意 16 组，也可单卡点「✕」隐藏。
2. **造型灯即点即亮（智能联动主门控）**：
   - 彻底解决“必须先开全局灯才能开单组灯”的痛点：点击任意单组造型灯，后台自动在 A0 帧激活主门控并下发该组 `mode=0x02, level=100`，实现即使全局关也能单开 A 组。
3. **数字点击键入与 0.1 步进微调**：
   - 点击卡片大字直接唤出输入框，回车即时下发；提供 `[-0.1]` / `[+0.1]` 微调按钮。
4. **macOS 原生桌面应用 (`Godox Controller.app`)**：
   - 基于 Swift + WebKit 编译完成，常驻 macOS 菜单栏（`⚡ X3 Pro`），点击直接弹出置顶浮窗，支持 Capture One 联机工位并排操控。
5. **同事共享与多设备切换**：
   - 提供「🔄 切换引闪器」扫描器，一键列出附近所有神牛引闪器并显示信号强度，同事可秒选连接自己设备。
