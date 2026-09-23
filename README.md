# 神牛引闪器桌面控制台（Godox Flash Controller）

macOS 菜单栏应用：通过蓝牙（BLE）连接神牛引闪器，在 Mac 上直接控制影棚闪光灯。

![界面截图](docs/screenshots/m3_ui_mvp.png)

## 功能

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
