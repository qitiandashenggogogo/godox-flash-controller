# 引闪器电量取证

工具：`scripts/capture_battery_evidence.py`，使用项目 `.venv` 中的 Bleak。

macOS 实机录制先执行 `bash scripts/build-battery-capture.sh`，使用输出的本机 `Godox Battery Evidence.app`。它有独立 Bundle ID、蓝牙用途声明和 ad hoc 签名，仅用于本机研究，不使用正式应用的签名密钥。首次运行可能需要您在系统提示中允许蓝牙。下面的 Python 命令适用于已有合规蓝牙用途声明的运行环境；普通 `.venv` Python 未必具备该声明，不能据此认定权限可用。实机用法是将命令中的 `.venv/bin/python scripts/capture_battery_evidence.py` 换成 `"<LOCAL_APP>/Contents/MacOS/GodoxBatteryEvidence"`。

系统蓝牙权限列表显示的名称是 **Godox Battery Evidence**，不保证采用 `CFBundleDisplayName` 中的中文名称。不要误认成正式控制台 Godox Controller。

记录仅存本机，含设备标识、原始帧及人工填写的机身读数。默认创建权限为0600的新JSONL，不覆盖已有文件。它不发送应用调参、试闪或未知查询命令，默认不读取私有FEC7/FFF1。订阅/退订通知会涉及标准CCCD控制操作。

## 仅观察目标广播

```sh
.venv/bin/python scripts/capture_battery_evidence.py \
  --address '<已确认的 macOS 设备 UUID>' \
  --output 'dist/battery-evidence/advertisements.jsonl' \
  --scan-only --scan-seconds 8
```

只保留指定设备的macOS API可见字段。当前正式后端占用情况写入记录；设备若已被控制台或手机连接，可能不广播，未观察到不能证明无广播或无电量。

## 连接录制

先正常退出Godox Controller，并释放iPhone官方App的设备连接。录制期间不要重新打开控制台。引闪器保持开机、蓝牙开启，人工记录机身电量及时间。

```sh
.venv/bin/python scripts/capture_battery_evidence.py \
  --address '<已确认的 macOS 设备 UUID>' \
  --output 'dist/battery-evidence/session-01.jsonl' \
  --model 'X3 Pro S' --firmware 'v1.03' --screen-battery '85%' \
  --scan-seconds 8 --seconds 20
```

这里的85%只是命令示例，执行时填写当时实际机身读数。型号、固件、电量都标为人工参考，不代表BLE已经验证。

工具持有与正式后端相同的`backend.lock`互斥锁，录制结束才释放；只锁定文件，不截断或改写身份内容。尊重`GODOX_CONTROLLER_STATE_DIR`，默认目录还检查旧版8765后端。正式后端仍运行时拒绝连接录制。录制结束并确认进程退出后，可以重新打开控制台。

枚举服务/特征/描述符，仅读取标准BAS电量和DIS白名单。仅订阅已知FEC8、FFF4与Battery Level通知；新的未知通知特征会被枚举但不自动订阅。保留已知/未知载荷，不先按A0/A1过滤。

可选补查：加 `--read-control-values` 时，仅在实际声明 read 属性且服务/特征同时匹配 FEC0/FEC7 或 FFF0/FFF1 时，各执行一次 GATT Read。该选项不写应用命令、不自动扩大到其他特征，也不把这些原值解析成百分比。读到单字节89或100也只能当线索，必须另行验证字段语义；读失败记录错误而不改成写查询。前两轮历史录制未启用此选项。

连接12秒超时；读/订阅5秒超时；录制主体上限为指定通知观察时长加60秒，随后逐项有界清理（每次退订3秒、断连5秒）。整个扫描与连接会话另有通知观察时长加扫描时长加90秒的总预算。中途取消也会尝试清理。断连未确认时记录错误并以失败退出，不将其说成完成。

时间为主机接收时间，不是空口时间。一次运行只连接一次，不重连，使用一代次UUID。失效后的迟到帧在记录仍开放时保留并标discarded，不计入有效通知。文件关闭后的回调被忽略。

`application_command_writes_by_construction=0`来自工具代码没有应用写调用，不是抓包仪的观测统计。订阅失败、超时、意外断开可见；无通知只意味着观察窗口未取得，不足以判定电量协议不存在。

## 验证范围

```sh
.venv/bin/python -m unittest discover -s tests -p test_battery_capture.py -v
```

测试使用mock验证写入边界、真实0%、晚到通知、错误、超时、取消与锁定。它不证明实机BLE权限、设备字段语义或电量映射已经成功。
