# 神牛引闪器桌面控制台（Godox Flash Controller）

macOS 菜单栏应用：通过蓝牙（BLE）连接神牛引闪器，在 Mac 上直接控制影棚闪光灯。

![界面截图](docs/screenshots/m3_ui_mvp.png)

## 功能

- 版本与更新：控制台显示当前版本；发现新版时菜单栏显示橙点，点击更新并确认安装后自动下载安装和重启，可稍后处理。默认后台检查，由用户主动安装，保留已有更新偏好。
- 菜单栏常驻：左键唤出控制台面板，右键快捷菜单（立即试闪 / 刷新 / 退出）
- 分组控制：组别开关、功率调节、频道切换、造型灯与蜂鸣开关
- 一键全局 OFF：保存当前组别状态快照，再点一次恢复原状
- 外观主题：深色 / 浅色 / 跟随 macOS 系统
- 点击窗口外任意位置自动收起面板

## 系统要求

- macOS 11 或更高版本
- Intel 与 Apple Silicon 通用（universal2 包）

## 从源码构建

```bash
bash build-app.sh                  # 只重编 Swift 外壳（秒级）
bash build-app.sh --bundle-backend # 连同 Python 后端一起打进 App（需 .venv 与 PyInstaller）
```

产出为 `Godox Controller.app`，内置后端，双击即用，无需安装 Python。

## 技术栈

- 外壳：Swift 5（AppKit + WebKit 浮动面板）
- 后端：Python（FastAPI + bleak 蓝牙）
- 前端：单页 HTML（`app/static/index.html`）

## 许可

[MIT License](LICENSE)。

「Godox / 神牛」名称与标志版权归神牛公司所有，本项目为非官方第三方工具，与神牛公司无关联。

## 更新提醒效果预览

```bash
bash scripts/build-update-preview.sh
open "/tmp/Godox Update Preview.app"
```

这是独立的预览应用，显示当前包版本与演示新版，并明确标注“不会实际更新”。
它不运行蓝牙、正式后端或更新器；点击更新只显示演示说明。正式构建不包含预览代码。
实际更新仍由 Sparkle 检查签名和安装。连接恢复只针对更新前确实连接的原地址，记录有目标 build、过期时间和一次性消费约束。

发布时需要同时提供安装包及匹配的已签名 `appcast.xml`；只上传源码或 DMG 不会自动产生应用内更新通知。
旧版本用户先安装支持橙点提示的版本，之后才会看到该提示；已有的更新检查偏好仍然有效。

更新相关测试：

```bash
bash scripts/test-update-ui.sh
```

本机隔离更新的验证不等于同事机器或真实蓝牙设备的验收。
