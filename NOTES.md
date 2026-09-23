# NOTES.md — 踩坑记录

<!-- 新记录插在这一行下面 -->

## 2026-09-23 用 SVG 官方标志做 App 图标，qlmanage 转出的 PNG 带白底且内容缩在角落

- **问题描述**：想把 `assets/icon/godox.svg` 合成图标 PNG，先用 `qlmanage -t -s` 把 SVG 转 PNG 再拿 AppKit 合成，结果转出的图是不透明白底、标志只在左上角一小块，合成出来的图标是白方块里一个迷你 logo。
- **原因分析**：qlmanage 的 SVG 缩略图渲染不尊重 SVG 自身的透明背景与 viewBox 排版，输出是带白底的整幅画布；按 alpha 通道扫描包围盒会铺满全图，裁切逻辑失效。另外直接在 Chrome 里打开 `.svg` 文件得到的是纯 SVG XML 文档，`document.createElement('canvas')` 产不出可用的 HTMLCanvasElement，合成脚本要在 HTML 页面（如 about:blank）里跑。
- **解决方案**：不经过 qlmanage，把 SVG 源码内联成字符串，在 Chrome 普通页面里用 Blob → Image → canvas 画圆角深色底再 drawImage 标志，`toDataURL('image/png')` 导出后用 python3 标准库 base64 解码落盘，再 `sips -z` 出 iconset 各尺寸、`iconutil -c icns` 打包。全程零新依赖（不装 Pillow）。

## 2026-09-23 改了前端页面，打包版 App 里却没变

- **问题描述**：修改 `app/static/index.html` 后运行 `bash build-app.sh` 并重启 App，页面仍是旧内容。
- **原因分析**：`build-app.sh` 默认只重编译 Swift 外壳；打包版 App 显示的是 PyInstaller 打进 `Godox Controller.app/Contents/Resources/backend` 里的那份 `app/static` 副本，不带 `--bundle-backend` 就不会更新。另外旧的后端进程如果没被杀掉，Swift 外壳检测到健康服务会直接复用，新包也不会生效。
- **解决方案**：改前端/后端代码后要打包生效，必须 `bash build-app.sh --bundle-backend`；重启前先 `pkill -f "Godox Controller.app"` 和 `pkill -f GodoxControllerBackend`，再 `open -n "Godox Controller.app"`，最后用 `curl --noproxy '*' -s http://127.0.0.1:8765/ | grep '<title>'` 验证。
