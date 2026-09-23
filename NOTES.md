# NOTES.md — 踩坑记录

<!-- 新记录插在这一行下面 -->

## 2026-09-23 打 universal2 包时 pydantic-core 只发了分架构 wheel，PyInstaller 收集不到 x86_64 版

- **问题描述**：`build-app.sh --bundle-backend` 加 `--target-architecture universal2` 后，打出的包里 `pydantic_core/_pydantic_core.*.so` 仍是 arm64 单架构，Intel Mac 上会 import 失败；用 `pip download --platform macosx_10_13_universal2` 想直接下 universal wheel 时报「from versions: 0.0.1」。
- **原因分析**：pydantic-core 只发布分架构 wheel（`macosx_11_0_arm64` / `macosx_10_12_x86_64`），没有 universal2 wheel，所以 venv 里本来就只有 arm64 的 .so，PyInstaller 原样收集，universal2 打包缺一块拼图。
- **解决方案**：单独 `pip download pydantic-core==<当前版本> --platform macosx_10_12_x86_64 --python-version 3.12 --no-deps -d <临时目录>`，解出 x86_64 的 .so，用 `lipo -create` 与 venv 里的 arm64 .so 合成 fat 二进制后覆盖回 venv（留 .bak 备份）；随后 PyInstaller 就能收集到 universal2 .so。验证：构建后 `find 包内 -name "*.so" | xargs lipo -info` 全部显示 x86_64+arm64，并用 `arch -x86_64 <后端二进制>` 在 Rosetta 下实测启动 + curl /api/health。

## 2026-09-23 用 SVG 官方标志做 App 图标，qlmanage 转出的 PNG 带白底且内容缩在角落

- **问题描述**：想把 `assets/icon/godox.svg` 合成图标 PNG，先用 `qlmanage -t -s` 把 SVG 转 PNG 再拿 AppKit 合成，结果转出的图是不透明白底、标志只在左上角一小块，合成出来的图标是白方块里一个迷你 logo。
- **原因分析**：qlmanage 的 SVG 缩略图渲染不尊重 SVG 自身的透明背景与 viewBox 排版，输出是带白底的整幅画布；按 alpha 通道扫描包围盒会铺满全图，裁切逻辑失效。另外直接在 Chrome 里打开 `.svg` 文件得到的是纯 SVG XML 文档，`document.createElement('canvas')` 产不出可用的 HTMLCanvasElement，合成脚本要在 HTML 页面（如 about:blank）里跑。
- **解决方案**：不经过 qlmanage，把 SVG 源码内联成字符串，在 Chrome 普通页面里用 Blob → Image → canvas 画圆角深色底再 drawImage 标志，`toDataURL('image/png')` 导出后用 python3 标准库 base64 解码落盘，再 `sips -z` 出 iconset 各尺寸、`iconutil -c icns` 打包。全程零新依赖（不装 Pillow）。

## 2026-09-23 改了前端页面，打包版 App 里却没变

- **问题描述**：修改 `app/static/index.html` 后运行 `bash build-app.sh` 并重启 App，页面仍是旧内容。
- **原因分析**：`build-app.sh` 默认只重编译 Swift 外壳；打包版 App 显示的是 PyInstaller 打进 `Godox Controller.app/Contents/Resources/backend` 里的那份 `app/static` 副本，不带 `--bundle-backend` 就不会更新。另外旧的后端进程如果没被杀掉，Swift 外壳检测到健康服务会直接复用，新包也不会生效。
- **解决方案**：改前端/后端代码后要打包生效，必须 `bash build-app.sh --bundle-backend`；重启前先 `pkill -f "Godox Controller.app"` 和 `pkill -f GodoxControllerBackend`，再 `open -n "Godox Controller.app"`，最后用 `curl --noproxy '*' -s http://127.0.0.1:8765/ | grep '<title>'` 验证。
