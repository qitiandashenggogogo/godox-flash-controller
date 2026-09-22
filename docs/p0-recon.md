# 神牛 X3 Pro 桌面控制台 — P0 侦察与硬件协议判定记录

## 1. 扫描与设备识别

在 macOS 本机运行基于 `bleak` 的扫描脚本对附近 BLE 广播进行持续监听与元数据提取，成功捕获神牛 X3 Pro 引闪器：

- **广播设备名**：`GDBH-E601`
  - 命名规则解释：`GD` 即 Godox（神牛），`BH` 即 Bluetooth Host（蓝牙主机/引闪器），`-E601` 即引闪器蓝牙 MAC 地址后 4 位（屏幕蓝牙菜单左下角显示的 MAC 校验码）。
- **CoreBluetooth UUID**：`628A1160-0E76-D5A7-CCB6-5DA73EC96391`
- **硬件芯片平台**：Silicon Labs（芯科科技 EFR32 系列 BLE SoC，设备信息服务 0x180A 的 Manufacturer Name 返回 `Silicon Labs`，System ID: `7c 31 fa ff fe ac e6 01`）
- **实测信号强度**：-61 ~ -66 dBm（稳定近场信号）

## 2. GATT 服务与特征值枚举

经过对 `GDBH-E601` 的全量 GATT 枚举，提取到以下关键服务与特征值：

```
[Service] Device Information (0000180a-0000-1000-8000-00805f9b34fb)
  └─ [Char] Manufacturer Name: 'Silicon Labs' (00002a29) | [read]
  └─ [Char] System ID: 7c 31 fa ff fe ac e6 01 (00002a23) | [read]

[Service] 调参控制服务 (0000fec0-0000-1000-8000-00805f9b34fb)
  └─ [Char] 写入通道 PHONE->BLE (0000fec7-0000-1000-8000-00805f9b34fb)
      属性: [write-without-response, read, write]
      User Description: "PHONE->BLE"
  └─ [Char] 通知通道 BLE->PHONE (0000fec8-0000-1000-8000-00805f9b34fb)
      属性: [notify]
      User Description: "BLE->PHONE"

[Service] 触发与同步服务 (0000fff0-0000-1000-8000-00805f9b34fb)
  └─ [Char] 写入通道 PHONE->BLE (0000fff1-0000-1000-8000-00805f9b34fb)
      属性: [write-without-response, read, write]
      User Description: "PHONE->BLE"
  └─ [Char] 通知通道 BLE->PHONE (0000fff4-0000-1000-8000-00805f9b34fb)
      属性: [notify]
      User Description: "BLE-PHONE"

[Service] OTA 固件升级服务 (1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0)
  └─ [Char] Gecko Bootloader (f7bf3564-fb6d-4e53-88a4-5e37e0326063) | [write]
```

## 3. 核心问题判定结论

**问题：X3 Pro 的蓝牙是 Godox mesh 同族协议，还是独立的点对点 BLE 协议？**

**实测判定结论**：
1. **绝对非 Godox Mesh 协议**：Godox 影视灯/常亮灯（如 SL/UL/TL 系列）使用 Telink BLE Mesh 广播与代理服务（0x1828 / 0x2ADD / 0x2ADE），而 X3 Pro 采用的是 Silicon Labs EFR32 芯片上的**点对点 BLE 透传 GATT 协议**。
2. **无高难度配对加密门槛**：官方手册记载的 000000 为默认从机重置密码；经逆向官方 Godox Flash Android APK（com.linking.godoxflash）证实，BLE 控制通道在底层直接接受明文 11 字节协议帧，**无需复杂密钥派生或配对加密流程**。
3. **路线选择：确定采用「BLE 直连桌面 App」路线，完全无需降级到 Android SDK 桥接方案！**
